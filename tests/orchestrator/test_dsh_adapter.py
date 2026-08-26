import subprocess
from unittest.mock import patch, call
from orchestrator.adapters.base import TaskPacket
from orchestrator.adapters.dsh import DshAdapter


def _packet(tmp_path):
    return TaskPacket(role="dev", prompt="实现 task-1", workdir=tmp_path, budget={})


def test_exit_zero_is_done(tmp_path):
    fake = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
    with patch("subprocess.run", return_value=fake) as m:
        r = DshAdapter().run(_packet(tmp_path))
    assert r.status == "done"
    assert m.call_args[0][0][:3] == ["dsh", "--profile", "headless"]


def test_nonzero_is_failed(tmp_path):
    fake = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="err")
    with patch("subprocess.run", return_value=fake):
        r = DshAdapter().run(_packet(tmp_path))
    assert r.status == "failed" and "err" in r.output


def test_timeout(tmp_path):
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="dsh", timeout=1)):
        assert DshAdapter().run(_packet(tmp_path)).status == "timeout"
