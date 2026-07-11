"""Sensors: last-day, month-to-date, and running-total consumption."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, Resource
from .coordinator import PastatoInfoCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: PastatoInfoCoordinator = entry.runtime_data
    entities: list[SensorEntity] = []
    for object_id, object_name in coordinator.objects.items():
        for resource in coordinator.enabled_resources:
            for kind in ("last_day", "month", "prev_month", "total"):
                entities.append(
                    PastatoInfoSensor(coordinator, object_id, object_name, resource, kind)
                )
    async_add_entities(entities)


class PastatoInfoSensor(CoordinatorEntity[PastatoInfoCoordinator], SensorEntity):
    """One consumption value pulled from the portal."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PastatoInfoCoordinator,
        object_id: str,
        object_name: str,
        resource: Resource,
        kind: str,
    ) -> None:
        super().__init__(coordinator)
        self._object_id = object_id
        self._resource = resource
        self._kind = kind
        entry_id = coordinator.entry.entry_id
        # kind="total" must match const.total_unique_id() exactly: the
        # coordinator looks this entity up by unique_id to import statistics
        # onto its entity_id (apexcharts-card requires a live entity, which a
        # bare external statistic id can never be).
        self._attr_unique_id = f"{entry_id}_{object_id}_{resource.key}_{kind}"
        self._attr_native_unit_of_measurement = resource.unit
        self._attr_icon = resource.icon
        self._attr_suggested_display_precision = 3 if resource.unit == "m³" else 0
        self._attr_translation_key = f"{resource.key}_{kind}"
        if kind == "total":
            self._attr_device_class = (
                SensorDeviceClass.ENERGY
                if resource.is_heating
                else SensorDeviceClass.WATER
            )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{object_id}")},
            name=f"Pastatoinfo {object_name}",
            manufacturer="IRTC",
            configuration_url="https://pastatoinfo.irtc.lt",
        )

    @property
    def _values(self) -> dict | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get((self._object_id, self._resource.key))

    @property
    def native_value(self):
        values = self._values
        if values is None:
            return None
        if self._kind == "last_day":
            return values["last_day_value"]
        if self._kind == "prev_month":
            return values["prev_month_total"]
        if self._kind == "total":
            return values["total"]
        return values["month_total"]

    @property
    def extra_state_attributes(self) -> dict | None:
        values = self._values
        if values is None:
            return None
        if self._kind == "last_day":
            day = values["last_day_date"]
            return {"date": day.isoformat() if day else None}
        if self._kind == "prev_month":
            return {"month": values["prev_month"]}
        if self._kind == "total":
            return None
        return {"month": values["month"]}
