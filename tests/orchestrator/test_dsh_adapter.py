import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch
from orchestrator.adapters.base import TaskPacket
from orchestrator.adapters.dsh import (
    DshAdapter, USAGE_MISSING_MSG, USAGE_TRAILER, parse_usage_trailer,
)
from orchestrator.adapters.dsh_profiles import settings_yaml


def _packet(tmp_path):
    return TaskPacket(role="dev", prompt="实现 task-1", workdir=tmp_path, budget={})


def _trailer(i=120, o=340, cost=0.05) -> str:
    """按 D3 契约拼 usage trailer 末行"""
    payload = json.dumps({"input_tokens": i, "output_tokens": o, "cost_cny": cost})
    return f"{USAGE_TRAILER} {payload}"


def _fake(stdout="ok", stderr="", returncode=0, trailer=True):
    out = f"{stdout}\n{_trailer()}" if trailer else stdout
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=out, stderr=stderr)


def test_exit_zero_is_done(tmp_path):
    with patch("subprocess.run", return_value=_fake()) as m:
        r = DshAdapter().run(_packet(tmp_path))
    assert r.status == "done"
    cmd = m.call_args[0][0]
    assert Path(cmd[0]).name.lower().startswith("dsh")  # shim 可能解析为全路径
    assert cmd[1:3] == ["--profile", "headless"]


def test_nonzero_is_failed(tmp_path):
    with patch("subprocess.run", return_value=_fake(stdout="out", stderr="err",
                                                    returncode=1)):
        r = DshAdapter().run(_packet(tmp_path))
    assert r.status == "failed" and "err" in r.output


def test_timeout(tmp_path):
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="dsh", timeout=1)):
        assert DshAdapter().run(_packet(tmp_path)).status == "timeout"


# ---- usage trailer 契约消费(T-2026-0828-003 设计 D3) ----

def test_trailer_parsed_tokens_cost_filled_and_stripped(tmp_path):
    fake = _fake(stdout="实现完成\n详见 foo.py")
    with patch("subprocess.run", return_value=fake):
        r = DshAdapter().run(_packet(tmp_path))
    assert r.status == "done"
    assert r.tokens == {"input_tokens": 120, "output_tokens": 340}
    assert r.cost_cny == 0.05
    assert "实现完成" in r.output and "foo.py" in r.output
    assert USAGE_TRAILER not in r.output          # trailer 剥离,不污染正文


def test_no_trailer_degraded_warn_and_estimate(tmp_path):
    # 明放(T-2026-0829-004):现役 dsh 无 trailer → 按 returncode 推进 + usage_missing
    # 留痕 + 按次估算入账(禁止记 0);缺省 est=0 时估算关闭(向后兼容)
    with patch("subprocess.run", return_value=_fake(stdout="ok", trailer=False)):
        r = DshAdapter().run(_packet(tmp_path))
    assert r.status == "done"                        # rc=0 → done,不再硬判负
    assert r.usage_missing is True
    assert USAGE_MISSING_MSG in r.output
    assert r.tokens == {} and r.cost_cny == 0.0 and r.estimated is False
    with patch("subprocess.run", return_value=_fake(stdout="ok", trailer=False)):
        r = DshAdapter(est_call_cny=0.05).run(_packet(tmp_path))
    assert r.status == "done" and r.cost_cny == 0.05 and r.estimated is True


def test_trailer_must_be_last_line(tmp_path):
    # trailer 之后还有正文 = 输出流不完整/非契约版本,视同缺失→明放降级
    with patch("subprocess.run",
               return_value=_fake(stdout=f"{_trailer()}\n后续还有输出", trailer=False)):
        r = DshAdapter(est_call_cny=0.05).run(_packet(tmp_path))
    assert r.status == "done" and r.usage_missing is True
    assert r.cost_cny == 0.05 and r.estimated is True


def test_malformed_trailer_treated_as_missing(tmp_path):
    bads = [f"{USAGE_TRAILER} {{broken json",
            f"{USAGE_TRAILER} [1, 2, 3]",
            f'{USAGE_TRAILER} {{"input_tokens": 1}}']   # 缺 output_tokens/cost_cny 键
    for bad in bads:
        with patch("subprocess.run", return_value=_fake(stdout=bad, trailer=False)):
            r = DshAdapter(est_call_cny=0.05).run(_packet(tmp_path))
        assert r.status == "done" and r.usage_missing is True, bad
        assert r.estimated is True, bad


