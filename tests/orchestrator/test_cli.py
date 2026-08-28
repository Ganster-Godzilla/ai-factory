import yaml
from pathlib import Path
from orchestrator.daemon.cli import main
from orchestrator.daemon.ticket import load_ticket


def _cfg(tmp_path, monkeypatch):
    (tmp_path / "orchestrator.yaml").write_text(
        yaml.safe_dump({"pool": "pool", "projects": {}, "thresholds": {"concurrent_max": 2}}),
        encoding="utf-8", newline="\n")
    monkeypatch.chdir(tmp_path)


def _new_ticket(tmp_path, capsys, summary="加缓存"):
    assert main(["new", "quant-lab", summary]) == 0
    out = capsys.readouterr().out
    return [w for w in out.split() if w.startswith("T-")][0]


def _ticket_at_p1_proposed(tmp_path, monkeypatch, capsys, summary="redo-me"):
    """CLI 走完 draft→p0→p1_drafting→pm 交 PRD(p1_proposed)的审批链。"""
    _cfg(tmp_path, monkeypatch)
    tid = _new_ticket(tmp_path, capsys, summary)
    assert main(["approve", tid, "--as", "pm"]) == 0   # pm 提交 draft→p0_proposed
    assert main(["approve", tid]) == 0                 # boss:p0→p1_drafting
    assert main(["advance", tid, ".", "--fake"]) == 0  # pm 写 PRD→p1_proposed
    return tid


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


def test_dashboard_smoke(tmp_path, monkeypatch):
    """dashboard 命令可导入并创建 app;拦截 Flask.run,不真起服务。"""
    _cfg(tmp_path, monkeypatch)
    from flask import Flask
    calls = {}

    def fake_run(self, **kwargs):
        calls.update(kwargs)

    monkeypatch.setattr(Flask, "run", fake_run)
    assert main(["dashboard"]) == 0
    assert calls == {"host": "127.0.0.1", "port": 8321, "debug": False}

    calls.clear()
    assert main(["dashboard", "--port", "9000", "--host", "0.0.0.0"]) == 0
    assert calls["port"] == 9000 and calls["host"] == "0.0.0.0"


# ---- D2:orc reject --redo 驳回回炉 ----

def test_reject_redo_returns_to_p1_drafting(tmp_path, monkeypatch, capsys):
    tid = _ticket_at_p1_proposed(tmp_path, monkeypatch, capsys)
    assert main(["reject", tid, "--redo"]) == 0
    out = capsys.readouterr().out
    assert "p1_drafting" in out and "round=1" in out
    assert load_ticket(tmp_path / "pool", tid).state == "p1_drafting"
    # 回炉后再走一轮:PM 重交 → 二次驳回,轮次累加
    assert main(["advance", tid, ".", "--fake"]) == 0
    assert main(["reject", tid, "--redo"]) == 0
    assert "round=2" in capsys.readouterr().out


def test_reject_redo_only_from_p1_proposed(tmp_path, monkeypatch, capsys):
    _cfg(tmp_path, monkeypatch)
    tid = _new_ticket(tmp_path, capsys, "fresh")
    assert main(["reject", tid, "--redo"]) == 1          # draft 态 --redo 非法
    assert "error" in capsys.readouterr().err
    assert load_ticket(tmp_path / "pool", tid).state == "draft"  # 工单未被误动


def test_reject_default_still_closes(tmp_path, monkeypatch, capsys):
    tid = _ticket_at_p1_proposed(tmp_path, monkeypatch, capsys)
    assert main(["reject", tid]) == 0                    # 缺省行为不变:关单
    assert "closed" in capsys.readouterr().out
    assert load_ticket(tmp_path / "pool", tid).state == "closed"
