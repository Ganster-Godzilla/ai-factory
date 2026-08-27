import pytest

from orchestrator.dashboard.app import create_app
from orchestrator.dashboard.views import overview_data
from orchestrator.daemon.events import append_event
from orchestrator.daemon.ledger import append_ledger
from orchestrator.daemon.statemachine import transition
from orchestrator.daemon.ticket import new_ticket


@pytest.fixture
def client(pool):
    cfg = {"budgets": {"k3_week_token_budget": 2000000, "ds_daily_cny": 30},
           "gateway": {"url": "http://127.0.0.1:1"}}   # 不可达 → 回退本地台账
    t = new_ticket(pool, project="p", summary="测试工单")
    transition(pool, t, "p0_proposed", actor="pm")
    app = create_app(pool, cfg)
    app.config["TESTING"] = True
    return app.test_client()


def test_index_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "总览" in html
    assert "测试工单" not in html      # 总览不列工单明细(那是审批中心)
    assert "待审批" in html


def _cfg():
    return {"budgets": {"k3_week_token_budget": 2000000, "ds_daily_cny": 30},
            "gateway": {"url": "http://127.0.0.1:1"}}   # 不可达 → 本地台账


def test_overview_data_counts(pool):
    t1 = new_ticket(pool, project="p", summary="待审批单")
    transition(pool, t1, "p0_proposed", actor="pm")          # 待审批(APPROVALS 键)
    t2 = new_ticket(pool, project="p", summary="运行中单")
    transition(pool, t2, "p0_proposed", actor="pm")
    transition(pool, t2, "p1_drafting", actor="boss")
    transition(pool, t2, "p1_proposed", actor="pm")
    transition(pool, t2, "p2_designing", actor="boss")
    transition(pool, t2, "p2_approved", actor="boss")
    transition(pool, t2, "p3_queued", actor="system")
    transition(pool, t2, "p3_running", actor="system")       # 运行中
    t3 = new_ticket(pool, project="p", summary="挂起单")
    transition(pool, t3, "p0_proposed", actor="pm")
    transition(pool, t3, "p1_drafting", actor="boss")
    from orchestrator.daemon.statemachine import suspend
    suspend(pool, t3, actor="boss", reason="人工挂起")        # suspended

    append_ledger(pool, "k3", 12345, "tokens", t2.id, "dev", "k3")
    append_ledger(pool, "deepseek", 1.5, "cny", t2.id, "dev", "deepseek")

    d = overview_data(pool, _cfg())
    assert d["k3_used"] == 12345
    assert d["k3_budget"] == 2000000
    assert d["k3_pct"] == round(12345 / 2000000 * 100, 1)
    assert d["ds_today"] == 1.5
    assert d["ds_month"] == 1.5
    assert d["pending_approval"] == 1
    assert d["running"] == 1
    assert d["suspended"] == 1
    # 今日事件按工单分组计数:t1/t2/t3 均有事件,gateway 回退还会写 system
    assert d["today_events"][t1.id] >= 2      # created + state_changed
    assert d["today_events"][t2.id] >= 8
    assert d["today_events"][t3.id] >= 3


def test_overview_data_empty_pool(pool):
    d = overview_data(pool, _cfg())
    assert d["k3_used"] == 0
    assert d["k3_pct"] == 0.0
    assert d["ds_today"] == 0.0
    assert d["ds_month"] == 0.0
    assert d["pending_approval"] == 0
    assert d["running"] == 0
    assert d["suspended"] == 0
    # 空池也有 gateway 回退留痕事件(system)
    assert isinstance(d["today_events"], dict)


def test_overview_data_events_grouping(pool):
    t = new_ticket(pool, project="p", summary="事件单")
    append_event(pool, t.id, "pm", "note", msg="x")
    append_event(pool, t.id, "pm", "note", msg="y")
    d = overview_data(pool, _cfg())
    assert d["today_events"][t.id] == 3       # created + 2 条 note


def test_index_shows_percent_and_currency(client, pool):
    append_ledger(pool, "k3", 1000000, "tokens", "T-x", "dev", "k3")
    append_ledger(pool, "deepseek", 2.5, "cny", "T-x", "dev", "deepseek")
    r = client.get("/")
    html = r.get_data(as_text=True)
    assert "50.0%" in html                     # 1000000 / 2000000
    assert "2.5" in html                       # DS 今日现金
    assert "sk-" not in html                   # 页面不显示任何 key 信息
