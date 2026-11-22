# Changelog

## 0.1.1
<sub>2026-11-22</sub>

- The wake window now starts 7 s before the expected wake-up and ends 30 s after it by default (was 20 s / 60 s).
  On the device every wake-up was caught with probing starting about 7 s early and about 30 connection attempts per
  hour. After a missed or too tight window the next one still uses at least 20 s / 60 s. Entries with own values keep
  them.

## 0.1.0
<sub>2026-11-22</sub>

First release of this fork, built from CozyLife Local 1.1.8.

- Keep only the battery-powered Wi-Fi temperature and humidity sensor: temperature, humidity, battery and IP address
  entities. Lights, switches, plugs, fans, media players, selects, numbers and the model catalogue are removed.
- Wake window: learn the sensor's report period and probe only from 20 s before to 60 s after the expected wake-up
  (both adjustable in the options). A missed or too tight window makes the next one wider; three misses in a row
  fall back to continuous probing. The learned schedule is stored and survives restarts (it also reads the state of
  the earlier wake-window add-on).
- No UDP discovery and no broadcasts. The sensor is added by its fixed IP address; the IP can be changed with
  *Reconfigure*. The original's empty discovery entry is removed automatically.
- The device ID of a previously configured sensor can be entered (optional), so its entities, device and
  history come back after switching from the original (whose entries must be removed before it can be uninstalled).
- Devices without entities (for example left over from an identity change) can be deleted.
- Diagnostics show the learned period, its jitter and the recent probe windows.
- Workflows: hassfest, HACS validation, unit and Home Assistant tests, and a weekly check of the original for
  sensor-related changes.

---

**Versions 0.1.0 to 1.1.8 (December 2025 to November 2026) are by
[soulripper13/cozylife_local](https://github.com/soulripper13/cozylife_local)**; see its releases for their history.
This fork starts from 1.1.8 (2026-11-14) and counts its own versions from 0.1.0.
