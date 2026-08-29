"""T-2026-0829-004 明放模式:估算入账 + 双闸 warn-only + 复审提醒。"""
import subprocess
from unittest.mock import patch, MagicMock

from orchestrator.adapters.base import TaskPacket
from orchestrator.adapters.dsh import DshAdapter, USAGE_MISSING_MSG
from orchestrator.daemon.ledger import append_ledger


def _git_repo(tmp_path):
    r = tmp_path / "proj"
    r.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=r, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=r, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=r, check=True)
    (r / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=r, check=True)
    subprocess.run(["git", "commit", "-m", "i"], cwd=r, check=True, capture_output=True)
    return r


def _pkt(tmp_path):
    return TaskPacket(role="dev", prompt="x", workdir=tmp_path, timeout=10)


def _fake_run(stdout="out", rc=0):
    m = MagicMock()
    m.stdout, m.stderr, m.returncode = stdout, "", rc
    return m


def test_dsh_degraded_estimated_cost(tmp_path):
    ad = DshAdapter(est_call_cny=0.05)
    with patch("subprocess.run", return_value=_fake_run("正文无 trailer")):
        r = ad.run(_pkt(tmp_path))
    assert r.status == "done"                      # 按 returncode 推进
    assert r.usage_missing is True
    assert r.cost_cny == 0.05 and r.estimated is True   # 估算入账,禁止记 0
    assert r.tokens == {}


def test_dsh_degraded_failed_rc(tmp_path):
    ad = DshAdapter(est_call_cny=0.05)
    with patch("subprocess.run", return_value=_fake_run("boom", rc=1)):
        r = ad.run(_pkt(tmp_path))
    assert r.status == "failed" and r.usage_missing is True
    assert r.cost_cny == 0.05 and r.estimated is True   # 失败尝试也烧钱,照估


def test_dsh_trailer_exact_cost(tmp_path):
    ad = DshAdapter(est_call_cny=0.05)
    out = '正文\n__DSH_USAGE__ {"input_tokens": 100, "output_tokens": 50, "cost_cny": 0.012}'
    with patch("subprocess.run", return_value=_fake_run(out)):
        r = ad.run(_pkt(tmp_path))
    assert r.cost_cny == 0.012 and r.estimated is False  # 精确值不打估算标
    assert r.usage_missing is False


def test_est_call_default_zero_no_estimate(tmp_path):
    ad = DshAdapter()                              # 缺省不估(向后兼容)
    with patch("subprocess.run", return_value=_fake_run()):
        r = ad.run(_pkt(tmp_path))
    assert r.cost_cny == 0.0 and r.estimated is False


def test_usage_missing_msg_semantics():
    assert "视同失败" not in USAGE_MISSING_MSG
    assert "估算" in USAGE_MISSING_MSG


# ---------- runner 层:入账透传 + 双闸 warn-only ----------

def _cfg_mingfang(on=True):
    return {"budgets": {"ds_daily_cny": 0.01, "mingfang_mode": on,
                        "ds_est_call_cny": 0.05, "k3_week_token_budget": 10**9}}


def _ticket_with_task(pool):
    from orchestrator.daemon.ticket import new_ticket
    t = new_ticket(pool, project="p", summary="明放测试")
    t.state = "p3_running"
    t.tasks = [{"id": "g1", "title": "t", "status": "pending", "attempts": 0,
                "depends_on": [], "acceptance_cmd": None}]
    from orchestrator.daemon.ticket import save_ticket
    save_ticket(pool, t)
    return t


def _fake_adapter():
    from orchestrator.adapters.base import HarnessResult
    ad = MagicMock()
    ad.name = "dsh"
    ad.run.return_value = HarnessResult(
        status="done", output="ok", tokens={}, cost_cny=0.05,
        usage_missing=True, estimated=True)
    return ad


def test_record_cost_writes_estimated(pool, tmp_path):
    from orchestrator.daemon.runner import run_dev_tasks
    from orchestrator.daemon.ledger import _entries
    t = _ticket_with_task(pool)
    run_dev_tasks(pool, t, _fake_adapter(), _git_repo(tmp_path), cfg=_cfg_mingfang())
    rows = [e for e in _entries(pool) if e["resource"] == "deepseek"]
    assert len(rows) == 1
    assert rows[0]["amount"] == 0.05 and rows[0]["estimated"] is True


