import yaml
from pathlib import Path
from orchestrator.daemon.cli import main


def _cfg(tmp_path, monkeypatch):
    (tmp_path / "orchestrator.yaml").write_text(
        yaml.safe_dump({"pool": "pool", "projects": {}, "thresholds": {"concurrent_max": 2}}),
        encoding="utf-8", newline="\n")
    monkeypatch.chdir(tmp_path)


def test_new_list_approve(tmp_path, monkeypatch, capsys):
    _cfg(tmp_path, monkeypatch)
    assert main(["new", "quant-lab", "加缓存"]) == 0
    out = capsys.readouterr().out
    tid = [w for w in out.split() if w.startswith("T-")][0]

    assert main(["advance", tid, ".", "--fake"]) == 0          # draft→p0_proposed? 否:draft 是 idle
    # draft 需要先由 pm 提交:用 advance 让 pm 干活?draft 不在 WORK_STATES。
    # 设计决策:orc new 后直接 pm 提交走 approve 前需要 p0_proposed。
    # 简化:new 之后提供 submit 动作由 advance 处理 draft 状态。
    assert main(["approve", tid, "--as", "pm"]) == 0            # pm 提交 draft→p0_proposed
    assert main(["approve", tid]) == 0                          # boss:p0→p1
    assert main(["advance", tid, ".", "--fake"]) == 0           # pm 写 PRD→p1_proposed
    assert main(["approve", tid]) == 0                          # boss:p1→p2
    assert main(["advance", tid, ".", "--fake"]) == 0           # architect→等审批
    assert main(["approve", tid]) == 0                          # boss:p2_approved
    assert main(["advance", tid, ".", "--fake"]) == 0           # auto→p3_running? auto 只迁移系统态
    assert main(["advance", tid, ".", "--fake"]) == 0           # dev→p4
    assert main(["advance", tid, ".", "--fake"]) == 0           # qa→p5_ready
    assert main(["approve", tid]) == 0                          # boss:p5_releasing
    assert main(["advance", tid, ".", "--fake"]) == 0           # release→monitoring
    assert main(["advance", tid, ".", "--fake"]) == 0           # sre→done
    assert main(["show", tid]) == 0
    out = capsys.readouterr().out
    assert "done" in out
    assert "state_changed" in out
