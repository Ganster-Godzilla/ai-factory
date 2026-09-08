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


# ── T-2026-0908-003 R2:--model 白名单传递 ─────────────────────────────────────

def _captured_cmd(tmp_path, model):
    pkt = TaskPacket(role="dev", prompt="x", workdir=tmp_path, budget={}, model=model)
    fake = subprocess.CompletedProcess(
        args=[], returncode=0,
        stdout=json.dumps({"result": "ok", "is_error": False, "usage": {}}),
        stderr="")
    with patch("subprocess.run", return_value=fake) as m:
        ClaudeCodeAdapter().run(pkt)
    return m.call_args.args[0] if m.call_args.args else m.call_args[0][0]


def test_driver_model_whitelist_passes_flag(tmp_path):
    for model in ("k2.6", "gpt-6-astra"):
        cmd = _captured_cmd(tmp_path, model)
        assert "--model" in cmd and model in cmd, f"{model} 应传 --model"


def test_non_whitelist_model_never_passed(tmp_path):
    for model in ("deepseek-v4-flash", "kimi-k2.6", "claude-sonnet"):
        cmd = _captured_cmd(tmp_path, model)
        assert "--model" not in cmd, f"{model} 非白名单不得传 --model"


def test_none_model_no_flag(tmp_path):
    cmd = _captured_cmd(tmp_path, None)
    assert "--model" not in cmd
