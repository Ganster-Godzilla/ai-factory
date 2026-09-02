"""T-2026-0903-003 S1:check-complexity 闸判定逻辑(radon_result 注入,不起子进程)。"""
import importlib.util
from pathlib import Path

# 文件名带连字符(check-complexity.py),不能按模块名 import,按路径加载(011-S4 手法)
_SPEC = importlib.util.spec_from_file_location(
    "check_complexity",
    Path(__file__).resolve().parents[2] / "scripts" / "check-complexity.py")
cc_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cc_mod)


def _write_baseline(tmp_path, lines):
    p = tmp_path / "complexity-baseline.txt"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_new_over_threshold_blocked(tmp_path):
    base = _write_baseline(tmp_path, [])
    cur = {("orchestrator/daemon/x.py", "fat"): 20}
    hits = cc_mod.find_violations(tmp_path, base, radon_result=cur)
    assert any("fat" in h and "新增超标" in h for h in hits)


def test_baseline_function_exempt(tmp_path):
    base = _write_baseline(tmp_path, ["orchestrator/daemon/cli.py::main::25"])
    cur = {("orchestrator/daemon/cli.py", "main"): 25}
    assert cc_mod.find_violations(tmp_path, base, radon_result=cur) == []


def test_baseline_function_worsened_blocked(tmp_path):
    base = _write_baseline(tmp_path, ["orchestrator/daemon/cli.py::main::25"])
    cur = {("orchestrator/daemon/cli.py", "main"): 30}
    hits = cc_mod.find_violations(tmp_path, base, radon_result=cur)
    assert any("main" in h and "恶化" in h for h in hits)


def test_baseline_function_improved_passes(tmp_path):
    base = _write_baseline(tmp_path, ["orchestrator/daemon/cli.py::main::25"])
    cur = {("orchestrator/daemon/cli.py", "main"): 15}   # 降到阈值内
    assert cc_mod.find_violations(tmp_path, base, radon_result=cur) == []


def test_at_threshold_not_blocked(tmp_path):
    base = _write_baseline(tmp_path, [])
    cur = {("orchestrator/daemon/x.py", "edge"): 15}   # 恰达阈值,不超
    assert cc_mod.find_violations(tmp_path, base, radon_result=cur) == []


def test_method_qualname_parsed(tmp_path):
    base = _write_baseline(tmp_path, [])
    cur = {("orchestrator/adapters/dsh.py", "DshAdapter.run"): 23}
    hits = cc_mod.find_violations(tmp_path, base, radon_result=cur)
    assert any("DshAdapter.run" in h for h in hits)


def test_missing_baseline_blocks_all_over_threshold(tmp_path):
    # 无基线文件:所有 cc>15 按新增拦
    cur = {("a.py", "f"): 20, ("b.py", "g"): 16}
    hits = cc_mod.find_violations(tmp_path, tmp_path / "nope.txt",
                                  radon_result=cur)
    assert len(hits) == 2
