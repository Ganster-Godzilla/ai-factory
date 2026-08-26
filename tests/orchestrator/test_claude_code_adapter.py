import json
import subprocess
from unittest.mock import patch
from orchestrator.adapters.base import TaskPacket
from orchestrator.adapters.claude_code import ClaudeCodeAdapter


def _packet(tmp_path):
    return TaskPacket(role="pm", prompt="写 PRD", workdir=tmp_path, budget={})


def test_success_parses_json(tmp_path):
    fake = subprocess.CompletedProcess(
        args=[], returncode=0,
        stdout=json.dumps({"result": "PRD 已写", "is_error": False,
                           "usage": {"input_tokens": 100, "output_tokens": 50}}),
        stderr="")
    with patch("subprocess.run", return_value=fake):
        r = ClaudeCodeAdapter().run(_packet(tmp_path))
    assert r.status == "done"
    assert r.output == "PRD 已写"
    assert r.tokens == {"input_tokens": 100, "output_tokens": 50}


def test_nonzero_exit_is_failed(tmp_path):
    fake = subprocess.CompletedProcess(args=[], returncode=1, stdout="boom", stderr="")
    with patch("subprocess.run", return_value=fake):
        assert ClaudeCodeAdapter().run(_packet(tmp_path)).status == "failed"


def test_timeout(tmp_path):
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=1)):
        assert ClaudeCodeAdapter().run(_packet(tmp_path)).status == "timeout"
