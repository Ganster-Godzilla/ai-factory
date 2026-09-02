#!/usr/bin/env python
"""常设复杂度闸(T-2026-0903-003):radon 圈复杂度,只拦增量/恶化,豁免存量基线。

合 main 前与 check-pool-load 同跑:python scripts/check-complexity.py
退出码:0=全豁免/无超标;1=有命中(新增超标 或 基线函数恶化);2=radon 不可用(不静默放行)。

基线 scripts/complexity-baseline.txt:一行 `rel_path::qualname::cc`(`#` 注释/空行跳过),
冻结现状超标函数;基线内不拦,但 cc 升高仍拦(恶化),基线外新增 cc>THRESHOLD 必拦。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

THRESHOLD = 15          # cc > 15(C 级以上)即候选拦截
SCAN_DIRS = ("orchestrator", "plugin", "scripts")
BASELINE = Path(__file__).resolve().parent / "complexity-baseline.txt"
ROOT = Path(__file__).resolve().parent.parent


def _run_radon(root: Path) -> dict:
    """radon cc --json → {(rel_path, qualname): cc};失败抛 RuntimeError。"""
    cmd = [sys.executable, "-m", "radon", "cc", *SCAN_DIRS, "--json"]
    try:
        r = subprocess.run(cmd, cwd=root, capture_output=True, text=True,
                           timeout=300)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"radon 调用失败: {e}") from e
    if r.returncode != 0:
        raise RuntimeError(f"radon 退出非零: {r.stderr.strip()[:300]}")
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"radon 输出解析失败: {e}") from e
    out = {}
    for path, entries in data.items():
        rel = path.replace("\\", "/")
        for e in entries:
            qual = f"{e['classname']}.{e['name']}" if e.get("classname") else e["name"]
            out[(rel, qual)] = int(e["complexity"])
    return out


def _load_baseline(path: Path) -> dict:
    """基线文件 → {(rel, qualname): cc};不存在 → 空(全部按新增拦)。"""
    if not path.is_file():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rel, qual, cc = line.rsplit("::", 2)
        out[(rel.strip(), qual.strip())] = int(cc.strip())
    return out


def find_violations(root: Path, baseline_path: Path,
                    radon_result: dict | None = None) -> list[str]:
    """命中清单:cc>THRESHOLD 且(不在基线 或 cc>基线)。radon_result 可注入(测试)。"""
    current = radon_result if radon_result is not None else _run_radon(root)
    baseline = _load_baseline(baseline_path)
    hits = []
    for (rel, qual), cc in sorted(current.items()):
        if cc <= THRESHOLD:
            continue
        base_cc = baseline.get((rel, qual))
        if base_cc is None:
            hits.append(f"{rel}::{qual} cc={cc} (新增超标,基线外)")
        elif cc > base_cc:
            hits.append(f"{rel}::{qual} cc={cc} (基线 {base_cc} → 恶化)")
    return hits


def main(argv: list[str] | None = None) -> int:
    root = ROOT
    try:
        hits = find_violations(root, BASELINE)
    except RuntimeError as e:
        print(f"check-complexity 需要 radon: pip install radon\n({e})",
              file=sys.stderr)
        return 2
    if hits:
        print("check-complexity: 复杂度超标(增量/恶化拦截):", file=sys.stderr)
        for h in hits:
            print(f"  {h}", file=sys.stderr)
        return 1
    print(f"check-complexity: PASS(阈值 cc>{THRESHOLD},基线豁免生效)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
