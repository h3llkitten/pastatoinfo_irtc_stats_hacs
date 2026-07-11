"""Resync-now button."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import PastatoInfoCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([PastatoInfoResyncButton(entry.runtime_data)])


class PastatoInfoResyncButton(ButtonEntity):
    """Trigger an immediate sync/backfill run."""

    _attr_has_entity_name = True
    _attr_translation_key = "resync"

    def __init__(self, coordinator: PastatoInfoCoordinator) -> None:
        self._coordinator = coordinator
        entry = coordinator.entry
        self._attr_unique_id = f"{entry.entry_id}_resync"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="IRTC",
            configuration_url="https://pastatoinfo.irtc.lt",
        )

    async def async_press(self) -> None:
        await self._coordinator.async_refresh()
