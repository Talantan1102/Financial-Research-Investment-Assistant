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

# ============================================================================
# v1.0 monitoring engine — Celery worker + beat (dev)
# ============================================================================
.PHONY: worker beat worker-eager-test clean-monitoring

worker: ## v1.0 monitoring: Start Celery worker (default + llm queues)
	@echo ">> starting Celery worker (Q=default,llm concurrency=4)"
	cd backend && uv run celery -A app.tasks.celery_app worker -Q default,llm --concurrency 4 --loglevel INFO

beat: ## v1.0 monitoring: Start Celery beat scheduler
	@echo ">> starting Celery beat (schedule from celery_beat_schedule.py)"
	cd backend && uv run celery -A app.tasks.celery_app beat --loglevel INFO

worker-eager-test: ## v1.0 monitoring: Run pytest with eager Celery (no broker needed)
	cd backend && CELERY_TASK_ALWAYS_EAGER=1 CELERY_TASK_EAGER_PROPAGATES=1 uv run pytest tests/unit/tasks/ -v

clean-monitoring: ## v1.0 monitoring: Drop runtime sqlite (after PG migration)
	rm -f backend/data/monitoring.sqlite
	@echo ">> monitoring.sqlite dropped"
