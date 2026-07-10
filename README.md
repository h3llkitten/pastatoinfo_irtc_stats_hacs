# Pastatoinfo IRTC → Home Assistant

HACS custom component that pulls building utility data (heating, hot/cold water) from [pastatoinfo.irtc.lt](https://pastatoinfo.irtc.lt) — a Lithuanian building-management portal (IRTC) — into Home Assistant.

**Status: scaffold only, not functional yet.** No official public API exists for this portal; the plan is to reverse-engineer the site's internal AJAX endpoints (session-cookie auth). Full research (auth flow, endpoints, JSON shapes, known quirks) is in `CLAUDE.md`.

## Install (once functional)
Via HACS as a custom repository, or copy `custom_components/pastatoinfo_irtc` into your HA `custom_components` folder.
