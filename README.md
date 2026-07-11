# Pastatoinfo IRTC → Home Assistant

*README updated: 2026-07-11*

A Home Assistant custom integration (HACS-installable) that logs into [pastatoinfo.irtc.lt](https://pastatoinfo.irtc.lt) — the building-information portal operated by IRTC (Informatikos ir ryšių technologijų centras, Lithuania) — and imports your apartment's utility consumption into Home Assistant:

- **Heating** (kWh)
- **Hot water** (m³)
- **Cold water** (m³)

The portal has **no official public API**. This integration replays the AJAX calls the portal's own web frontend makes (session-cookie auth). It can break without notice on any portal update.

## ⚠️ Status / disclaimers

- **Experimental. Not yet reviewed or tested by a human end-to-end** beyond one real account — treat it accordingly.
- **Not tested with more than one object (apartment) per account.** Multi-object support is designed in (the config flow lets you pick several), but has never run against a real multi-object account.
- Tested only with accounts whose data lives in the `NIS_VILNIUS` portal database (auto-selected; falls back to the account's only database).
- Portal data is **daily, with a 1–2 day lag**. This is not a real-time meter.

## Installation (HACS)

1. HACS → three-dot menu → **Custom repositories**.
2. Repository: `h3llkitten/pastatoinfo_irtc_stats_hacs`, type: **Integration** → Add.
3. Find **Pastatoinfo IRTC** in HACS, **Download** it.
4. Restart Home Assistant.
5. Settings → Devices & services → **Add integration** → search **Pastatoinfo IRTC**.

## Configuration

The config flow asks for:

1. **Username / password** — your pastatoinfo.irtc.lt credentials. They are stored in the config entry and used to log in; the session cookie is persisted across restarts, with automatic re-login when it expires.
2. **Objects** — the apartments/buildings found on your account; pick one, several, or all.
3. **Confirmation** — historical consumption **starting from 2025-01** is imported on first sync. Past months come as monthly totals, the current month and 2 preceding ones as daily values. Heating has no manual toggle: it syncs automatically during the legal Oct 1 – Apr 30 heating season (Lithuanian Heat Supply Law, buildings with automated heat-distribution points) and is skipped the rest of the year — the initial import always backfills it in full regardless of season, and any gap heals automatically once the season starts again.

## What you get

### Long-term statistics (the main output)

External statistics, usable in the Energy dashboard and `statistics-graph` cards:

| Statistic id | Unit |
|---|---|
| `pastatoinfo_irtc:heating_<objectId>` | kWh |
| `pastatoinfo_irtc:hot_water_<objectId>` | m³ |
| `pastatoinfo_irtc:cold_water_<objectId>` | m³ |

Monthly totals from 2025-01; daily resolution for the current month (and for any partially-synced month healed later). Rows are timestamped at 01:00 Europe/Vilnius.

### Sensors (per object, per resource)

- `… last day` — consumption on the most recent day the portal has data for (the exact date is in the `date` attribute; remember the 1–2 day lag).
- `… this month` — month-to-date total.
- `… last month` — previous calendar month total.

### Controls

- **Resync now** button — runs the sync/backfill immediately (idempotent; safe to press anytime).
- `pastatoinfo_irtc.sync` service — the same, callable from automations.

### Sync schedule

Once a day at a random moment between 02:11 and 03:11 UTC (randomized to avoid hammering the portal at a fixed second), plus one sync on Home Assistant startup. The sync is a single unified backfill: it looks at the last imported statistics row and fills everything from there, so downtime, the heating season starting again, or a freshly wiped database all heal automatically.

## Example dashboard cards

The built-in `statistics-graph` card works out of the box:

```yaml
type: statistics-graph
title: Cold water, m³
entities:
  - pastatoinfo_irtc:cold_water_<objectId>
stat_types: [change]
chart_type: bar
period: day
days_to_show: 31
```

```yaml
type: statistics-graph
title: Heating, kWh
entities:
  - pastatoinfo_irtc:heating_<objectId>
stat_types: [change]
chart_type: bar
period: month
days_to_show: 600
```

Its water values are rounded to 2 decimals with no way to configure that (a hard-coded HA frontend default for external, entity-less statistics). For full-precision graphs, use **[`plotly-graph-card`](https://github.com/dbuezas/lovelace-plotly-graph-card)** (HACS) instead — it queries `recorder/statistics_during_period` directly by statistic id, with no live-entity requirement (unlike `apexcharts-card`, which hard-requires one and doesn't support this kind of externally-sourced statistic — see [apexcharts-card#707](https://github.com/RomRider/apexcharts-card/issues/707), closed as not planned):

```yaml
type: custom:plotly-graph
entities:
  - entity: pastatoinfo_irtc:cold_water_<objectId>
    statistic: sum
    period: day
    filters:
      - delta # turns the cumulative "sum" column into a per-day value
    texttemplate: "%{y:.3f}"
    hovertemplate: "%{y:.3f} m³<extra></extra>"
layout:
  yaxis:
    tickformat: ".3f"
hours_to_show: 31d
```

For "this month / last month" tiles use the integration's sensors with regular `tile` cards. (Avoid the `statistic` card with this integration's data: with sparse rows — one per day/month — its period-change math drops the first row of the period.)

## Removal

Deleting the integration entry removes the sensors and the persisted session cookie. Imported statistics stay in the recorder database; delete them via Developer tools → Statistics if you want them gone.
