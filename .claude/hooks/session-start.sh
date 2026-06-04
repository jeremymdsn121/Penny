#!/bin/bash
# SessionStart hook — install backend + frontend dependencies so tests,
# typechecks, and the dev servers work in a fresh remote session.
# Runs only in Claude Code on the web (remote); local machines keep their
# own .venv / node_modules.
set -euo pipefail

# Only run in the remote (web) environment. Locally this is a no-op so it
# never clobbers an existing local setup.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# --- Backend (FastAPI + Python) -------------------------------------------
cd "$ROOT/backend"
if [ ! -x ".venv/bin/python" ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r requirements.txt

# --- Frontend (React + Vite) ----------------------------------------------
cd "$ROOT/frontend"
npm install

echo "session-start: backend + frontend dependencies installed"

# --- Branch freshness report ----------------------------------------------
# Print where this session's branch stands relative to its remote and to
# master, so a stale checkout is obvious before any editing starts. This is
# best-effort: a git/network hiccup must never abort the session, so we drop
# the -e/pipefail guard for this block.
cd "$ROOT"
set +eo pipefail
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
git fetch -q origin "$BRANCH" master 2>/dev/null
BEHIND_ORIGIN="$(git rev-list --count "HEAD..origin/$BRANCH" 2>/dev/null)"
BEHIND_MASTER="$(git rev-list --count "HEAD..origin/master" 2>/dev/null)"
AHEAD_MASTER="$(git rev-list --count "origin/master..HEAD" 2>/dev/null)"
echo "----------------------------------------------------------------------"
echo "session-start: on branch '${BRANCH:-unknown}'"
if [ "${BEHIND_ORIGIN:-0}" -gt 0 ]; then
  echo "  WARNING: behind origin/$BRANCH by $BEHIND_ORIGIN commit(s)."
  echo "           run:  git pull origin $BRANCH"
else
  echo "  OK: in sync with origin/$BRANCH"
fi
if [ "$BRANCH" != "master" ]; then
  if [ "${BEHIND_MASTER:-0}" -gt 0 ]; then
    echo "  WARNING: master has $BEHIND_MASTER commit(s) not in this branch."
    echo "           to pull them in:  git merge origin/master"
  else
    echo "  OK: this branch already contains everything on master (ahead by ${AHEAD_MASTER:-0})"
  fi
fi
echo "----------------------------------------------------------------------"