def test_daily_gate_warn_only(pool, tmp_path):
    from orchestrator.daemon.runner import run_dev_tasks
    from orchestrator.daemon.events import read_events
    t = _ticket_with_task(pool)
    append_ledger(pool, "deepseek", 99.0, "cny", t.id, "dev", "dsh")  # 已超日闸
    out = run_dev_tasks(pool, t, _fake_adapter(), _git_repo(tmp_path), cfg=_cfg_mingfang())
    assert "blocked" not in out                       # 明放:不阻断
    warns = [e for e in read_events(pool, t.id) if e["event"] == "budget_warn"]
    assert any(w.get("gate") == "ds_daily" for w in warns)


def test_daily_gate_hard_when_off(pool, tmp_path):
    from orchestrator.daemon.runner import run_dev_tasks
    t = _ticket_with_task(pool)
    append_ledger(pool, "deepseek", 99.0, "cny", t.id, "dev", "dsh")
    out = run_dev_tasks(pool, t, _fake_adapter(), _git_repo(tmp_path), cfg=_cfg_mingfang(on=False))
    assert "blocked" in out                           # 缺省硬闸,向后兼容


def test_ticket_cap_warn_only(pool, tmp_path):
    from orchestrator.daemon.runner import run_dev_tasks
    from orchestrator.daemon.events import read_events
    from orchestrator.daemon.ticket import load_ticket
    t = _ticket_with_task(pool)
    t_budget = (t.budget or {}).get("token_cap_cny", 10.0)
    append_ledger(pool, "deepseek", t_budget + 1, "cny", t.id, "dev", "dsh")  # 超帽
    run_dev_tasks(pool, t, _fake_adapter(), _git_repo(tmp_path),
                  cfg={"budgets": {"ds_daily_cny": 10**6, "mingfang_mode": True,
                                   "k3_week_token_budget": 10**9}})
    assert load_ticket(pool, t.id).state == "p3_running"   # 不挂起
    warns = [e for e in read_events(pool, t.id) if e["event"] == "budget_warn"]
    assert any(w.get("gate") == "ticket_cap" for w in warns)


def test_ticket_cap_hard_when_off(pool, tmp_path):
    from orchestrator.daemon.runner import run_dev_tasks
    from orchestrator.daemon.ticket import load_ticket
    t = _ticket_with_task(pool)
    t_budget = (t.budget or {}).get("token_cap_cny", 10.0)
    append_ledger(pool, "deepseek", t_budget + 1, "cny", t.id, "dev", "dsh")
    run_dev_tasks(pool, t, _fake_adapter(), _git_repo(tmp_path),
                  cfg={"budgets": {"ds_daily_cny": 10**6,
                                   "k3_week_token_budget": 10**9}})
    assert load_ticket(pool, t.id).state == "suspended"    # 缺省硬帽


def test_mingfang_defaults_off_missing_budgets(pool, tmp_path):
    from orchestrator.daemon.runner import run_dev_tasks
    t = _ticket_with_task(pool)
    append_ledger(pool, "deepseek", 99.0, "cny", t.id, "dev", "dsh")
    out = run_dev_tasks(pool, t, _fake_adapter(), _git_repo(tmp_path),
                        cfg={"budgets": {"ds_daily_cny": 0.01,
                                         "k3_week_token_budget": 10**9}})
    assert "blocked" in out                           # 无 mingfang 键 → 硬闸


# ---------- dashboard 复审提醒 ----------

def test_overview_mingfang_overdue(pool):
    from orchestrator.dashboard.views import overview_data
    cfg = {"budgets": {"k3_week_token_budget": 1, "ds_daily_cny": 30,
                       "mingfang_mode": True, "review_after": "2020-01-01"},
           "gateway": {"url": "http://127.0.0.1:1"}}
    d = overview_data(pool, cfg)
    assert d["mingfang_overdue"] is True


def test_overview_mingfang_not_overdue(pool):
    from orchestrator.dashboard.views import overview_data
    cfg = {"budgets": {"k3_week_token_budget": 1, "ds_daily_cny": 30,
                       "mingfang_mode": True, "review_after": "2099-01-01"},
           "gateway": {"url": "http://127.0.0.1:1"}}
    d = overview_data(pool, cfg)
    assert d["mingfang_overdue"] is False and d["mingfang_mode"] is True


def test_index_mingfang_banner(pool):
    from orchestrator.dashboard.app import create_app
    cfg = {"budgets": {"k3_week_token_budget": 1, "ds_daily_cny": 30,
                       "mingfang_mode": True, "review_after": "2020-01-01"},
           "gateway": {"url": "http://127.0.0.1:1"}}
    app = create_app(pool, cfg)
    app.config["TESTING"] = True
    html = app.test_client().get("/").get_data(as_text=True)
    assert "明放" in html and "2020-01-01" in html
