"""L0 — TierRouter config resolution + interface stability."""

import pytest
from app.services.tier_router import TierConfig, TierRouter


def test_default_v0_config_all_tiers_resolve_to_v4_flash() -> None:
    router = TierRouter.from_default_v0_config()
    assert router.resolve("fast") == "deepseek-v4-flash"
    assert router.resolve("balanced") == "deepseek-v4-flash"
    assert router.resolve("deep") == "deepseek-v4-flash"


def test_custom_config_resolves_per_tier() -> None:
    cfg = TierConfig(fast="m1", balanced="m2", deep="m3")
    router = TierRouter(cfg)
    assert router.resolve("fast") == "m1"
    assert router.resolve("deep") == "m3"


def test_unknown_tier_raises() -> None:
    router = TierRouter.from_default_v0_config()
    with pytest.raises(ValueError, match="unknown tier"):
        router.resolve("ultra")  # type: ignore[arg-type]
