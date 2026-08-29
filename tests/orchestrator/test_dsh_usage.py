"""T-2026-0829-002:dsh 会话文件 usage 解析 + adapter 优先级链。"""
import json
from unittest.mock import patch, MagicMock

import zstandard

from orchestrator.adapters.base import TaskPacket
from orchestrator.adapters.dsh import DshAdapter
from orchestrator.adapters.dsh_usage import (estimate_cost, find_session_file,
                                             read_session_usage)

RATES = {"deepseek": {"input_per_m": 2.0, "cache_hit_per_m": 0.5,
                      "output_per_m": 8.0},
         "glm": {"input_per_m": 0, "cache_hit_per_m": 0, "output_per_m": 0}}


def _mk_session(dir_path, records, frames=1):
    """造 session.jsonl.zstd:records 按 frames 切成多帧追加。"""
    dir_path.mkdir(parents=True, exist_ok=True)
    f = dir_path / "session.jsonl.zstd"
    cctx = zstandard.ZstdCompressor()
    chunks = [records[i::frames] for i in range(frames)] if frames > 1 else [records]
    with f.open("wb") as fh:
        for part in chunks:
            body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in part)
            fh.write(cctx.compress(body.encode("utf-8")))
    return f


def _header(cwd):
    return {"type": "session", "version": 0, "id": "s1", "cwd": cwd}


def _usage(turn, step, t, inp=100, out=50, cache=None):
    u = {"inputTokens": inp, "outputTokens": out}
    if cache is not None:
        u["cacheReadTokens"] = cache
    return {"type": "assistant/chunk", "seq": step, "time": t,
            "data": {"turn": turn, "step": step,
                     "chunk": {"type": "usage", "usage": u}}}


# ---------- F2 多帧解压 + F3 过滤汇总 ----------

def test_multiframe_zstd_full_read(tmp_path):
    f = _mk_session(tmp_path / "s",
                    [_header("x"), _usage(1, 1, 1000), _usage(1, 2, 2000)],
                    frames=2)
    got = read_session_usage(f, since_ms=0)
    assert got == {"input": 200, "output": 100, "cache_read": 0}


def test_usage_filter_dedup_sum(tmp_path):
    f = _mk_session(tmp_path / "s", [
        _header("x"),
        _usage(1, 1, 500, inp=999, out=999),          # 早于 since → 滤掉
        _usage(1, 1, 1500, inp=100, out=10),          # 同 (turn,step) 旧值
        _usage(1, 1, 1600, inp=120, out=12),          # 同键取末
        _usage(1, 2, 1700, inp=200, out=20, cache=8000),
    ])
    got = read_session_usage(f, since_ms=1000)
    assert got == {"input": 320, "output": 32, "cache_read": 8000}


def test_no_usage_returns_none(tmp_path):
    f = _mk_session(tmp_path / "s", [_header("x")])
    assert read_session_usage(f, since_ms=0) is None


def test_corrupt_file_returns_none(tmp_path):
    f = tmp_path / "bad.zstd"
    f.write_bytes(b"\x00\x01garbage")
    assert read_session_usage(f, since_ms=0) is None


# ---------- F1 定位 ----------

def test_find_session_fastpath(tmp_path):
    sd = tmp_path / "sessions"
    f = _mk_session(sd / "--D-workspace-proj--" / "session-1",
                    [_header("d:\\workspace\\proj"), _usage(1, 1, 100)])
    got = find_session_file(sd, "d:\\workspace\\proj", since_ms=0)
    assert got == f


def test_find_session_by_cwd_header(tmp_path):
    # 目录名完全不符也能按 session 头 cwd 命中(转义规则漂移免疫)
    sd = tmp_path / "sessions"
    f = _mk_session(sd / "weird-name" / "session-1", [_header("D:/workspace/proj"),
                                        _usage(1, 1, 100)])
    got = find_session_file(sd, "d:\\workspace\\proj", since_ms=0)
    assert got == f


def test_find_session_missing_dir(tmp_path):
    assert find_session_file(tmp_path / "nope", "d:\\x", since_ms=0) is None


# ---------- F4 费率 ----------

