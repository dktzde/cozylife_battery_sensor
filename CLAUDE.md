# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Read `STATUS.md` first** (current state, next steps, known issues).

## Git, commits and pull requests

These rules apply to every session, also to Claude Code on the web.

- **Author:** commits and PRs must look as if the maintainer made them alone. Before the first commit run `git config user.name "dktzde"` and `git config user.email "dktzde@users.noreply.github.com"`. No `Co-Authored-By`, no "Generated with Claude" in commits, PR texts, issues, changelog or README.
- **Branches:** no `claude/` prefix where the environment allows it (Claude Code on the web may force `claude/…`; that is accepted).
- **One topic = one branch = one PR.** One commit per sub-topic, test after each commit. Plan the commit split before the first push. Never force-push a pushed branch; fix mistakes with `git revert`.
- **This is a cut-down fork of `soulripper13/cozylife_local`.** It keeps only the battery-powered temperature and humidity sensor and is not meant to go back upstream: branches start from our `main`, and no PRs are opened at the upstream. Open PRs against this repository with `gh pr create --repo dktzde/cozylife_battery_sensor --base main`, otherwise they land at the upstream.
- **Upstream watch:** the workflow `upstream-watch.yml` opens an issue when the upstream changes files that matter for the sensor. Port such changes by hand in a normal PR; never merge the upstream branch.
- **CodeRabbit:** this repository has fewer than 10 stars, so CodeRabbit does not review PRs automatically. Right after opening a PR that changes code (Python under `custom_components/`, translations, `manifest.json`, workflows, tests), comment `@coderabbitai review` (`gh pr comment <number> --repo dktzde/cozylife_battery_sensor --body "@coderabbitai review"`). Skip documentation-only PRs (`docs:`), drafts and pure version bumps without code changes. Before the merge, read the bot's comments and either address them or explain in the PR why not. Settings are in `.coderabbit.yaml`.
- **Merge** only when the maintainer explicitly asks, always with a merge commit (no squash), so every commit can be reverted on its own.
- **Versions:** bump only for user-facing changes and only on `main`; documentation-only changes get no new version. Change the version in `manifest.json` and `CHANGELOG.md` at the same time, then tag `vX.Y.Z` and publish a GitHub release (HACS installs from releases).
- **Changelog:** every version gets its date as `<sub>YYYY-MM-DD</sub>` under its heading. Versions by earlier authors are separated by a `---` line and a bold sentence naming them.
- **Language:** everything in the repository is English (code, comments, docs, commits, PR and issue texts). Exception: the UI translations under `custom_components/cozylife_local/translations/` (for example `de.json`) are localized on purpose; keep their keys equal to `strings.json`. Commit messages in the imperative, e.g. `feat(scope): …`, `fix: …`, `docs: …`, `chore: …`, `ci: …`.
- **No secrets or private data** (tokens, passwords, IP addresses, device IDs, entity IDs) in the repository; use placeholders.
- **README:** a credit line for Claude Code only after asking the maintainer.
- **Handover:** keep `STATUS.md` with the current state, next steps, known issues, decisions and key files. Record what runs on the device with date and time, what was checked and what not. Update it after every step.

## Tests

`python -m pytest tests` runs without Home Assistant (its modules are stubbed in `tests/conftest.py`). The CI workflow `tests.yml` runs the same command.
