# CozyLife Battery Sensor for Home Assistant

First of all, a big thank you to [soulripper13](https://github.com/soulripper13), who created the original
[CozyLife Local](https://github.com/soulripper13/cozylife_local) integration. I adapted it for my own Home Assistant to
make a few improvements. I give no guarantee for the functionality and no promise of lifelong maintenance, as I do all of
this in my free time. Of course, I am happy about every contribution and PR.

## What this fork does – and why

CozyLife Local supports a whole range of CozyLife devices: lights, switches, plugs, fans, speakers and sensors. I only
own one battery-powered CozyLife Wi-Fi **temperature and humidity sensor**. Such a sensor sleeps and wakes up for a
few seconds about once an hour; Home Assistant has to catch it over local TCP while it is awake.

To be sure to catch it, the original integration asks the sleeping sensor four times per second, around the clock, and
sends a UDP discovery broadcast into the network every ten seconds (which only powered devices such as plugs need).
On my network that is a lot of traffic for one sensor. So this fork:

- **keeps only the sensor**: temperature, humidity, battery and its IP address – no lights, switches, plugs, fans,
  speakers, no 1 MB model catalogue;
- **learns when the sensor wakes up** and only asks shortly before the expected wake-up (a *wake window*, by default
  from 20 s before to 60 s after it). After a missed window the next one is wider; after three misses in a row it
  searches continuously again, as the original does. The learned rhythm survives restarts;
- **sends no UDP broadcasts at all** – give the sensor a fixed IP address in your router;
- keeps the domain `cozylife_local` and the entity unique IDs, so switching from the original keeps your entity IDs
  and history.

## Installation

1. Reserve a fixed IP address for the sensor in your router.
2. If you use the original CozyLife Local: remove it in HACS (keep the integration entries in Home Assistant).
3. HACS → three dots → *Custom repositories* → add `https://github.com/dktzde/cozylife_battery_sensor` as
   *Integration*, then download *CozyLife Battery Sensor* and restart Home Assistant.
4. New installation: *Settings → Devices & services → Add integration → CozyLife Battery Sensor*, enter the IP address.
   The sensor may sleep; it is added anyway and identifies itself at its next wake-up.

Coming from the original, the existing sensor entry keeps working; the empty "CozyLife Local" discovery entry of the
original is removed automatically, and leftover devices without entities can be deleted.

## Options

| Option | Default | Meaning |
|---|---|---|
| Probe only around the learned wake-up | on | Off = ask four times per second all the time, like the original. |
| Start probing before the expected wake-up | 20 s | Smaller = less traffic, but a higher risk of missing the sensor. |
| Stop probing after the expected wake-up | 60 s | How long to keep asking when the sensor is late. |
| Filter outliers | off | Optional median filter against false readings (from the original). |
| Debug logging | off | Logs every probe and the timing of each caught wake-up (no IP addresses or values). |

The diagnostics download of the entry shows the learned period, the jitter and the last probe windows.

## Supported sensors

Tested: CozyLife Wi-Fi temperature and humidity sensor, product ID `Z4tRml`. The other Wi-Fi temperature and humidity
sensors from the CozyLife catalogue (`s1AxFq`, `nrQdBz`, `JTFMlo`, `1iTgTJ`, `2EKExY`, `suUl7T`) can be selected but
are untested.

## Staying in sync with the original

A weekly workflow compares this fork with the original and opens an issue when sensor-related code changes there.
Useful fixes are ported by hand.

## License

MIT, see [LICENSE](LICENSE). The original integration is © soulripper13.
