"""Plan 2 Task 9 — 截图上传文件系统管理。

存储路径:`dashboard/screenshots/{cap_id}/{timestamp}-{safe_name}.{ext}`
进 git(.gitkeep 占位 + 用户 git add 实际文件)。

校验:
- 类型白名单:png / jpg / jpeg / gif / webp
- 大小:≤ 500_000 bytes (500KB)
- 文件名 sanitize:剔除非 ASCII / 路径分隔符
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

ALLOWED_TYPES = frozenset(["image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"])
ALLOWED_EXTS = frozenset(["png", "jpg", "jpeg", "gif", "webp"])
MAX_SIZE = 500_000  # 500KB


class UploadError(Exception):
    """上传校验失败。"""


@dataclass(frozen=True)
class UploadResult:
    rel_path: str
    markdown: str
    git_hint: str


def sanitize_filename(name: str) -> str:
    """剔除非 ASCII + 路径分隔符 + 危险字符。"""
    parts = name.rsplit(".", 1)
    ext = parts[1].lower() if len(parts) == 2 else ""
    stem = parts[0]
    safe_stem = re.sub(r"[^a-zA-Z0-9._-]", "_", stem)[:60] or "image"
    if ext and ext in ALLOWED_EXTS:
        return f"{safe_stem}.{ext}"
    return f"{safe_stem}.png"


def save_screenshot(
    base_dir: Path,
    cap_id: str,
    content: bytes,
    content_type: str,
    original_filename: str,
) -> UploadResult:
    """保存截图。返回 UploadResult。"""
    if content_type not in ALLOWED_TYPES:
        raise UploadError(f"unsupported type: {content_type}")
    if len(content) > MAX_SIZE:
        raise UploadError(f"size {len(content)} > {MAX_SIZE}")

    safe_cap = re.sub(r"[^a-zA-Z0-9._-]", "_", cap_id)
    if safe_cap != cap_id:
        raise UploadError(f"invalid cap_id: {cap_id}")

    out_dir = base_dir / "screenshots" / safe_cap
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_name = sanitize_filename(original_filename)
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out_path = out_dir / f"{ts}-{safe_name}"
    out_path.write_bytes(content)

    rel_path = f"screenshots/{safe_cap}/{out_path.name}"
    return UploadResult(
        rel_path=rel_path,
        markdown=f"![{safe_name}]({rel_path})",
        git_hint=f"git add dashboard/{rel_path}",
    )
