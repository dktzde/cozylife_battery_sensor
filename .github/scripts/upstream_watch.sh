#!/usr/bin/env bash
# Open (or update) an issue when the upstream integration changes code that
# matters for the battery sensor. Run by .github/workflows/upstream-watch.yml.
#
# Baseline: the upstream commit recorded in the newest watch issue (its "base"
# while it is open, its "head" once it is closed = reviewed), otherwise
# .github/upstream-baseline. Close the issue after porting or dismissing the
# changes; the next run then starts from that issue's head.
#
# Environment: GH_TOKEN, GH_REPO (this repository, so gh never picks the
# upstream remote), UPSTREAM (owner/repo), optional DRY_RUN=1.
set -euo pipefail

UPSTREAM="${UPSTREAM:-soulripper13/cozylife_local}"
BRANCH="${UPSTREAM_BRANCH:-main}"
LABEL="upstream-watch"
COMPONENT="custom_components/cozylife_local"
# Files whose every change matters for the sensor.
ALWAYS=(sensor.py measurement_filter.py)
# Shared files: only changed lines that mention the sensor count.
SHARED=(cozylife_api.py coordinator.py __init__.py config_flow.py const.py debug.py diagnostics.py)
KEYWORDS='sensor|z4trml|sleep|wake|battery|humidity|temperature|measurement|environment'

if ! git remote get-url upstream >/dev/null 2>&1; then
  git remote add upstream "https://github.com/${UPSTREAM}.git"
fi
git fetch --quiet upstream "$BRANCH"
head=$(git rev-parse "upstream/${BRANCH}")

marker() { sed -n "s/^<!-- upstream-watch $1=\([0-9a-f]\{40\}\) -->\$/\1/p" <<<"$2" | head -n 1; }

number="" state="" body=""
if [ "${DRY_RUN:-0}" != 1 ] || [ -n "${GH_TOKEN:-}" ]; then
  issue=$(gh issue list --label "$LABEL" --state all --limit 1 --json number,state,body)
  number=$(jq -r '.[0].number // empty' <<<"$issue")
  state=$(jq -r '.[0].state // empty' <<<"$issue")
  body=$(jq -r '.[0].body // empty' <<<"$issue")
fi

base=""
if [ -n "$number" ] && [ "$state" = "OPEN" ]; then
  base=$(marker base "$body")
  if [ "$(marker head "$body")" = "$head" ]; then
    echo "Issue #$number already covers upstream ${head:0:7}."
    exit 0
  fi
elif [ -n "$number" ]; then
  base=$(marker head "$body")
fi
if [ -z "$base" ] || ! git cat-file -e "${base}^{commit}" 2>/dev/null; then
  base=$(tr -d '[:space:]' < .github/upstream-baseline)
fi

if [ "$base" = "$head" ]; then
  echo "Upstream unchanged since ${base:0:7}."
  exit 0
fi

relevant=()
for file in "${ALWAYS[@]}"; do
  if ! git diff --quiet "$base" "$head" -- "$COMPONENT/$file"; then
    relevant+=("$COMPONENT/$file")
  fi
done
for file in "${SHARED[@]}"; do
  # Count instead of grep -q: an early exit would break the pipe under pipefail.
  hits=$(git diff "$base" "$head" -- "$COMPONENT/$file" \
    | { grep -E '^[+-]' || true; } | { grep -vE '^(\+\+\+|---) ' || true; } \
    | { grep -ciE "$KEYWORDS" || true; })
  if [ "${hits:-0}" -gt 0 ]; then
    relevant+=("$COMPONENT/$file")
  fi
done

if [ "${#relevant[@]}" -eq 0 ]; then
  echo "Upstream changed since ${base:0:7}, but nothing that concerns the sensor."
  exit 0
fi

version=$(git show "${head}:${COMPONENT}/manifest.json" | jq -r '.version // "?"')
{
  echo "<!-- upstream-watch base=${base} -->"
  echo "<!-- upstream-watch head=${head} -->"
  echo "The upstream integration [${UPSTREAM}](https://github.com/${UPSTREAM}) (now version ${version}) changed files that matter for the battery sensor."
  echo
  echo "Compare: https://github.com/${UPSTREAM}/compare/${base:0:12}...${head:0:12}"
  echo
  echo "### Files"
  for file in "${relevant[@]}"; do
    echo "- \`${file}\` ($(git diff --numstat "$base" "$head" -- "$file" | awk '{print "+" $1 " / -" $2}'))"
  done
  echo
  echo "### Commits"
  git log --no-merges --format='- %h %s' "${base}..${head}" -- "${relevant[@]}" | sed -n '1,50p'
  echo
  echo "Port what is useful in a normal PR, then close this issue. The next check starts from \`${head:0:7}\`."
} > upstream-watch.md

title="Upstream changed sensor code (${base:0:7}..${head:0:7})"
if [ "${DRY_RUN:-0}" = 1 ]; then
  echo "DRY RUN – would write issue: $title"
  cat upstream-watch.md
  exit 0
fi

gh label create "$LABEL" --color FBCA04 --description "Upstream changes to review" >/dev/null 2>&1 || true
if [ -n "$number" ] && [ "$state" = "OPEN" ]; then
  # The maintainer may have closed it meanwhile; never write a new head into a closed issue.
  state=$(gh issue view "$number" --json state --jq .state)
fi
if [ -n "$number" ] && [ "$state" = "OPEN" ]; then
  gh issue edit "$number" --title "$title" --body-file upstream-watch.md
  gh issue comment "$number" --body "More upstream commits, now up to ${head:0:7}. The description above is updated."
else
  gh issue create --title "$title" --label "$LABEL" --body-file upstream-watch.md
fi
