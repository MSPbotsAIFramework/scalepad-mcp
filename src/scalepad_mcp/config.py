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
"""Process settings and ScalePad endpoints. Holds no credentials."""

from pydantic_settings import BaseSettings, SettingsConfigDict

REGION_HOSTS: dict[str, str] = {
    "us": "https://api.scalepad.com",
    "eu": "https://eu.api.scalepad.com",
    "ca": "https://ca.api.scalepad.com",
    "au": "https://au.api.scalepad.com",
}
DEFAULT_REGION = "us"

# Where each product is deployed. Core, Lifecycle Manager and Quoter answer
# only on the US edge; ControlMap in every region; Backup Radar in US and EU.
PRODUCT_REGIONS: dict[str, tuple[str, ...]] = {
    "core": ("us",),
    "lm": ("us",),
    "quoter": ("us",),
    "cm": ("us", "eu", "ca", "au"),
    "br": ("us", "eu"),
}
# Path prefix added in front of the operation path (Quoter is served under /quoter).
PRODUCT_PREFIX: dict[str, str] = {"quoter": "/quoter"}
PRODUCT_NAMES: dict[str, str] = {
    "core": "Core",
    "lm": "Lifecycle Manager",
    "cm": "ControlMap",
    "br": "Backup Radar",
    "quoter": "Quoter",
}


class Settings(BaseSettings):
    # extra="ignore": the runtime injects variables this project does not declare.
    model_config = SettingsConfigDict(extra="ignore")

    mcp_http_port: int = 8080
    mcp_http_host: str = "0.0.0.0"
    log_level: str = "INFO"


def get_settings() -> Settings:
    return Settings()