def test_estimate_cost_rates():
    usage = {"input": 100000, "output": 10000, "cache_read": 1000000}
    cost = estimate_cost(RATES, "deepseek", usage)
    # input 10万×¥2/M=0.2;output 1万×¥8/M=0.08;cache 100万×¥0.5/M=0.5 → 0.78
    assert cost == 0.78


def test_estimate_cost_glm_zero():
    cost = estimate_cost(RATES, "glm", {"input": 10**6, "output": 10**6,
                                        "cache_read": 10**6})
    assert cost == 0.0


# ---------- adapter 优先级链(F5/F7) ----------

def _pkt(tmp_path, model="deepseek"):
    return TaskPacket(role="dev", prompt="x", workdir=tmp_path, timeout=10,
                      model=model)


def _fake_run(stdout="out", rc=0):
    m = MagicMock()
    m.stdout, m.stderr, m.returncode = stdout, "", rc
    return m


def _sessions_for(tmp_path, workdir, records):
    sd = tmp_path / "sessions"
    _mk_session(sd / "--x--" / "session-1", [_header(str(workdir))] + records)
    return sd


def test_trailer_wins(tmp_path):
    sd = _sessions_for(tmp_path, tmp_path,
                       [_usage(1, 1, 10**13, inp=99999, out=99999)])
    ad = DshAdapter(rates=RATES, sessions_dir=sd)
    out = 'ok\n__DSH_USAGE__ {"input_tokens": 100, "output_tokens": 50, "cost_cny": 0.012}'
    with patch("subprocess.run", return_value=_fake_run(out)):
        r = ad.run(_pkt(tmp_path))
    assert r.cost_cny == 0.012 and r.estimated is False
    assert r.tokens == {"input_tokens": 100, "output_tokens": 50}


def test_session_fallback_real_cost(tmp_path):
    sd = _sessions_for(tmp_path, tmp_path, [
        _usage(1, 1, 10**13, inp=100000, out=10000, cache=1000000)])
    ad = DshAdapter(rates=RATES, sessions_dir=sd)
    with patch("subprocess.run", return_value=_fake_run("无 trailer")):
        r = ad.run(_pkt(tmp_path))
    assert r.status == "done"
    assert r.estimated is False and r.usage_missing is False    # 真实计量
    assert r.tokens == {"input_tokens": 100000, "output_tokens": 10000}
    assert r.cost_cny == 0.78                                    # 含 cache 贡献


def test_dual_missing_failed_but_estimated(tmp_path):
    ad = DshAdapter(rates=RATES, sessions_dir=tmp_path / "none",
                    est_call_cny=0.05)
    with patch("subprocess.run", return_value=_fake_run("无 trailer 无会话")):
        r = ad.run(_pkt(tmp_path))
    assert r.status == "failed" and r.usage_missing is True     # 恢复硬契约
    assert r.cost_cny == 0.05 and r.estimated is True           # 但照估禁记 0


def test_timeout_uses_session_partial(tmp_path):
    import subprocess
    sd = _sessions_for(tmp_path, tmp_path, [_usage(1, 1, 10**13, inp=1000,
                                                   out=500)])
    ad = DshAdapter(rates=RATES, sessions_dir=sd, est_call_cny=0.05)
    with patch("subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd="dsh", timeout=1)):
        r = ad.run(_pkt(tmp_path))
    assert r.status == "timeout"
    assert r.estimated is False                                  # 有会话=真实
    assert r.tokens == {"input_tokens": 1000, "output_tokens": 500}


def test_cache_read_not_in_tokens(tmp_path):
    sd = _sessions_for(tmp_path, tmp_path, [
        _usage(1, 1, 10**13, inp=100, out=50, cache=99999)])
    ad = DshAdapter(rates=RATES, sessions_dir=sd)
    with patch("subprocess.run", return_value=_fake_run("x")):
        r = ad.run(_pkt(tmp_path))
    assert set(r.tokens.keys()) == {"input_tokens", "output_tokens"}
    assert r.cost_cny > 0    # cache 按 hit 价进了 cost(99999×0.5/M≈0.05)
