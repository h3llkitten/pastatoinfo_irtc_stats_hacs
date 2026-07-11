"""Async client for the pastatoinfo.irtc.lt internal web API.

The portal has no official read API; this client replays the AJAX calls the
site's own frontend makes. It is intentionally independent from Home Assistant
so it can be exercised standalone.
"""
from __future__ import annotations

import html as html_mod
import logging
import re
from dataclasses import dataclass

import aiohttp

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://pastatoinfo.irtc.lt"
LOGIN_PATH = "/Account/Login"

_TOKEN_RE = re.compile(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"')
_OBJECT_SELECT_RE = re.compile(r'<select[^>]*id="Butas"[\s\S]*?</select>')
_OPTION_RE = re.compile(r'<option value="(\d+)"[^>]*>\s*([^<]+?)\s*</option>')
_DATABASE_RE = re.compile(r'class="SelectDatabase" data-culture="([^"]+)"')


class PastatoInfoError(Exception):
    """Generic portal error."""


class PastatoInfoAuthError(PastatoInfoError):
    """Login failed (bad credentials) or session could not be established."""


@dataclass
class HeatingMonth:
    """Heating data for one month: portal-reported total and per-day values."""

    total: float
    daily: list[float]


def _to_float(value) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


class PastatoInfoClient:
    """Cookie-session client for pastatoinfo.irtc.lt."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        database: str | None = None,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._database = database
        self._logged_in = False

    async def async_login(self) -> None:
        """Log in and (if configured) select the target database."""
        resp = await self._session.get(
            f"{BASE_URL}{LOGIN_PATH}", params={"ReturnUrl": "/"}
        )
        page = await resp.text()
        match = _TOKEN_RE.search(page)
        if not match:
            raise PastatoInfoError("CSRF token not found on login page")
        # RememberMe is sent twice (checkbox + hidden field), like the browser does.
        form = [
            ("__RequestVerificationToken", match.group(1)),
            ("UserName", self._username),
            ("Password", self._password),
            ("RememberMe", "true"),
            ("RememberMe", "false"),
        ]
        resp = await self._session.post(
            f"{BASE_URL}{LOGIN_PATH}",
            params={"ReturnUrl": "/"},
            data=form,
            headers={"Referer": f"{BASE_URL}{LOGIN_PATH}"},
        )
        page = await resp.text()
        if "/Account/Login" in str(resp.url) and 'name="Password"' in page:
            raise PastatoInfoAuthError("Login rejected — check username/password")
        self._logged_in = True
        _LOGGER.debug("Logged in to pastatoinfo as %s", self._username)
        if self._database:
            await self.async_set_database(self._database)

    async def async_set_database(self, database: str) -> None:
        """Switch the server-side session to the given database."""
        resp = await self._session.post(
            f"{BASE_URL}/Home/SetDatabase",
            params={"database": database, "redirectUrl": "/"},
        )
        if resp.status >= 400:
            raise PastatoInfoError(f"SetDatabase({database}) failed: {resp.status}")
        self._database = database

    async def async_get_databases(self) -> list[str]:
        """List databases available to this account (parsed from page header)."""
        page = await self._get_page("/")
        return list(dict.fromkeys(_DATABASE_RE.findall(page)))

    async def async_get_objects(self) -> dict[str, str]:
        """Map objectId -> address for all objects in the active database."""
        page = await self._get_page("/Energetics")
        select = _OBJECT_SELECT_RE.search(page)
        if not select:
            raise PastatoInfoError("Object list (select#Butas) not found")
        return {
            object_id: html_mod.unescape(name)
            for object_id, name in _OPTION_RE.findall(select.group(0))
        }

    async def async_get_yearly_usage(
        self, object_id: str, tipas: str, year: int
    ) -> dict[int, float]:
        """Monthly totals for one year, keyed by month number (1-12)."""
        data = await self._get_json(
            "/Energetics/YearlyUsage",
            {"objectId": object_id, "tipas": tipas, "periodas": str(year)},
        )
        return {
            int(key.split("-")[1]): _to_float(value) for key, value in data.items()
        }

    async def async_get_growing_usage(
        self, object_id: str, tipas: str, period: str
    ) -> list[float]:
        """Cumulative-within-month daily readings for YYYY-MM (water meters)."""
        data = await self._get_json(
            "/Energetics/GrowingUsage",
            {
                "objectId": object_id,
                "butasId": object_id,
                "tipas": tipas,
                "periodas": period,
            },
        )
        return [_to_float(value) for value in data.get("dataset", [])]

    async def async_get_heating_usage(
        self, object_id: str, period: str
    ) -> HeatingMonth:
        """Per-day heating consumption for YYYY-MM, summed across meters."""
        data = await self._get_json(
            "/Energetics/HeatingUsage",
            {"objectId": object_id, "period": period},
        )
        daily: list[float] = []
        for meter in data.get("Data", []):
            values = [_to_float(value) for value in meter.get("Values", [])]
            if len(values) > len(daily):
                daily.extend([0.0] * (len(values) - len(daily)))
            for index, value in enumerate(values):
                daily[index] += value
        return HeatingMonth(total=_to_float(data.get("Sum")), daily=daily)

    async def _get_page(self, path: str, _retry: bool = True) -> str:
        """GET an HTML page, re-logging-in if the session expired."""
        if not self._logged_in:
            await self.async_login()
        resp = await self._session.get(f"{BASE_URL}{path}")
        if "/Account/Login" in str(resp.url):
            if _retry:
                self._logged_in = False
                return await self._get_page(path, _retry=False)
            raise PastatoInfoAuthError("Session expired and re-login failed")
        if resp.status >= 400:
            raise PastatoInfoError(f"GET {path} failed: {resp.status}")
        return await resp.text()

    async def _get_json(self, path: str, params: dict, _retry: bool = True):
        """GET a JSON endpoint the way the frontend does (XHR headers)."""
        if not self._logged_in:
            await self.async_login()
        resp = await self._session.get(
            f"{BASE_URL}{path}",
            params=params,
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{BASE_URL}/Energetics",
            },
        )
        # An expired session redirects XHR calls to the login page (HTML).
        if "/Account/Login" in str(resp.url) or "html" in (resp.content_type or ""):
            if _retry:
                self._logged_in = False
                return await self._get_json(path, params, _retry=False)
            raise PastatoInfoAuthError("Session expired and re-login failed")
        if resp.status >= 400:
            raise PastatoInfoError(f"GET {path} failed: {resp.status}")
        return await resp.json(content_type=None)
