"""Pastatoinfo IRTC integration setup."""
from __future__ import annotations

import logging
import os

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import aiohttp_client

from homeassistant.helpers import device_registry as dr

from .api import PastatoInfoClient
from .const import CONF_DATABASE, CONF_OBJECTS, DOMAIN, SERVICE_SYNC
from .coordinator import PastatoInfoCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BUTTON]

type PastatoInfoConfigEntry = ConfigEntry[PastatoInfoCoordinator]


def _cookie_path(hass: HomeAssistant, entry: ConfigEntry) -> str:
    return hass.config.path(f".storage/{DOMAIN}.{entry.entry_id}.cookies")


async def async_setup_entry(
    hass: HomeAssistant, entry: PastatoInfoConfigEntry
) -> bool:
    cookie_jar = aiohttp.CookieJar()
    path = _cookie_path(hass, entry)

    def _load_cookies() -> None:
        if os.path.exists(path):
            try:
                cookie_jar.load(path)
            except Exception:  # corrupt/stale jar → just log in again
                _LOGGER.debug("Could not load cookie jar, starting fresh")

    await hass.async_add_executor_job(_load_cookies)

    session = aiohttp_client.async_create_clientsession(hass, cookie_jar=cookie_jar)
    client = PastatoInfoClient(
        session,
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        entry.data.get(CONF_DATABASE),
    )

    async def _save_cookies() -> None:
        await hass.async_add_executor_job(cookie_jar.save, path)

    coordinator = PastatoInfoCoordinator(hass, entry, client, _save_cookies)
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Initial sync in the background (may import 1.5 years of history),
    # then hand over to the daily scheduler.
    async def _startup_sync() -> None:
        await coordinator.async_refresh()
        coordinator.schedule_daily_sync()

    entry.async_create_background_task(hass, _startup_sync(), f"{DOMAIN}_startup_sync")

    if not hass.services.has_service(DOMAIN, SERVICE_SYNC):

        async def _handle_sync(_call: ServiceCall) -> None:
            for loaded in hass.config_entries.async_loaded_entries(DOMAIN):
                await loaded.runtime_data.async_refresh()

        hass.services.async_register(DOMAIN, SERVICE_SYNC, _handle_sync)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: PastatoInfoConfigEntry
) -> bool:
    entry.runtime_data.cancel_daily_sync()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow deleting devices that no longer match a configured object."""
    active = {
        f"{entry.entry_id}_{object_id}" for object_id in entry.data[CONF_OBJECTS]
    }
    return not any(
        domain == DOMAIN and identifier in active
        for domain, identifier in device_entry.identifiers
    )


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up the persisted cookie jar."""
    path = _cookie_path(hass, entry)

    def _remove() -> None:
        if os.path.exists(path):
            os.remove(path)

    await hass.async_add_executor_job(_remove)
