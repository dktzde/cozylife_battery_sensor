# STATUS

Read this first, and update it after every step, so the next session can continue without the chat history.

Last updated: 2026-11-22 (device test, default wake window 7 s / 30 s, 0.1.1)

## Current state

- Fork of `soulripper13/cozylife_local` 1.1.8 (commit `33affa1`), rebuilt around the battery-powered temperature and
  humidity sensor (PR #2): TCP client, learned wake window, no UDP, reconfigure for the IP, removal of empty devices.
- Upstream watch baseline: `f733d29` (upstream 1.1.9-1, reviewed 2026-11-22: only the battery range check concerned
  the sensor and is covered).
- **0.1.0 on the device since 2026-11-22 03:48** (installed through the Home Assistant Marketplace after removing the
  upstream's entries; the sensor was re-added with its old device ID, entity IDs, registry IDs and history kept).
  **Checked 2026-11-22 03:49–10:55:** all 8 wake-ups caught (2 while learning, 2 windows with 20 s lead, 4 with 7 s lead);
  with 7 s lead probing started 7.0 / 7.7 / 7.0 / 7.4 s before the sensor answered; about 30 connection attempts per hour
  (upstream: about 14,000); learned period 3523.9 s; values arrive hourly; no warnings or errors; the learned schedule
  survived an options reload.
- 0.1.1: defaults 7 s lead / 30 s tail. Not checked yet on the device as a release (the options already used these values).

## Next steps

1. Install 0.1.1 on the device and check that windows keep hitting after the restart.
2. Watch for misses over a few days (Wi-Fi outages of the Home Assistant host are expected to cause single misses).

## Known issues and backlog

- Only `Z4tRml` is tested. The other catalogue sensors can be selected but may need different framing.
- Extra wake-ups (for example triggered by large changes, DPIDs 24/25) are only seen while searching continuously;
  if they disturb learning, three missed windows reset the schedule.
- The learned schedule is stored per config entry: re-adding the sensor starts learning again (up to two report periods of
  continuous probing).
- Marketplace (Home Assistant 2026.11) only uninstalls the upstream after its entries are removed; the README explains the
  switch with the optional device ID.

## Decisions and conventions

- Domain stays `cozylife_local`, entity unique IDs stay `<device_id>_temperature|humidity|battery|ip_address`, so an existing
  installation keeps its entity IDs and history when it switches from the upstream to this fork.
- No PRs to the upstream (maintainer, 2026-11-20). The upstream watch opens an issue; port by hand.
- The wake schedule is stored as `.storage/cozylife_local_wake_<entry_id>` (same key and fields as the maintainer's
  earlier `cozylife_aufwachfenster` add-on, so the learned period carries over).
- Times in the schedule are wall-clock seconds; the wake-up time is the moment the TCP connection succeeded.
- A connection that succeeds on the first attempt of a window means the sensor was already awake: that wake-up is
  not used for learning and the next window is widened.

## Key files

- `custom_components/cozylife_local/cozylife_api.py` – TCP client.
- `custom_components/cozylife_local/wake_schedule.py` – learned period and windows (no Home Assistant imports).
- `custom_components/cozylife_local/probe.py` – probe loop (no Home Assistant imports).
- `custom_components/cozylife_local/coordinator.py` – frames to entities, storage, identity check.
- `tests/` – unit tests without Home Assistant; `tests_ha/` – tests with pytest-homeassistant-custom-component.
- `.github/scripts/upstream_watch.sh`, `.github/upstream-baseline` – upstream watch.
- `.coderabbit.yaml` – CodeRabbit review settings.
