"""Sensors: last-day and month-to-date consumption per object and resource."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
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
            entities.append(
                PastatoInfoSensor(coordinator, object_id, object_name, resource, "last_day")
            )
            entities.append(
                PastatoInfoSensor(coordinator, object_id, object_name, resource, "month")
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
        self._attr_unique_id = f"{entry_id}_{object_id}_{resource.key}_{kind}"
        self._attr_native_unit_of_measurement = resource.unit
        self._attr_icon = resource.icon
        self._attr_suggested_display_precision = 3 if resource.unit == "m³" else 0
        if kind == "last_day":
            self._attr_translation_key = f"{resource.key}_last_day"
        else:
            self._attr_translation_key = f"{resource.key}_month"
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
        return values["month_total"]

    @property
    def extra_state_attributes(self) -> dict | None:
        values = self._values
        if values is None:
            return None
        if self._kind == "last_day":
            day = values["last_day_date"]
            return {"date": day.isoformat() if day else None}
        return {"month": values["month"]}
