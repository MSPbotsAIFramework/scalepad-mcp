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
"""Tool discovery per product and the connection check."""

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .._json import compact as to_json
from ..api_client import ScalePadClient, ScalePadError
from ..catalog import TOOLS
from ..config import PRODUCT_NAMES, PRODUCT_REGIONS
from ._common import LOCAL, READ_ONLY, ClientFactory, run_tool

DOMAIN_TO_PRODUCT = {"core": "core", "lifecycle-manager": "lm", "controlmap": "cm", "backup-radar": "br", "quoter": "quoter"}
DOMAIN_SUMMARY = {
    "core": "Unified MSP data, read-only: clients, contacts, members, sites, opportunities, assets, contracts, tickets.",
    "lifecycle-manager": "Initiatives, goals, meetings, action items, assessments, deliverables, budgets, contracts, assets.",
    "controlmap": "Compliance per client: risks, controls, evidence, policies, procedures, assessments, action items.",
    "backup-radar": "Backup health and backup devices per client (read-only).",
    "quoter": "Quotes, quote templates, catalog items, categories, contacts and suppliers.",
}
# A cheap read per product, used to check which subscriptions the key covers.
PROBES = {
    "core": "/core/v1/clients",
    "lm": "/lifecycle-manager/v1/client-groups",
    "cm": "/controlmap/v1/clients/health",
    "br": "/backup-radar/v3/clients/devices",
    "quoter": "/v1/manufacturers",
}


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=LOCAL)
    async def scalepad_navigate(
        domain: Annotated[
            Literal["core", "lifecycle-manager", "controlmap", "backup-radar", "quoter"],
            Field(description="Product to describe."),
        ],
    ) -> str:
        """List one ScalePad product's tools with a one-line purpose each. All tools are already callable."""
        product = DOMAIN_TO_PRODUCT[domain]
        tools = [{"name": t["name"], "kind": t["kind"], "purpose": t["summary"]} for t in TOOLS if t["product"] == product]
        return to_json(
            {
                "domain": domain,
                "summary": DOMAIN_SUMMARY[domain],
                "regions": list(PRODUCT_REGIONS[product]),
                "tool_count": len(tools),
                "tools": tools,
            }
        )

    @mcp.tool(annotations=READ_ONLY)
    async def scalepad_status() -> str:
        """Check the ScalePad API key and region, and which products it can reach (all five products)."""

        async def action(client: ScalePadClient) -> dict:
            products = {}
            for product, path in PROBES.items():
                try:
                    await client.request("GET", product, path, query=[("page_size", "1")] if product != "lm" else None)
                    products[PRODUCT_NAMES[product]] = {"reachable": True}
                except ScalePadError as e:
                    products[PRODUCT_NAMES[product]] = {"reachable": False, "status": e.status_code, "error": e.message}
            return {
                "region": client.region,
                "products": products,
                "domains": DOMAIN_SUMMARY,
                "note": (
                    "402 means no subscription for that product; Core, Lifecycle Manager and Quoter are "
                    "US-only, Backup Radar is US and EU."
                ),
            }

        return await run_tool("scalepad_status", client_factory, action)
