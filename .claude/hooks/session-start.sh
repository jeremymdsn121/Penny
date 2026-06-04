#!/bin/bash
# SessionStart hook.
#   Local sessions  — keep the clone current: auto fast-forward master so work
#                     never starts on a stale tree behind origin/master.
#   Remote (web)    — install backend + frontend dependencies so tests,
#                     typechecks, and the dev servers work in a fresh clone.
set -euo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$ROOT"

# --- Local: sync with origin/master ---------------------------------------
# Remote clones are always fresh; only local clones drift when remote/cloud
# sessions push. Auto-advance ONLY when the tree is clean and on master, so a
# feature branch or uncommitted work is never clobbered — otherwise just warn.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  git fetch --quiet origin || true
  behind=$(git rev-list --count HEAD..origin/master 2>/dev/null || echo 0)
  if [ "$behind" -gt 0 ]; then
    if [ -z "$(git status --porcelain)" ] && [ "$(git branch --show-current)" = "master" ]; then
      git pull --ff-only origin master >/dev/null \
        && echo "session-start: fast-forwarded master ($behind commit(s) from origin)"
    else
      echo "⚠️  session-start: local is $behind commit(s) behind origin/master." \
           "Tree is dirty or you're not on master — pull manually before working."
    fi
  fi
  exit 0
fi

# --- Remote: install dependencies -----------------------------------------

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
