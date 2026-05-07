# dashboard/tests/derive/test_app_shell_stat.py
from pathlib import Path

from dashboard.derive.app_shell_stat import compute_app_shell_stat
from dashboard.derive.types import DimensionConfig


def _mk_config(id_: str, name_cn: str, paths: tuple[str, ...]) -> DimensionConfig:
    return DimensionConfig(
        id=id_,
        number="09",
        name_cn=name_cn,
        name_en=name_cn,
        paths=paths,
    )


def test_basic_file_count(tmp_path: Path) -> None:
    """一个 path glob 命中多个文件,正确数到。"""
    (tmp_path / "frontend" / "src").mkdir(parents=True)
    (tmp_path / "frontend" / "src" / "App.tsx").write_text("x")
    (tmp_path / "frontend" / "src" / "main.tsx").write_text("x")
    cfg = _mk_config("frontend", "前端", ("frontend/**",))
    out = compute_app_shell_stat(tmp_path, [cfg])
    assert len(out) == 1
    assert out[0].id == "frontend"
    assert out[0].name_cn == "前端"
    assert out[0].file_count == 2


def test_empty_dir_zero(tmp_path: Path) -> None:
    """目标 path 不存在,count = 0。"""
    cfg = _mk_config("frontend", "前端", ("frontend/**",))
    out = compute_app_shell_stat(tmp_path, [cfg])
    assert out[0].file_count == 0


def test_glob_no_match_zero(tmp_path: Path) -> None:
    """glob 不命中(扩展名错),count = 0。"""
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "README.md").write_text("x")
    cfg = _mk_config("frontend", "前端", ("frontend/**/*.tsx",))
    out = compute_app_shell_stat(tmp_path, [cfg])
    assert out[0].file_count == 0


def test_multi_path_glob_sums(tmp_path: Path) -> None:
    """多个 path glob,count 相加。"""
    (tmp_path / "backend" / "app").mkdir(parents=True)
    (tmp_path / "backend" / "app" / "main.py").write_text("x")
    (tmp_path / "frontend" / "src").mkdir(parents=True)
    (tmp_path / "frontend" / "src" / "App.tsx").write_text("x")
    cfg = _mk_config(
        "fullstack",
        "全栈",
        ("backend/app/**/*.py", "frontend/src/**/*.tsx"),
    )
    out = compute_app_shell_stat(tmp_path, [cfg])
    assert out[0].file_count == 2
