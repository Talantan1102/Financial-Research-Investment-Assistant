"""charting 技能 —— 自动进 L1 清单 + load_skill 返回全文(SKILL.md frontmatter 合法)。"""

from __future__ import annotations

from app.chatloop.worker_wiring import CHAT_SKILLS_ROOT
from app.skills.skill_loader import SkillLoader


def test_charting_skill_in_l1_listing() -> None:
    loader = SkillLoader(skills_root=CHAT_SKILLS_ROOT)
    names = {m.name for m in loader.load_l1()}
    assert "charting" in names, f"charting 未进 L1 清单: {sorted(names)}"


def test_charting_skill_loads_full_body() -> None:
    loader = SkillLoader(skills_root=CHAT_SKILLS_ROOT)
    res = loader.load_skill("charting")
    body = res.skill_md_content
    # 关键方法论必须在正文里(模型 load 后能看到写法契约 + 风格)
    assert "figures" in body
    assert "data" in body
    assert "plotly" in body.lower()
    assert "红涨绿跌" in body or "#FF3B30" in body
