# STATUS

Read this first, and update it after every step, so the next session can continue without the chat history.

Last updated: 2026-11-22 (CodeRabbit settings and handover files)

## Current state

- Fork of `soulripper13/cozylife_local` at upstream 1.1.8 (commit `33affa1`), not changed yet.
- 2026-11-22: `.coderabbit.yaml`, `STATUS.md` and `CLAUDE.md` added.

## Next steps

1. Cut the integration down to the battery-powered temperature and humidity sensor (PID `Z4tRml`): remove lights, switches, fans,
   media players, selects, numbers, the model catalogue and UDP discovery/broadcast.
2. Build the wake window in (probe only shortly before the learned wake-up), make lead and tail time options.
3. Allow removing devices without entities.
4. Workflows: hassfest, HACS validation, tests, weekly upstream watch.
5. README (English, short, thanks to the original author), `hacs.json`, `manifest.json` 0.1.0, release `v0.1.0`.

## Known issues and backlog

- None yet.

## Decisions and conventions

- Domain stays `cozylife_local`, entity unique IDs stay `<device_id>_temperature|humidity|battery|ip_address`, so an existing
  installation keeps its entity IDs and history when it switches from the upstream to this fork.
- No PRs to the upstream (maintainer, 2026-11-20).

## Key files

- `custom_components/cozylife_local/` – the integration.
- `.coderabbit.yaml` – CodeRabbit review settings.
