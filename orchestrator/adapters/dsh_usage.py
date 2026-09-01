"""dsh 会话文件 usage 解析(T-2026-0829-002):真实计量补台账。

dsh 0.1.1-rc.2 把会话写成多帧 zstd 追加日志:
~/.dsh/sessions/<转义workdir>/<session-id>/session.jsonl.zstd
usage 在 assistant/chunk 的 data.chunk(type="usage"),每 (turn,step) 一条。
注意:ZstdDecompressor().decompress() 只读首帧(实证 1MB 文件只出 199 字符),
必须 stream_reader 全帧读;断帧(超时掐断)按魔数切分逐段抢救。
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path

import zstandard

DEFAULT_SESSIONS_DIR = Path.home() / ".dsh" / "sessions"
_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def _norm_cwd(p: str) -> str:
    """cwd 归一化:反斜杠转正、去尾斜杠、小写(Windows 大小写/斜杠变体免疫)。"""
    return str(p).replace("\\", "/").rstrip("/").lower()


def _escape_candidates(workdir: str) -> list[str]:
    """快路径目录名变体:观察规则 `--` 包裹 + 非字母数字(点号除外)转 `-`
    ——实证 worktree 目录保留点号(--d-...ai-factory-.orc-worktrees-...--);
    驱动器字母大小写两种都存在,都生成。规则漂移时由 cwd 头兜底。"""
    w = str(workdir)
    names = set()
    for variant in {w, w[0].upper() + w[1:], w[0].lower() + w[1:]}:
        names.add("--" + re.sub(r"[^A-Za-z0-9.]+", "-", variant).strip("-") + "--")
    return sorted(names)


def _read_frames(path: Path) -> str | None:
    """全帧流式解压;断帧(超时掐断写出垃圾尾巴)按魔数切分逐段抢救;
    任何不可恢复异常 → None。"""
    try:
        raw = Path(path).read_bytes()
        try:
            return zstandard.ZstdDecompressor().stream_reader(
                io.BytesIO(raw)).read().decode("utf-8", "replace")
        except zstandard.ZstdError:
            # 逐段抢救:完整帧留下,损坏尾段丢弃(评审:断帧不该杀掉全部有效帧)
            parts = raw.split(_ZSTD_MAGIC)
            out = []
            for seg in parts[1:]:
                try:
                    out.append(zstandard.ZstdDecompressor().stream_reader(
                        io.BytesIO(_ZSTD_MAGIC + seg)).read())
                except zstandard.ZstdError:
                    break   # 首个坏段之后的不要(顺序语义)
            return b"".join(out).decode("utf-8", "replace") if out else None
    except Exception:   # noqa: BLE001 — 解析失败=会话源不可用,不炸 run
        return None


def _session_cwd(path: Path) -> str | None:
    """读 session 头 cwd(定位兜底)。stream 读前缀取首行——
    首帧未声明长度且 >64KB 时 decompress() 会炸(实证),这里免疫。"""
    try:
        reader = zstandard.ZstdDecompressor().stream_reader(
            io.BytesIO(Path(path).read_bytes()))
        prefix = reader.read(65536).decode("utf-8", "replace")
        first = prefix.split("\n", 1)[0]
        e = json.loads(first)
        return e.get("cwd") if e.get("type") == "session" else None
    except Exception:   # noqa: BLE001
        return None


def find_session_file(sessions_dir: Path, workdir, since_ms: float) -> Path | None:
    """定位 workdir 对应的会话文件:转义快路径(cwd 头复核防碰撞)→ cwd 头兜底;
    since_ms 预筛 mtime 过旧的候选;多候选取最新。"""
    sessions_dir = Path(sessions_dir)
    if not sessions_dir.exists():
        return None
    wd = _norm_cwd(workdir)
    cands: list[Path] = []
    for name in _escape_candidates(str(workdir)):
        d = sessions_dir / name
        if d.is_dir():
            for f in d.glob("*/session.jsonl.zstd"):
                cwd = _session_cwd(f)   # 快路径也复核:转义碰撞会跨项目错账
                if cwd is not None and _norm_cwd(cwd) != wd:
                    continue
                cands.append(f)
    if not cands:   # 兜底:按 session 头 cwd 精确匹配(规则漂移免疫)
        for f in sessions_dir.glob("*/*/session.jsonl.zstd"):
            cwd = _session_cwd(f)
            if cwd is not None and _norm_cwd(cwd) == wd:
                cands.append(f)
    if not cands:
        return None
    fresh = []
    for p in cands:
        try:
            fresh.append((p.stat().st_mtime, p))
        except FileNotFoundError:
            continue   # TOCTOU:glob 与 stat 之间被清理
    if not fresh:
        return None
    # since_ms 只做偏好排序(新文件优先),不做硬过滤——记录内 time 才是权威过滤器;
    # mtime 早于 run 开始不代表没有新记录(续写会话/测试场景),硬过滤会误杀
    return max(fresh, key=lambda x: x[0])[1]


def _to_int(v) -> int:
    """token 值容错:int/float 直转;数字字符串强转;其余 → None(抛 TypeError)。"""
    if isinstance(v, bool):
        raise TypeError("bool 不是 token 数")
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    raise TypeError(f"非法 token 值: {v!r}")


def _collect_per_step(text: str, since_ms: float) -> dict[tuple, dict]:
    """汇总 since_ms 以来的 usage:按 (turn,step) 去重取末条,保留时间戳供分时计价。"""
    per_step: dict[tuple, dict] = {}
    for line in text.splitlines():
        if '"usage"' not in line:
            continue
        try:
            e = json.loads(line)
            if e.get("type") != "assistant/chunk":
                continue
            d = e["data"]
            chunk = d.get("chunk")
            if not isinstance(chunk, dict) or chunk.get("type") != "usage":
                continue
            t = e.get("time", 0)
            t = float(t) if not isinstance(t, str) else float(t or 0)
            if t < since_ms:
                continue
            u = chunk.get("usage")
            if not isinstance(u, dict):
                continue
            per_step[(d["turn"], d["step"])] = {
                "time": t,
                "input": _to_int(u.get("inputTokens") or 0),
                "output": _to_int(u.get("outputTokens") or 0),
                "cache_read": _to_int(u.get("cacheReadTokens") or 0),
            }
        except (json.JSONDecodeError, KeyError, TypeError, ValueError,
                AttributeError):
            continue
    return per_step


def read_session_usage(path: Path, since_ms: float) -> dict | None:
    """汇总 since_ms 以来的 usage:按 (turn,step) 去重取末条。
    坏行跳过;全零汇总(键名漂移,如 GLM promptTokens)→ None(落双缺);
    解析失败 → None(调用方按"会话源不可用"处理)。"""
    if path is None:
        return None
    text = _read_frames(Path(path))
    if text is None:
        return None
    per_step = _collect_per_step(text, since_ms)
    if not per_step:
        return None
    total = {
        "input": sum(u["input"] for u in per_step.values()),
        "output": sum(u["output"] for u in per_step.values()),
        "cache_read": sum(u["cache_read"] for u in per_step.values()),
    }
    # 全零=键名漂移(GLM 同构假设破产),按无会话源落双缺,不许当"真实 ¥0 账"
    return None if total["input"] + total["output"] + total["cache_read"] == 0 else total


def rates_for(model: str | None, rates: dict | None) -> dict | None:
    """模型名→费率表:精确命中 → provider 前缀(deepseek-*/glm-*)→ 缺省 deepseek。
    rates 缺失或 provider 无条目 → None(调用方走 est 兜底,禁记 ¥0 真账)。"""
    if not rates:
        return None
    m = (model or "").strip()
    if m in rates:
        return rates[m]
    for prefix in ("deepseek", "glm"):
        if m.lower().startswith(prefix) and prefix in rates:
            return rates[prefix]
    return rates.get("deepseek")


def estimate_cost(rate: dict, usage: dict) -> float:
    """按费率行计算现金:cacheRead 走 hit 价(真实计费项,不进 tokens 字段)。
    费率值容错:None/非法按 0(配置残段不炸 run)。"""
    def _num(k):
        v = (rate or {}).get(k)
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0
    cost = (usage.get("input", 0) * _num("input_per_m")
            + usage.get("cache_read", 0) * _num("cache_hit_per_m")
            + usage.get("output", 0) * _num("output_per_m")) / 1e6
    return round(cost, 4)


# ---------- 峰谷分时计价(T-2026-0901-003) ----------

def _rate_row_at(ms: float, rate: dict) -> dict:
    """按时间戳取峰/谷费率行:命中 peak_hours(本地小时,[start,end) 区间)
    用峰时价(顶层),否则用 off_peak 子表;off_peak 缺省回落顶层(平价)。"""
    import datetime
    off = (rate or {}).get("off_peak")
    if not isinstance(off, dict):
        return rate or {}
    hours = rate.get("peak_hours") or []
    h = datetime.datetime.fromtimestamp(ms / 1000).hour
    for span in hours:
        try:
            start, end = int(span[0]), int(span[1])
        except (TypeError, ValueError, IndexError):
            continue
        if start <= h < end:
            return rate
    return {**rate, **off}


def price_session_usage(path: Path, since_ms: float, rate: dict) -> float | None:
    """按步分时计价:每条 usage 按其时间戳取峰/谷价求和。
    rate 无 off_peak → None(调用方回落 estimate_cost 平价);
    会话源不可用/无 usage → None。"""
    if path is None or not isinstance(rate, dict) or not rate.get("off_peak"):
        return None
    text = _read_frames(Path(path))
    if text is None:
        return None
    per_step = _collect_per_step(text, since_ms)
    if not per_step:
        return None

    def _num(row, k):
        try:
            return float((row or {}).get(k) or 0)
        except (TypeError, ValueError):
            return 0.0

    cost = 0.0
    for u in per_step.values():
        row = _rate_row_at(u["time"], rate)
        cost += (u["input"] * _num(row, "input_per_m")
                 + u["cache_read"] * _num(row, "cache_hit_per_m")
                 + u["output"] * _num(row, "output_per_m")) / 1e6
    return round(cost, 4)
