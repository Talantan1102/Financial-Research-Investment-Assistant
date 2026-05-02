"""MineruParser — mineru 3.x CLI subprocess wrapper(v0.7 default).

⚠️ Spike 1 后 pivot:不直接 import mineru API(Python 3.13 + Mac CPU 下
反复触发 huggingface 查询 / weights_only / 模型版本不匹配 等错),
改用 subprocess 包 CLI(`mineru -p X -o Y -b pipeline`),输出 JSON 文件再读取。

首次需 modelscope 下载 ~7GB 模型(MINERU_MODEL_SOURCE=modelscope env);
稳态推理(Mac CPU)~20s/page,5-page PDF ~1m40s(Spike 1 实测)。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from io import StringIO
from pathlib import Path
from typing import Any

from app.services.pdf_parser import ParsedDocument, Section, Table

# 默认输出根目录(test 中可 monkey-patch)
_OUT_ROOT: Path | None = None


class MineruParser:
    """MinerU 3.x backend(CLI subprocess wrap)."""

    def __init__(self, *, model_dir: str | None = None) -> None:
        # MINERU_MODEL_SOURCE=modelscope 是国内必需 env(否则走 HF 失败)
        os.environ.setdefault("MINERU_MODEL_SOURCE", "modelscope")
        if model_dir:
            os.environ["MINERU_MODEL_DIR"] = model_dir

    async def parse(self, pdf_path: Path) -> ParsedDocument:
        out_root = _OUT_ROOT or Path(tempfile.mkdtemp(prefix="mineru_v07_"))
        out_root.mkdir(parents=True, exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            "mineru",
            "-p",
            str(pdf_path),
            "-o",
            str(out_root),
            "-b",
            "pipeline",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"mineru CLI failed (exit {proc.returncode}): "
                f"stderr={stderr.decode('utf-8', errors='replace')[-500:]}"
            )

        stem = pdf_path.stem
        content_list_path = out_root / stem / "auto" / f"{stem}_content_list.json"
        if not content_list_path.exists():
            raise RuntimeError(f"mineru output missing: {content_list_path}")

        blocks = json.loads(content_list_path.read_text(encoding="utf-8"))
        return self._blocks_to_parsed_doc(blocks)

    @staticmethod
    def _blocks_to_parsed_doc(blocks: list[dict[str, Any]]) -> ParsedDocument:
        sections: list[Section] = []
        tables: list[Table] = []
        current_title: str | None = None

        # block types 11 种(Spike 1 实测):text(可有 text_level=1-6 表 heading)/
        # header / page_footnote / page_number / aside_text(全跳过,噪声)/
        # list / code / table / image / equation / chart(后 3 种 v0.7 跳过)
        SKIP = {
            "header",
            "page_footnote",
            "page_number",
            "aside_text",
            "image",
            "equation",
            "chart",
        }

        for blk in blocks:
            blk_type = blk.get("type", "text")
            if blk_type in SKIP:
                continue

            if blk_type == "table":
                html = blk.get("table_body", "")
                if not html:
                    continue
                caption_list = blk.get("table_caption", []) or []
                caption = caption_list[0] if caption_list else None
                tables.append(
                    Table(
                        markdown=_html_table_to_markdown(html),
                        title=caption,
                        section_index=max(0, len(sections) - 1),
                    )
                )
                continue

            text = (blk.get("text") or "").strip()
            if not text:
                continue

            if blk_type == "text" and blk.get("text_level"):
                # heading — flush 旧 title,记录新 title 作为下一段 paragraph 的 title
                if current_title:
                    sections.append(Section(title=current_title, text="", section_type="heading"))
                current_title = text
            elif blk_type == "code":
                sections.append(Section(title=current_title, text=text, section_type="code"))
                current_title = None
            elif blk_type == "list":
                sections.append(Section(title=current_title, text=text, section_type="list"))
                current_title = None
            else:  # text 普通段 / 默认
                sections.append(Section(title=current_title, text=text, section_type="paragraph"))
                current_title = None

        # 末尾 dangling title flush
        if current_title:
            sections.append(Section(title=current_title, text="", section_type="heading"))

        return ParsedDocument(sections=sections, tables=tables, metadata={})


def _html_table_to_markdown(html: str) -> str:
    """简化 HTML <table> → markdown 转换。

    用 pandas.read_html 健壮处理 colspan/rowspan;失败 fallback 到 regex 提取
    (mineru 输出的 HTML 有时 colspan 让 pandas 报错)。
    """
    try:
        import pandas as pd

        dfs = pd.read_html(StringIO(html))
        if dfs:
            return str(dfs[0].to_markdown(index=False))
    except Exception:
        pass
    # fallback:粗暴 regex 提取 cell 文本
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.DOTALL)
    md_lines: list[str] = []
    for i, row_html in enumerate(rows):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, flags=re.DOTALL)
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        if not cells:
            continue
        md_lines.append("| " + " | ".join(cells) + " |")
        if i == 0:
            md_lines.append("|" + "|".join(["---"] * len(cells)) + "|")
    return "\n".join(md_lines)
