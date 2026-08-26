"""M2 验收:真实 harness 集成测试(slow)。

默认被 pytest.ini 的 addopts(-m "not slow")排除;
显式运行:python -m pytest tests/orchestrator/test_integration_live.py -v -m slow

无对应 CLI 时按 skipif 跳过(当前环境:dsh 未安装 → dsh 用例 skip)。
"""
import shutil

import pytest

from orchestrator.adapters.base import TaskPacket
from orchestrator.adapters.claude_code import ClaudeCodeAdapter
from orchestrator.adapters.dsh import DshAdapter

pytestmark = pytest.mark.slow


@pytest.mark.skipif(not shutil.which("claude"), reason="无 claude CLI")
def test_claude_headless_minimal(tmp_path):
    pkt = TaskPacket(role="pm", prompt="用一句话回答:1+1等于几?只输出数字。",
                     workdir=tmp_path, budget={}, timeout=300)
    r = ClaudeCodeAdapter().run(pkt)
    assert r.status == "done"
    assert "2" in r.output


@pytest.mark.skipif(not shutil.which("dsh"), reason="无 dsh CLI")
def test_dsh_headless_minimal(tmp_path):
    pkt = TaskPacket(role="dev", prompt="用一句话回答:1+1等于几?只输出数字。",
                     workdir=tmp_path, budget={}, timeout=300)
    r = DshAdapter().run(pkt)
    assert r.status == "done"
    assert "2" in r.output
