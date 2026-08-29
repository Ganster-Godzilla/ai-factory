"""dsh 会话文件 usage 解析(T-2026-0829-002):真实计量补台账。

dsh 0.1.1-rc.2 把会话写成多帧 zstd 追加日志:
~/.dsh/sessions/<转义workdir>/<session-id>/session.jsonl.zstd
usage 在 assistant/chunk 的 data.chunk(type="usage"),每 (turn,step) 一条。
注意:ZstdDecompressor().decompress() 只读首帧(实证 1MB 文件只出 199 字符),
必须 stream_reader 全帧读。
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path

import zstandard

DEFAULT_SESSIONS_DIR = Path.home() / ".dsh" / "sessions"


def _norm_cwd(p: str) -> str:
    """cwd 归一化:反斜杠转正、去尾斜杠、小写(Windows 大小写/斜杠变体免疫)。"""
    return str(p).replace("\\", "/").rstrip("/").lower()


def _escape_candidates(workdir: str) -> list[str]:
    """快路径目录名变体:观察规则是 `--` 包裹 + 非字母数字转 `-`;
    驱动器字母大小写两种实证都存在,都生成。规则漂移时由 cwd 头兜底。"""
    w = str(workdir)
    names = set()
    for variant in {w, w[0].upper() + w[1:], w[0].lower() + w[1:]}:
        names.add("--" + re.sub(r"[^A-Za-z0-9]+", "-", variant).strip("-") + "--")
    return sorted(names)


def _read_frames(path: Path) -> str | None:
    """全帧流式解压;任何异常(损坏/权限/非 zstd)→ None。"""
    try:
        raw = zstandard.ZstdDecompressor().stream_reader(
            io.BytesIO(path.read_bytes())).read()
        return raw.decode("utf-8", "replace")
    except Exception:   # noqa: BLE001 — 解析失败=会话源不可用,不炸 run
        return None


def _session_cwd(path: Path) -> str | None:
    """只读首帧 session 头拿 cwd(定位兜底用,便宜)。"""
    try:
        dctx = zstandard.ZstdDecompressor()
        first = dctx.decompress(path.read_bytes(),
                                max_output_size=65536).decode("utf-8", "replace")
        e = json.loads(first.splitlines()[0])
        return e.get("cwd") if e.get("type") == "session" else None
    except Exception:   # noqa: BLE001
        return None


def find_session_file(sessions_dir: Path, workdir, since_ms: float) -> Path | None:
    """定位 workdir 对应的会话文件:转义快路径 → cwd 头兜底;多候选取最新。"""
    sessions_dir = Path(sessions_dir)
    if not sessions_dir.exists():
        return None
    wd = _norm_cwd(workdir)
    cands: list[Path] = []
    for name in _escape_candidates(str(workdir)):
        d = sessions_dir / name
        if d.is_dir():
            cands.extend(d.glob("*/session.jsonl.zstd"))
    if not cands:   # 兜底:按 session 头 cwd 精确匹配
        for f in sessions_dir.glob("*/*/session.jsonl.zstd"):
            cwd = _session_cwd(f)
            if cwd is not None and _norm_cwd(cwd) == wd:
                cands.append(f)
    if not cands:
        return None
    return max(cands, key=lambda p: p.stat().st_mtime)


def read_session_usage(path: Path, since_ms: float) -> dict | None:
    """汇总 since_ms 以来的 usage:按 (turn,step) 去重取末条。
    无命中/解析失败 → None(调用方按"会话源不可用"处理)。"""
    text = _read_frames(Path(path))
    if text is None:
        return None
    per_step: dict[tuple, dict] = {}
    for line in text.splitlines():
        if '"usage"' not in line:
            continue
        try:
            e = json.loads(line)
            if e.get("type") != "assistant/chunk":
                continue
            d = e["data"]
            if d["chunk"].get("type") != "usage" or e.get("time", 0) < since_ms:
                continue
            per_step[(d["turn"], d["step"])] = d["chunk"]["usage"]
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    if not per_step:
        return None
    return {
        "input": sum(u.get("inputTokens") or 0 for u in per_step.values()),
        "output": sum(u.get("outputTokens") or 0 for u in per_step.values()),
        "cache_read": sum(u.get("cacheReadTokens") or 0 for u in per_step.values()),
    }


def estimate_cost(rates: dict, provider: str, usage: dict) -> float:
    """按费率表估算现金:cacheRead 走 hit 价(真实计费项,不进 tokens 字段)。"""
    r = (rates or {}).get(provider) or {}
    cost = (usage.get("input", 0) * r.get("input_per_m", 0)
            + usage.get("cache_read", 0) * r.get("cache_hit_per_m", 0)
            + usage.get("output", 0) * r.get("output_per_m", 0)) / 1e6
    return round(cost, 4)
