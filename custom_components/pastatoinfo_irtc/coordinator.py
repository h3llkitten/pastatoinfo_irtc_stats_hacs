"""Sync engine: pulls portal data and imports it as long-term statistics."""
from __future__ import annotations

import logging
import random
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.const import DOMAIN as RECORDER_DOMAIN
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import PastatoInfoClient, PastatoInfoError
from .const import (
    ALL_RESOURCES,
    CONF_IMPORT_HEATING,
    CONF_OBJECTS,
    DOMAIN,
    HISTORY_START_MONTH,
    HISTORY_START_YEAR,
    PORTAL_TIMEZONE,
    SYNC_HOUR_UTC,
    SYNC_MINUTE_UTC,
    SYNC_RANDOM_WINDOW_SEC,
    Resource,
    total_unique_id,
)

_LOGGER = logging.getLogger(__name__)

try:  # HA 2025.4+: has_mean replaced by mean_type
    from homeassistant.components.recorder.models import (
        StatisticData,
        StatisticMeanType,
        StatisticMetaData,
    )

    _MEAN_KWARGS: dict[str, Any] = {"mean_type": StatisticMeanType.NONE}
except ImportError:  # pragma: no cover - older cores
    from homeassistant.components.recorder.models import (  # type: ignore[attr-defined]
        StatisticData,
        StatisticMetaData,
    )

    _MEAN_KWARGS = {"has_mean": False}

PORTAL_TZ = ZoneInfo(PORTAL_TIMEZONE)


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _next_month(month: date) -> date:
    if month.month == 12:
        return date(month.year + 1, 1, 1)
    return date(month.year, month.month + 1, 1)


def _previous_month(month: date) -> date:
    if month.month == 1:
        return date(month.year - 1, 12, 1)
    return date(month.year, month.month - 1, 1)


def _months_between(first: date, last: date) -> list[date]:
    """Month-start dates from first to last inclusive."""
    months = []
    month = _month_start(first)
    while month <= last:
        months.append(month)
        month = _next_month(month)
    return months


def _local_midnight_utc(day: date) -> datetime:
    """UTC datetime of local (portal) midnight for the given date."""
    return datetime(day.year, day.month, day.day, tzinfo=PORTAL_TZ).astimezone(
        dt_util.UTC
    )


def _stat_start_utc(day: date) -> datetime:
    """Timestamp for a statistics row covering the given local day/month.

    01:00 local, NOT midnight: HA computes `change` over a calendar period as
    sum(at end) - sum(at start), and a row stamped exactly at the period
    boundary becomes the baseline — i.e. falls out of the period. One hour in,
    the row stays inside its own day and month buckets everywhere.
    """
    return datetime(day.year, day.month, day.day, 1, tzinfo=PORTAL_TZ).astimezone(
        dt_util.UTC
    )


