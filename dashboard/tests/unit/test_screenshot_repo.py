"""Plan 2 Task 9 — screenshot_repo 校验测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dashboard.derive.screenshot_repo import (
    MAX_SIZE,
    UploadError,
    sanitize_filename,
    save_screenshot,
)


def test_sanitize_filename_strips_unsafe() -> None:
    assert sanitize_filename("arch design.png") == "arch_design.png"
    # 非 ASCII strip
    out = sanitize_filename("中文.gif")
    assert out.endswith(".gif")
    assert all(
        c in "_-.abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" for c in out
    )
    # 无 ext 时补 .png
    assert sanitize_filename("no_ext") == "no_ext.png"


def test_save_screenshot_creates_file(tmp_path: Path) -> None:
    content = b"\x89PNG\r\n\x1a\n" + b"x" * 100
    result = save_screenshot(tmp_path, "execution.docker_compose", content, "image/png", "arch.png")
    assert result.rel_path.startswith("screenshots/execution.docker_compose/")
    assert result.rel_path.endswith("-arch.png")
    assert (
        "(/screenshots/execution.docker_compose/" in result.markdown
    )  # 绝对路径才能被 /screenshots mount serve
    assert (tmp_path / result.rel_path).exists()


def test_save_screenshot_rejects_unsupported_type(tmp_path: Path) -> None:
    with pytest.raises(UploadError, match="unsupported type"):
        save_screenshot(tmp_path, "x.y", b"data", "application/pdf", "foo.pdf")


def test_save_screenshot_rejects_too_large(tmp_path: Path) -> None:
    big = b"x" * (MAX_SIZE + 1)
    with pytest.raises(UploadError, match="size"):
        save_screenshot(tmp_path, "x.y", big, "image/png", "big.png")


def test_save_screenshot_rejects_path_traversal_cap_id(tmp_path: Path) -> None:
    with pytest.raises(UploadError, match="invalid cap_id"):
        save_screenshot(tmp_path, "../etc", b"x", "image/png", "x.png")
