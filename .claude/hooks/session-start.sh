#!/bin/bash
# SessionStart hook.
#   Remote (web) — install backend + frontend deps so tests, typechecks, and the
#                  dev servers work in a fresh clone.
#   Local        — keep the checkout current: auto fast-forward master when it's
#                  clean and behind, and always report branch freshness vs origin
#                  and master so a stale tree is obvious before any editing.
set -euo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$ROOT"

# --- Remote: install dependencies -----------------------------------------
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
  cd "$ROOT/backend"
  if [ ! -x ".venv/bin/python" ]; then
    python3 -m venv .venv
  fi
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt
  cd "$ROOT/frontend"
  # Use `npm ci` (not `npm install`): it installs strictly from the lockfile and
  # never rewrites it, so a differing local npm version can't re-format
  # package-lock.json and leave the tree dirty every session. Falls back to
  # `npm install` only if the lockfile is genuinely out of sync.
  npm ci || npm install
  echo "session-start: backend + frontend dependencies installed"
  exit 0
fi

# --- Local: freshness + auto fast-forward ---------------------------------
# Best-effort only: a git/network hiccup must never abort the session, so drop
# the -e/pipefail guard for this block.
set +eo pipefail
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
git fetch -q origin "$BRANCH" master 2>/dev/null
BEHIND_ORIGIN="$(git rev-list --count "HEAD..origin/$BRANCH" 2>/dev/null)"
echo "----------------------------------------------------------------------"
echo "session-start: on branch '${BRANCH:-unknown}'"

if [ "$BRANCH" = "master" ] && [ "${BEHIND_ORIGIN:-0}" -gt 0 ]; then
  # On master we can safely advance when nothing is uncommitted; never clobber.
  if [ -z "$(git status --porcelain)" ]; then
    git pull --ff-only origin master >/dev/null \
      && echo "  fast-forwarded master ($BEHIND_ORIGIN commit(s) from origin)"
  else
    echo "  WARNING: behind origin/master by $BEHIND_ORIGIN — tree dirty, pull manually."
  fi
elif [ "${BEHIND_ORIGIN:-0}" -gt 0 ]; then
  echo "  WARNING: behind origin/$BRANCH by $BEHIND_ORIGIN commit(s). run: git pull origin $BRANCH"
else
  echo "  OK: in sync with origin/$BRANCH"
fi

# On a feature branch, also report drift from master.
if [ "$BRANCH" != "master" ]; then
  BEHIND_MASTER="$(git rev-list --count "HEAD..origin/master" 2>/dev/null)"
  AHEAD_MASTER="$(git rev-list --count "origin/master..HEAD" 2>/dev/null)"
  if [ "${BEHIND_MASTER:-0}" -gt 0 ]; then
    echo "  WARNING: master has $BEHIND_MASTER commit(s) not in this branch."
    echo "           to pull them in:  git merge origin/master"
  else
    echo "  OK: this branch already contains everything on master (ahead by ${AHEAD_MASTER:-0})"
  fi
fi
echo "----------------------------------------------------------------------"
