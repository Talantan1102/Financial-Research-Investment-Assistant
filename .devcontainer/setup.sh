#!/usr/bin/env bash
# Roadmap support — Codespaces postCreateCommand for this project.
# Universal:2-linux image already has docker / python / node / gh.
# This script just installs uv + syncs deps.

set -euo pipefail

echo "==[ Versions: docker / python / node / gh (already in universal image) ]=="
docker --version || echo "(docker unavailable — unexpected on universal image)"
python3 --version
node --version
gh --version | head -1

echo "==[ Install uv (Python pkg manager — manages own toolchain) ]=="
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  if [ -f ~/.bashrc ] && ! grep -q '\.local/bin' ~/.bashrc; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
  fi
fi
uv --version

echo "==[ Sync backend Python deps (uv sync --extra dev) ]=="
cd backend
uv sync --extra dev

echo "==[ Pre-commit hooks ]=="
uv run pre-commit install --install-hooks 2>/dev/null || \
  echo "(pre-commit install non-fatal failure, skip)"
uv run pre-commit install --hook-type commit-msg 2>/dev/null || \
  echo "(pre-commit commit-msg install non-fatal failure, skip)"

echo "==[ Frontend npm install ]=="
cd ../frontend
npm install --silent 2>&1 | tail -5 || echo "(npm install non-fatal failure)"

cd ..

echo ""
echo "============================================================"
echo "  Codespaces setup complete."
echo ""
echo "  Quick start:"
echo "    cd backend && cp .env.example .env"
echo "    docker compose up -d postgres redis"
echo "    uv run poe serve   # backend on :8000"
echo ""
echo "    cd ../frontend && npm run dev   # frontend on :5173"
echo "============================================================"
