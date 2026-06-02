"""Shared upload utilities for file-upload routers.

C72: Single source for ALLOWED_EXTENSIONS and get_file_extension — avoids
the duplicated definitions (and their emerging drift) between attachment_router
and knowledge_router.
"""

from __future__ import annotations

import os

# Canonical, frozen set shared by all upload endpoints.
ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Documents
        ".pdf",
        ".docx",
        ".doc",
        ".txt",
        ".md",
        ".html",
        ".xlsx",
        ".xls",
        ".pptx",
        ".ppt",
        # Images
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".bmp",
        # Code / data
        ".py",
        ".js",
        ".ts",
        ".json",
        ".yaml",
        ".yml",
        ".xml",
        ".csv",
    }
)


def get_file_extension(filename: str) -> str:
    """Return the lower-cased file extension (including the leading dot)."""
    return os.path.splitext(filename)[1].lower()
