"""Constants for the Pastatoinfo IRTC integration."""
from __future__ import annotations

from dataclasses import dataclass

DOMAIN = "pastatoinfo_irtc"

CONF_DATABASE = "database"
CONF_OBJECTS = "objects"

# Legal heating season for buildings with automated heat-distribution points
# (Lithuanian Heat Supply Law amendment, effective 2026-10-01): Oct 1 - Apr 30.
# This integration only ever sees data for such buildings, so heating sync is
# gated on this fixed window instead of a manual toggle.
HEATING_SEASON_START_MONTH = 10
HEATING_SEASON_END_MONTH = 4

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
    unit_class: str  # recorder statistics unit class ("energy" / "volume")
    name: str
    icon: str
    is_heating: bool = False


RESOURCE_HEATING = Resource(
    key="heating",
    tipas="SILUM_SK",
    unit="kWh",
    unit_class="energy",
    name="Heating",
    icon="mdi:radiator",
    is_heating=True,
)
RESOURCE_HOT_WATER = Resource(
    key="hot_water",
    tipas="K_VAND_SK",
    unit="m³",
    unit_class="volume",
    name="Hot water",
    icon="mdi:water-thermometer",
)
RESOURCE_COLD_WATER = Resource(
    key="cold_water",
    tipas="S_VAND_SK",
    unit="m³",
    unit_class="volume",
    name="Cold water",
    icon="mdi:water",
)

ALL_RESOURCES: tuple[Resource, ...] = (
    RESOURCE_HEATING,
    RESOURCE_HOT_WATER,
    RESOURCE_COLD_WATER,
)


def total_unique_id(entry_id: str, object_id: str, resource_key: str) -> str:
    """Unique id of the running-total sensor whose entity_id backs the statistic.

    Shared between sensor.py (creates the entity) and coordinator.py (looks up
    its entity_id via the entity registry to import statistics onto it).
    """
    return f"{entry_id}_{object_id}_{resource_key}_total"