def test_failed_run_with_trailer_still_reports_usage(tmp_path):
    # 烧了钱就是烧了:非零退出但 trailer 在 → tokens/cost 照常回传供入账
    with patch("subprocess.run", return_value=_fake(stdout="", stderr="boom",
                                                    returncode=1)):
        r = DshAdapter().run(_packet(tmp_path))
    assert r.status == "failed"
    assert r.tokens == {"input_tokens": 120, "output_tokens": 340}
    assert r.cost_cny == 0.05 and r.usage_missing is False
    assert "boom" in r.output


def test_parse_usage_trailer_tolerates_trailing_blank_lines():
    body, tokens, cost = parse_usage_trailer(f"hello\n{_trailer(i=1, o=2, cost=0.5)}\n\n")
    assert body == "hello"
    assert tokens == {"input_tokens": 1, "output_tokens": 2} and cost == 0.5
    assert parse_usage_trailer("") is None
    assert parse_usage_trailer("no trailer at all") is None


def test_env_injected_from_keys_dir(tmp_path):
    (tmp_path / "deepseek.env").write_text("KEY=sk-test-123\n", encoding="utf-8")
    with patch("subprocess.run", return_value=_fake()) as m:
        DshAdapter(keys_dir=tmp_path).run(
            TaskPacket(role="dev", prompt="p", workdir=tmp_path, budget={}))
    env = m.call_args.kwargs["env"]
    assert env["DEEPSEEK_API_KEY"] == "sk-test-123"


def test_missing_dsh_wrapped(tmp_path):
    with patch("shutil.which", return_value=None), \
         patch("subprocess.run", side_effect=FileNotFoundError):
        r = DshAdapter().run(TaskPacket(role="dev", prompt="p", workdir=tmp_path, budget={}))
    assert r.status == "failed" and "dsh" in r.output


def test_placeholder_key_fail_fast(tmp_path):
    # Finding S2:deepseek.env 只有占位 key(TODO 开头)且环境无真 key →
    # 直接 failed,不进入 subprocess
    (tmp_path / "deepseek.env").write_text("KEY=TODO-FILL\n", encoding="utf-8")
    with patch.dict(os.environ, {}, clear=True), \
         patch("subprocess.run") as m:
        r = DshAdapter(keys_dir=tmp_path).run(_packet(tmp_path))
    assert r.status == "failed"
    assert "key 未填" in r.output and "deepseek.env" in r.output
    m.assert_not_called()


def test_empty_key_fail_fast(tmp_path):
    # 空值同样算未填
    (tmp_path / "deepseek.env").write_text("KEY=\n", encoding="utf-8")
    with patch.dict(os.environ, {}, clear=True), \
         patch("subprocess.run") as m:
        r = DshAdapter(keys_dir=tmp_path).run(_packet(tmp_path))
    assert r.status == "failed" and "key 未填" in r.output
    m.assert_not_called()


def test_placeholder_does_not_override_real_env_key(tmp_path):
    # Finding S2:os.environ 已有真 key 时,文件里的 TODO 占位不得覆盖
    (tmp_path / "deepseek.env").write_text("KEY=TODO-FILL\n", encoding="utf-8")
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-real-456"}), \
         patch("subprocess.run", return_value=_fake()) as m:
        r = DshAdapter(keys_dir=tmp_path).run(
            TaskPacket(role="dev", prompt="p", workdir=tmp_path, budget={}))
    assert r.status == "done"
    assert m.call_args.kwargs["env"]["DEEPSEEK_API_KEY"] == "sk-real-456"


def test_settings_yaml_has_both_providers():
    txt = settings_yaml({})
    assert "deepseek" in txt and "zhipu" in txt
    assert "DEEPSEEK_API_KEY" in txt and "ZHIPU_API_KEY" in txt
    assert "sk-" not in txt   # 不含任何 key 值


def test_glm_env_injected(tmp_path):
    # key 文件名约定为 glm.env(dsh settings 里 provider id 仍为 zhipu)
    (tmp_path / "glm.env").write_text("KEY=glm-test-999\n", encoding="utf-8")
    with patch("subprocess.run", return_value=_fake()) as m:
        DshAdapter(keys_dir=tmp_path).run(
            TaskPacket(role="dev", prompt="p", workdir=tmp_path, budget={}))
    assert m.call_args.kwargs["env"]["ZHIPU_API_KEY"] == "glm-test-999"
