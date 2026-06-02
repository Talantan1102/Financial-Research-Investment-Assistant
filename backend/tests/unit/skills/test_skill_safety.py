"""L0 — skill_safety AST scanner."""

from __future__ import annotations

import pytest
from app.skills.skill_safety import (
    BANNED_APIS,
    SafetyScanError,
    scan_script_safety,
)


def test_banned_apis_listed():
    expected = {
        "os.system",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.run",
        "subprocess.check_call",
        "subprocess.check_output",
        "socket.socket",
        "urllib.request.urlopen",
        "requests.get",
        "requests.post",
        "httpx.get",
        "httpx.post",
        "eval",
        "exec",
        "__import__",
    }
    for api in expected:
        assert api in BANNED_APIS


def test_scan_clean_script_passes():
    src = """
import json, math
def dcf(financials, wacc):
    return sum(f / (1+wacc)**i for i, f in enumerate(financials, 1))
print(json.dumps({'ok': True}))
"""
    scan_script_safety(src)


def test_scan_rejects_os_system():
    src = "import os\nos.system('rm -rf /')\n"
    with pytest.raises(SafetyScanError, match="os.system"):
        scan_script_safety(src)


def test_scan_rejects_subprocess_run():
    src = "import subprocess\nsubprocess.run(['ls'])\n"
    with pytest.raises(SafetyScanError, match="subprocess.run"):
        scan_script_safety(src)


def test_scan_rejects_subprocess_popen():
    src = "from subprocess import Popen\nPopen(['ls'])\n"
    with pytest.raises(SafetyScanError, match="Popen"):
        scan_script_safety(src)


def test_scan_rejects_eval_exec():
    src = "eval('1+1')\n"
    with pytest.raises(SafetyScanError, match="eval"):
        scan_script_safety(src)
    src2 = "exec('print(1)')\n"
    with pytest.raises(SafetyScanError, match="exec"):
        scan_script_safety(src2)


def test_scan_rejects_dunder_import():
    src = "x = __import__('os')\n"
    with pytest.raises(SafetyScanError, match="__import__"):
        scan_script_safety(src)


def test_scan_rejects_socket():
    src = "import socket\ns = socket.socket()\n"
    with pytest.raises(SafetyScanError, match="socket"):
        scan_script_safety(src)


def test_scan_rejects_urllib_request():
    src = "import urllib.request\nurllib.request.urlopen('http://x.com')\n"
    with pytest.raises(SafetyScanError, match="urlopen"):
        scan_script_safety(src)


def test_scan_rejects_requests_http():
    src = "import requests\nrequests.get('http://x.com')\n"
    with pytest.raises(SafetyScanError, match="requests.get"):
        scan_script_safety(src)


def test_scan_rejects_aliased_subprocess():
    src = "import subprocess as sp\nsp.run(['ls'])\n"
    with pytest.raises(SafetyScanError):
        scan_script_safety(src)


def test_scan_invalid_python_raises():
    src = "this is not python !!"
    with pytest.raises(SafetyScanError, match="syntax"):
        scan_script_safety(src)


# C33 — file-read / sandbox-escape APIs that were previously missing from BANNED_APIS


def test_scan_rejects_open():
    """open('/etc/passwd').read() must be rejected by the scanner."""
    src = "data = open('/etc/passwd').read()\n"
    with pytest.raises(SafetyScanError, match="open"):
        scan_script_safety(src)


def test_scan_rejects_open_write():
    """open(..., 'w') file-write path must also be rejected."""
    src = "open('/tmp/evil.txt', 'w').write('boom')\n"
    with pytest.raises(SafetyScanError, match="open"):
        scan_script_safety(src)


def test_scan_rejects_compile():
    """compile() can construct code objects from arbitrary strings — must be banned."""
    src = "code = compile('import os', '<string>', 'exec')\n"
    with pytest.raises(SafetyScanError, match="compile"):
        scan_script_safety(src)


def test_scan_rejects_importlib_import_module():
    """importlib.import_module is an alternative __import__ vector."""
    src = "import importlib\nimportlib.import_module('os')\n"
    with pytest.raises(SafetyScanError, match="importlib.import_module"):
        scan_script_safety(src)


def test_scan_rejects_importlib_import_module_from_import():
    """from importlib import import_module; import_module('os') must be caught."""
    src = "from importlib import import_module\nimport_module('subprocess')\n"
    with pytest.raises(SafetyScanError, match="importlib.import_module"):
        scan_script_safety(src)


def test_scan_rejects_ctypes_cdll():
    """ctypes.CDLL can load native shared libraries — must be banned."""
    src = "import ctypes\nlib = ctypes.CDLL('libc.so.6')\n"
    with pytest.raises(SafetyScanError, match="ctypes.CDLL"):
        scan_script_safety(src)
