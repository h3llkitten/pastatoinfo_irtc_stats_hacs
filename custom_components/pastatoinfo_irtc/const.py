"""Constants for the Pastatoinfo IRTC integration."""
from __future__ import annotations

from dataclasses import dataclass

DOMAIN = "pastatoinfo_irtc"

CONF_DATABASE = "database"
CONF_OBJECTS = "objects"
CONF_IMPORT_HEATING = "import_heating"

# Fixed start of the historical import.
HISTORY_START_YEAR = 2025
HISTORY_START_MONTH = 1

# Daily sync anchor: 02:11 UTC + random offset within an hour.
SYNC_HOUR_UTC = 2
SYNC_MINUTE_UTC = 11
SYNC_RANDOM_WINDOW_SEC = 3600

# Portal data is bucketed in Lithuanian local days.
PORTAL_TIMEZONE = "Europe/Vilnius"

# All meter data (heating + both waters) lives in this database; never ask.
PREFERRED_DATABASE = "NIS_VILNIUS"

SERVICE_SYNC = "sync"


@dataclass(frozen=True)
class Resource:
    """One meter resource exposed by the portal."""

    key: str
    tipas: str
    unit: str
    name: str
    icon: str
    is_heating: bool = False


RESOURCE_HEATING = Resource(
    key="heating",
    tipas="SILUM_SK",
    unit="kWh",
    name="Heating",
    icon="mdi:radiator",
    is_heating=True,
)
RESOURCE_HOT_WATER = Resource(
    key="hot_water",
    tipas="K_VAND_SK",
    unit="m³",
    name="Hot water",
    icon="mdi:water-thermometer",
)
RESOURCE_COLD_WATER = Resource(
    key="cold_water",
    tipas="S_VAND_SK",
    unit="m³",
    name="Cold water",
    icon="mdi:water",
)

ALL_RESOURCES: tuple[Resource, ...] = (
    RESOURCE_HEATING,
    RESOURCE_HOT_WATER,
    RESOURCE_COLD_WATER,
)
