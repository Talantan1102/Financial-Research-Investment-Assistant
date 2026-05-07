#!/usr/bin/env bash
# Roadmap support — Codespaces postCreateCommand for this project.
# Installs uv, syncs backend deps, prepares frontend.

set -euo pipefail

echo "==[ Install uv (manages Python toolchain) ]=="
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# Persist PATH for future bash shells
if [ -f ~/.bashrc ] && ! grep -q '\.local/bin' ~/.bashrc; then
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
fi

echo "==[ Sync backend Python deps ]=="
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