class PastatoInfoCoordinator(DataUpdateCoordinator[dict]):
    """Runs the sync on a custom daily schedule and holds sensor values."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: PastatoInfoClient,
        cookie_saver,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=None,  # scheduling is manual, see schedule_daily_sync
        )
        self.entry = entry
        self.client = client
        self._cookie_saver = cookie_saver
        self._unsub_timer = None

    @property
    def objects(self) -> dict[str, str]:
        return self.entry.data[CONF_OBJECTS]

    @property
    def enabled_resources(self) -> list[Resource]:
        import_heating = self.entry.options.get(CONF_IMPORT_HEATING, True)
        return [
            resource
            for resource in ALL_RESOURCES
            if import_heating or not resource.is_heating
        ]

    # --- scheduling -----------------------------------------------------

    def schedule_daily_sync(self) -> None:
        """(Re)schedule the next run at 02:11 UTC + random 0-60 min."""
        self.cancel_daily_sync()
        now = dt_util.utcnow()
        base = now.replace(
            hour=SYNC_HOUR_UTC, minute=SYNC_MINUTE_UTC, second=0, microsecond=0
        )
        if base <= now:
            base += timedelta(days=1)
        target = base + timedelta(seconds=random.randint(0, SYNC_RANDOM_WINDOW_SEC))
        _LOGGER.info("Next pastatoinfo sync scheduled at %s", target)
        self._unsub_timer = async_track_point_in_utc_time(
            self.hass, self._async_scheduled_sync, target
        )

    def cancel_daily_sync(self) -> None:
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None

    async def _async_scheduled_sync(self, _now: datetime) -> None:
        try:
            await self.async_refresh()
        finally:
            self.schedule_daily_sync()

    # --- sync -----------------------------------------------------------

    async def _async_update_data(self) -> dict:
        """Full sync: statistics backfill + sensor values for every object/resource."""
        sensor_data: dict[tuple[str, str], dict] = {}
        # Cache of YearlyUsage responses: (object_id, tipas, year) -> {month: value}
        yearly_cache: dict[tuple[str, str, int], dict[int, float]] = {}
        try:
            for object_id, object_name in self.objects.items():
                for resource in self.enabled_resources:
                    sensor_data[(object_id, resource.key)] = (
                        await self._sync_resource(
                            object_id, object_name, resource, yearly_cache
                        )
                    )
        except PastatoInfoError as err:
            raise UpdateFailed(f"Portal sync failed: {err}") from err
        await self._cookie_saver()
        return sensor_data

    async def _sync_resource(
        self,
        object_id: str,
        object_name: str,
        resource: Resource,
        yearly_cache: dict,
    ) -> dict:
        """Backfill statistics for one object+resource; return sensor values."""
        entity_registry = er.async_get(self.hass)
        unique_id = total_unique_id(self.entry.entry_id, object_id, resource.key)
        statistic_id = entity_registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        if statistic_id is None:
            # The "total" sensor entity (which the statistic is imported onto)
            # is set up by the sensor platform before the first sync ever
            # runs, so this should not happen — but skip cleanly if it does,
            # rather than import statistics under a made-up id.
            _LOGGER.warning(
                "Total sensor for %s/%s not registered yet, skipping this cycle",
                object_id,
                resource.key,
            )
            return {
                "month_total": None,
                "month": None,
                "last_day_value": None,
                "last_day_date": None,
                "prev_month_total": None,
                "prev_month": None,
                "total": None,
            }

        today = datetime.now(PORTAL_TZ).date()
        current_month = _month_start(today)

        base_sum, first_month, daily_months = await self._resume_point(
            statistic_id, current_month
        )

        rows: list[StatisticData] = []
        running_sum = base_sum
        current_month_daily: list[float] = []

        for month in _months_between(first_month, current_month):
            if month in daily_months:
                daily = await self._fetch_daily(object_id, resource, month)
                # Never emit rows for today/future: portal lags 1-2 days and
                # today's value would be incomplete anyway.
                if month == current_month:
                    daily = daily[: max(0, (today - month).days)]
                else:
                    daily = daily[: ((_next_month(month) - month).days)]
                for index, value in enumerate(daily):
                    day = month + timedelta(days=index)
                    running_sum += value
                    rows.append(
                        StatisticData(
                            start=_stat_start_utc(day),
                            state=value,
                            sum=running_sum,
                        )
                    )
                if month == current_month:
                    current_month_daily = daily
            else:
                cache_key = (object_id, resource.tipas, month.year)
                if cache_key not in yearly_cache:
                    yearly_cache[cache_key] = await self.client.async_get_yearly_usage(
                        object_id, resource.tipas, month.year
                    )
                value = yearly_cache[cache_key].get(month.month, 0.0)
                running_sum += value
                rows.append(
                    StatisticData(
                        start=_stat_start_utc(month),
                        state=value,
                        sum=running_sum,
                    )
                )

        if rows:
            metadata = StatisticMetaData(
                source=RECORDER_DOMAIN,
                statistic_id=statistic_id,
                name=f"{resource.name} {object_name}",
                unit_of_measurement=resource.unit,
                unit_class=resource.unit_class,
                has_sum=True,
                **_MEAN_KWARGS,
            )
            async_import_statistics(self.hass, metadata, rows)
            _LOGGER.debug(
                "%s: imported %d rows (from %s)", statistic_id, len(rows), first_month
            )

        month_total = sum(current_month_daily)
        last_day_value = None
        last_day_date = None
        if current_month_daily:
            last_day_value = current_month_daily[-1]
            last_day_date = current_month + timedelta(days=len(current_month_daily) - 1)

        # Previous-month total for the sensor, from the (cached) yearly data.
        prev_month = _previous_month(current_month)
        cache_key = (object_id, resource.tipas, prev_month.year)
        if cache_key not in yearly_cache:
            yearly_cache[cache_key] = await self.client.async_get_yearly_usage(
                object_id, resource.tipas, prev_month.year
            )
        prev_month_total = yearly_cache[cache_key].get(prev_month.month, 0.0)

        return {
            "month_total": round(month_total, 3),
            "month": current_month.strftime("%Y-%m"),
            "last_day_value": last_day_value,
            "last_day_date": last_day_date,
            "prev_month_total": round(prev_month_total, 3),
            "prev_month": prev_month.strftime("%Y-%m"),
            "total": round(running_sum, 3),
        }

    async def _resume_point(
        self, statistic_id: str, current_month: date
    ) -> tuple[float, date, set[date]]:
        """Determine where to resume the import.

        Returns (base_sum, first month to import, set of months to import daily).
        Idempotency: months already covered are re-imported only when they need
        daily refinement; rows with matching start timestamps are overwritten.
        """
        recorder = get_instance(self.hass)
        last = await recorder.async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, {"state", "sum"}
        )
        if not last.get(statistic_id):
            # Nothing imported yet: full history from the fixed start.
            return 0.0, date(HISTORY_START_YEAR, HISTORY_START_MONTH, 1), {current_month}

        last_row = last[statistic_id][0]
        last_start = last_row["start"]
        if isinstance(last_start, (int, float)):
            last_start = dt_util.utc_from_timestamp(last_start)
        last_month = _month_start(last_start.astimezone(PORTAL_TZ).date())

        # Base sum = cumulative sum just before last_month, derived from the
        # first stored row of that month (sum - state = sum before the row).
        month_rows = await recorder.async_add_executor_job(
            statistics_during_period,
            self.hass,
            _local_midnight_utc(last_month),
            _local_midnight_utc(_next_month(last_month)),
            {statistic_id},
            "hour",
            None,
            {"state", "sum"},
        )
        rows = month_rows.get(statistic_id) or []
        if rows:
            base_sum = (rows[0].get("sum") or 0.0) - (rows[0].get("state") or 0.0)
        else:  # defensive: shouldn't happen, last row is inside last_month
            base_sum = last_row.get("sum") or 0.0

        # The month containing the last row is re-imported daily (finishes a
        # partial month / upgrades a monthly row); current month always daily.
        return base_sum, last_month, {last_month, current_month}

    async def _fetch_daily(
        self, object_id: str, resource: Resource, month: date
    ) -> list[float]:
        """Per-day consumption for one month from the portal."""
        period = month.strftime("%Y-%m")
        if resource.is_heating:
            heating = await self.client.async_get_heating_usage(object_id, period)
            return heating.daily
        cumulative = await self.client.async_get_growing_usage(
            object_id, resource.tipas, period
        )
        daily = []
        previous = 0.0
        for value in cumulative:
            daily.append(round(value - previous, 6))
            previous = value
        return daily
