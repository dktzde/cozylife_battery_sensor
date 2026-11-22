# STATUS

Read this first, and update it after every step, so the next session can continue without the chat history.

Last updated: 2026-11-22 (rebuild around the battery sensor, 0.1.0)

## Current state

- Fork of `soulripper13/cozylife_local` 1.1.8 (commit `33affa1`), rebuilt around the battery-powered temperature and
  humidity sensor (PR #2): TCP client, learned wake window, no UDP, reconfigure for the IP, removal of empty devices.
- Upstream watch baseline: `f733d29` (upstream 1.1.9-1, reviewed 2026-11-22: only the battery range check concerned
  the sensor and is covered).
- Not on the device yet.

## Next steps

1. Release `v0.1.0`, install it on the maintainer's Home Assistant (replacing the upstream HACS repository), check the
   entities keep their IDs and history.
2. Watch six hours of wake-ups and tighten the default lead so probing starts 5–10 s before the wake-up (0.1.1).

## Known issues and backlog

- Only `Z4tRml` is tested. The other catalogue sensors can be selected but may need different framing.
- Extra wake-ups (for example triggered by large changes, DPIDs 24/25) are only seen while searching continuously;
  if they disturb learning, three missed windows reset the schedule.

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
