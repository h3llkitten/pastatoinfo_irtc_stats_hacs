"""Config flow: credentials → database → objects → confirm import."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import PastatoInfoAuthError, PastatoInfoClient, PastatoInfoError
from .const import (
    CONF_DATABASE,
    CONF_IMPORT_HEATING,
    CONF_OBJECTS,
    DOMAIN,
    HISTORY_START_MONTH,
    HISTORY_START_YEAR,
    PREFERRED_DATABASE,
)

_LOGGER = logging.getLogger(__name__)


class PastatoInfoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the UI setup of a pastatoinfo account."""

    VERSION = 1

    def __init__(self) -> None:
        self._client: PastatoInfoClient | None = None
        self._username: str = ""
        self._password: str = ""
        self._databases: list[str] = []
        self._database: str | None = None
        self._objects: dict[str, str] = {}
        self._selected_objects: dict[str, str] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]
            session = aiohttp_client.async_create_clientsession(
                self.hass, cookie_jar=aiohttp.CookieJar()
            )
            self._client = PastatoInfoClient(session, self._username, self._password)
            try:
                await self._client.async_login()
                self._databases = await self._client.async_get_databases()
            except PastatoInfoAuthError:
                errors["base"] = "invalid_auth"
            except PastatoInfoError:
                errors["base"] = "cannot_connect"
            except aiohttp.ClientError:
                errors["base"] = "cannot_connect"
            else:
                # All meter data lives in NIS_VILNIUS; fall back to the only
                # available database for accounts that don't have it.
                if PREFERRED_DATABASE in self._databases:
                    self._database = PREFERRED_DATABASE
                else:
                    self._database = self._databases[0] if self._databases else None
                return await self._load_objects()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def _load_objects(self) -> config_entries.ConfigFlowResult:
        assert self._client is not None
        try:
            if self._database:
                await self._client.async_set_database(self._database)
            self._objects = await self._client.async_get_objects()
        except PastatoInfoError:
            return self.async_abort(reason="cannot_connect")
        if not self._objects:
            return self.async_abort(reason="no_objects")
        return await self.async_step_objects()

    async def async_step_objects(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            self._selected_objects = {
                object_id: self._objects[object_id]
                for object_id in user_input[CONF_OBJECTS]
            }
            return await self.async_step_confirm()

        return self.async_show_form(
            step_id="objects",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_OBJECTS, default=list(self._objects)
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": object_id, "label": name}
                                for object_id, name in self._objects.items()
                            ],
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            await self.async_set_unique_id(
                f"{self._username}_{self._database or 'default'}".lower()
            )
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"Pastatoinfo ({self._username})",
                data={
                    CONF_USERNAME: self._username,
                    CONF_PASSWORD: self._password,
                    CONF_DATABASE: self._database,
                    CONF_OBJECTS: self._selected_objects,
                },
                options={
                    CONF_IMPORT_HEATING: user_input[CONF_IMPORT_HEATING],
                },
            )

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema(
                {vol.Required(CONF_IMPORT_HEATING, default=True): bool}
            ),
            description_placeholders={
                "count": str(len(self._selected_objects)),
                "objects": ", ".join(self._selected_objects.values()),
                "start": f"{HISTORY_START_YEAR}-{HISTORY_START_MONTH:02d}",
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> PastatoInfoOptionsFlow:
        return PastatoInfoOptionsFlow()


class PastatoInfoOptionsFlow(config_entries.OptionsFlow):
    """Options: toggle heating import."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_IMPORT_HEATING,
                        default=self.config_entry.options.get(
                            CONF_IMPORT_HEATING, True
                        ),
                    ): bool
                }
            ),
        )
