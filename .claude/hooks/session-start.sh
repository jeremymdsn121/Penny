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
