# Codespaces / Devcontainer

This directory configures GitHub Codespaces for the project.

## What you get

- **Python 3.12** + uv (auto-installed by `setup.sh`)
- **Node.js 20** for frontend
- **Docker-in-Docker** — `docker compose up postgres redis` works inside the codespace
- **GitHub CLI** for issue/PR ops
- **VSCode extensions**:Pylance / Ruff / Mypy / GitLens / GitHub PR / Docker

## Quick start

After Codespaces creation finishes (~5-10 min first time, then 30s start/stop):

```bash
# Backend (terminal 1)
cd backend
cp .env.example .env  # edit if needed (DASHSCOPE_API_KEY etc.)
docker compose up -d postgres redis
uv run poe serve  # http://localhost:8000

# Frontend (terminal 2)
cd frontend
npm run dev  # http://localhost:5173 (port forwarded automatically)
```

## CLI from your local machine

```bash
# Create from current branch
gh codespace create

# Connect (or use VSCode Remote)
gh codespace ssh

# Stop (saves cost)
gh codespace stop

# List
gh codespace list
```

## Cost notes

- Personal accounts: 60 hours/month free (4-core machine)
- After free quota: $0.18/hour
- Set spending limit in GitHub Settings → Codespaces → Spending limit

## Why this exists

Roadmap #3.5 PR A-E require Docker for PG/Redis verification. Local Windows
machines with disabled VT-x can't run Docker Desktop. Codespaces is the
zero-BIOS-config alternative — fully Linux env in cloud.

See: `docs/superpowers/specs/2026-05-07-roadmap-3.5-db-unify-design.md`
