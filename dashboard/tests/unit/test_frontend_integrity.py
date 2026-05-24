"""前端链路完整性 — 用 CI 跑得起的静态检查守护"serve path 无 CI 覆盖"盲区。

V2 polish ship 时 4 个前端 bug 全部漏过 CI(lint + pytest 只测 Python,
前端 JS / 模板 / CSS / 路由 method 一致性都没被自动化抓)。这些 invariant
test 每个对应一类盲区:跑得便宜,误报率低,任何破坏立即在 CI 红。
"""

from __future__ import annotations

import re
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = DASHBOARD_DIR / "static"
TEMPLATES_DIR = DASHBOARD_DIR / "templates"


def test_template_script_srcs_resolve_to_static_files() -> None:
    """templates/*.html 里所有 <script src="/static/X.js"> 必须对应 static/ 存在文件。

    bug history:cytoscape-cose-bilkent.min.js 加进来但 cose-base.js 没加,
    且没人 grep 静态资源对应关系 → ship 漏依赖。
    """
    pattern = re.compile(r'<script\s+src="/static/([^"?]+)')
    missing: list[tuple[str, str]] = []
    for tpl in TEMPLATES_DIR.rglob("*.html"):
        for m in pattern.finditer(tpl.read_text(encoding="utf-8")):
            asset = m.group(1)
            if not (STATIC_DIR / asset).is_file():
                missing.append((tpl.name, asset))
    assert not missing, f"template script src 引用了不存在的 static 文件:{missing}"


def test_refresh_route_accepts_get_for_eventsource() -> None:
    """/refresh 必须接受 GET — EventSource(W3C SSE)强制 GET method。

    bug history:Plan 1 后端写 methods=["POST"],Plan 2 前端 EventSource('/refresh') →
    405 Method Not Allowed → SSE 断连。
    """
    server_py = (DASHBOARD_DIR / "server.py").read_text(encoding="utf-8")
    match = re.search(
        r'Route\(\s*"/refresh"\s*,\s*\w+\s*,\s*methods=\[([^\]]+)\]',
        server_py,
    )
    assert match, "/refresh route 应有 methods= 显式声明"
    methods = {m.strip().strip("\"'") for m in match.group(1).split(",")}
    assert "GET" in methods, (
        f"/refresh 必须接受 GET(EventSource 标准),当前 methods={sorted(methods)}"
    )


def test_static_assets_have_cache_buster() -> None:
    """所有 <script src="/static/*"> / <link href="/static/*"> 必须带 ?v=,
    防止 Safari 等浏览器缓存旧 JS/CSS 导致修复不生效。

    bug history:V2 polish hotfix 改 overview.js 后 Safari 用本地缓存的旧 JS,
    用户 hard reload 也未必生效;加 ?v={{ asset_v }} 强制 cache miss。
    """
    asset_ref = re.compile(r'(?:<script\s+src|<link\s+rel="stylesheet"\s+href)="/static/[^"]*"')
    offenders: list[tuple[str, str]] = []
    for tpl in TEMPLATES_DIR.rglob("*.html"):
        if tpl.name == "mockup-v2.html":
            continue
        for m in asset_ref.finditer(tpl.read_text(encoding="utf-8")):
            ref = m.group(0)
            if "?v=" not in ref:
                offenders.append((tpl.name, ref[:80]))
    assert not offenders, f"静态资源引用缺 ?v= cache buster:{offenders}"


def test_modal_overlay_callers_use_modal_helper() -> None:
    """打开 modal-overlay 必须走 Modal.open(),不能直接改 inline display。

    bug history:overview.js / _story_card.html 直接 `overlay.style.display='flex'`,
    但 Modal.close() 是 class-based 只移除 'modal-overlay--open',inline display
    不被清 → modal 视觉不消失 → 用户被遮罩困住,看似卡死。
    """
    inline_display = re.compile(
        r"""(?:getElementById\(['"]modal-overlay['"]\)|#modal-overlay)"""
        r"""[^;<>]*?\.style\.display\s*=\s*['"]"""
    )
    offenders: list[str] = []
    for path in [*STATIC_DIR.glob("*.js"), *TEMPLATES_DIR.rglob("*.html")]:
        if path.name.endswith(".min.js") or path.name == "mockup-v2.html":
            continue
        text = path.read_text(encoding="utf-8")
        if inline_display.search(text):
            offenders.append(path.name)
    assert not offenders, (
        f"以下文件直接改 modal-overlay inline display(应改用 Modal.open()):{offenders}"
    )
