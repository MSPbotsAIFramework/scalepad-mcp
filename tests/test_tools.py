# Copyright 2026 MSPbots.ai
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""tools/list contract, descriptions, annotations and the catalog's consistency. No network."""

import asyncio
import json
import re
from pathlib import Path

import pytest

from scalepad_mcp.api_client import ScalePadError
from scalepad_mcp.catalog import TOOLS
from scalepad_mcp.server import INSTRUCTIONS, create_mcp_server

# Tool names and required parameters are a public contract: existing agents
# and tenant connections depend on them. Changing contract.json is a breaking change.
CONTRACT: dict[str, list[str]] = json.loads((Path(__file__).parent / "contract.json").read_text())
CATALOG = {e["name"]: e for e in TOOLS}


@pytest.fixture(scope="module")
def tools():
    return {t.name: t for t in asyncio.run(create_mcp_server().list_tools())}


def test_tool_names_are_stable(tools):
    assert set(tools) == set(CONTRACT)
    assert len(tools) == 381


def test_required_params_are_stable(tools):
    changed = {n: (sorted(t.inputSchema.get("required", [])), CONTRACT[n]) for n, t in tools.items() if sorted(t.inputSchema.get("required", [])) != CONTRACT[n]}
    assert changed == {}


def test_descriptions_within_budget(tools):
    too_long = [n for n, t in tools.items() if len(t.description or "") > 500 or len((t.description or "").splitlines()[0]) > 100]
    empty = [n for n, t in tools.items() if not (t.description or "").strip()]
    assert too_long == [] and empty == []


def test_annotations_follow_catalog_kind(tools):
    wrong = []
    for name, entry in CATALOG.items():
        ann = tools[name].annotations
        if entry["kind"] == "read" and ann.readOnlyHint is not True:
            wrong.append(name)
        if entry["kind"] == "destructive" and not (ann.readOnlyHint is False and ann.destructiveHint is True):
            wrong.append(name)
        if entry["kind"] == "write" and not (ann.readOnlyHint is False and ann.destructiveHint is False):
            wrong.append(name)
    assert wrong == []


def test_deletes_are_destructive_and_writes_say_when_to_use_them(tools):
    for name, entry in CATALOG.items():
        if entry["method"] == "DELETE" and not name.endswith(("_detach", "_unmap", "_unassign", "_unmap_question")):
            assert entry["kind"] == "destructive", name
        if entry["kind"] in ("write", "destructive"):
            assert "explicitly asks" in tools[name].description, name


def test_catalog_paths_and_targets_are_consistent():
    for entry in TOOLS:
        if entry["special"] == "unsupported":
            continue
        placeholders = set(re.findall(r"\{([^}]+)\}", entry["path"] or ""))
        filled = {a["to"][1] for a in entry["args"] if a.get("to") and a["to"][0] == "path"}
        assert placeholders == filled, entry["name"]
        for arg in entry["args"]:
            if arg.get("to") and arg["to"][0] == "path":
                assert arg["required"], (entry["name"], arg["name"])


def test_products_and_prefixes():
    prefixes = {"core": "/core/", "lm": "/lifecycle-manager/", "cm": "/controlmap/", "br": "/backup-radar/", "quoter": "/v1/"}
    for entry in TOOLS:
        assert entry["name"].startswith(f"scalepad_{entry['product']}_")
        if entry["path"]:
            assert entry["path"].startswith(prefixes[entry["product"]]), entry["name"]


def test_instructions_budget():
    assert len(INSTRUCTIONS) <= 1500


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (401, "unauthorized", False),
        (402, "unauthorized", False),
        (403, "unauthorized", False),
        (404, "not_found", False),
        (400, "invalid_argument", False),
        (422, "invalid_argument", False),
        (429, "rate_limited", True),
        (500, "upstream_error", True),
        (0, "upstream_error", True),
    ],
)
def test_error_envelope(status, code, retryable):
    envelope = json.loads(ScalePadError(status, "boom").to_envelope())
    assert envelope == {"error": {"code": code, "message": "boom", "retryable": retryable}}


def test_tool_without_credentials_returns_not_configured():
    content, _ = asyncio.run(create_mcp_server().call_tool("scalepad_core_clients_list", {}))
    assert json.loads(content[0].text)["error"]["code"] == "not_configured"


def test_navigate_lists_a_product_without_credentials():
    content, _ = asyncio.run(create_mcp_server().call_tool("scalepad_navigate", {"domain": "backup-radar"}))
    result = json.loads(content[0].text)
    assert result["regions"] == ["us", "eu"]
    assert {t["name"] for t in result["tools"]} == {
        "scalepad_br_backups_list_health",
        "scalepad_br_backups_get_health",
        "scalepad_br_backups_list_devices",
    }
