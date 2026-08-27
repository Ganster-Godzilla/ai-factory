import subprocess
from pathlib import Path
from unittest.mock import patch, call
from orchestrator.adapters.base import TaskPacket
from orchestrator.adapters.dsh import DshAdapter
from orchestrator.adapters.dsh_profiles import settings_yaml


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


def test_env_injected_from_keys_dir(tmp_path):
    (tmp_path / "deepseek.env").write_text("KEY=sk-test-123\n", encoding="utf-8")
    fake = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
    with patch("subprocess.run", return_value=fake) as m:
        DshAdapter(keys_dir=tmp_path).run(
            TaskPacket(role="dev", prompt="p", workdir=tmp_path, budget={}))
    env = m.call_args.kwargs["env"]
    assert env["DEEPSEEK_API_KEY"] == "sk-test-123"


def test_missing_dsh_wrapped(tmp_path):
    with patch("shutil.which", return_value=None), \
         patch("subprocess.run", side_effect=FileNotFoundError):
        r = DshAdapter().run(TaskPacket(role="dev", prompt="p", workdir=tmp_path, budget={}))
    assert r.status == "failed" and "dsh" in r.output


def test_settings_yaml_has_both_providers():
    txt = settings_yaml({})
    assert "deepseek" in txt and "zhipu" in txt
    assert "DEEPSEEK_API_KEY" in txt and "ZHIPU_API_KEY" in txt
    assert "sk-" not in txt   # 不含任何 key 值
