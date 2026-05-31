"""Static AST safety scan for L3b skill scripts (S9 任意代码执行安全)."""

from __future__ import annotations

import ast
from typing import Final

BANNED_APIS: Final[frozenset[str]] = frozenset(
    {
        "os.system",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.run",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.getoutput",
        "subprocess.getstatusoutput",
        "socket.socket",
        "urllib.request.urlopen",
        "requests.get",
        "requests.post",
        "requests.put",
        "requests.delete",
        "requests.request",
        "httpx.get",
        "httpx.post",
        "httpx.put",
        "httpx.delete",
        "eval",
        "exec",
        "__import__",
        # C33: file-read/sandbox-escape builtins missing from original set
        "open",
        "compile",
        "importlib.import_module",
        "ctypes.CDLL",
    }
)


class SafetyScanError(Exception):
    """Raised when a script contains a banned API reference."""


def scan_script_safety(source: str) -> None:
    """Parse `source` and raise SafetyScanError if any banned API is referenced."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise SafetyScanError(f"syntax error: {exc}") from exc

    aliases: dict[str, str] = {}
    from_imports: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                key = alias.asname or alias.name
                aliases[key] = alias.name
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                key = alias.asname or alias.name
                from_imports[key] = f"{mod}.{alias.name}" if mod else alias.name

    def _resolve_call(call_node: ast.Call) -> str | None:
        f = call_node.func
        if isinstance(f, ast.Name):
            if f.id in from_imports:
                return from_imports[f.id]
            return f.id
        if isinstance(f, ast.Attribute):
            chain: list[str] = []
            cur: ast.expr = f
            while isinstance(cur, ast.Attribute):
                chain.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                base = aliases.get(cur.id, cur.id)
                chain.append(base)
                return ".".join(reversed(chain))
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            resolved = _resolve_call(node)
            if resolved and resolved in BANNED_APIS:
                raise SafetyScanError(f"banned API: {resolved} at line {node.lineno}")
