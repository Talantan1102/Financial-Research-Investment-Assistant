# ============================================================
# Harness Board (dev meta-tool)
# ============================================================
.PHONY: board board-stop board-refresh board-test

board:
	@uv run --project backend python -m dashboard.server &
	@sleep 1 && open http://localhost:8910

board-stop:
	@lsof -ti tcp:8910 | xargs -r kill 2>/dev/null || true

board-refresh:
	@curl -sX POST http://localhost:8910/refresh && echo " ✓ refreshed"

board-test:
	@uv run --project backend pytest dashboard/tests/ -v
