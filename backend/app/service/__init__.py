"""Legacy module — see backend/LEGACY_LAYOUT.md for module-by-module status and v1.x evolution plan.

New features should prefer importing from `app/services/*` (plural, v0.8.x main path).

This package intentionally has no eager imports — each module must be imported by
its full path (`from app.service.text2sql_service import Text2SQLService`). The
old barrel pattern pulled `llama_index` and other heavy deps into every consumer's
import chain even when they only needed a single legacy helper.
"""
