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


@pytest.fixture
def pool_client(pool):
    app = create_app(pool, _cfg())
    app.config["TESTING"] = True
    return pool, app.test_client()


def test_approvals_groups(client):
    r = client.get("/approvals")
    assert r.status_code == 200
    assert "P0 提案" in r.get_data(as_text=True)


def test_approve_p0_via_post(pool_client):
    pool, client = pool_client
    from orchestrator.daemon.ticket import load_ticket, new_ticket
    from orchestrator.daemon.statemachine import transition
    t = new_ticket(pool, project="p", summary="x")
    transition(pool, t, "p0_proposed", actor="pm")
    r = client.post(f"/approve/{t.id}")
    assert r.status_code == 302
    assert load_ticket(pool, t.id).state == "p1_drafting"
    from orchestrator.daemon.events import read_events
    assert read_events(pool, t.id)[-1]["actor"] == "boss"


def test_probe_draft_adoptable(pool_client):
    pool, client = pool_client
    from orchestrator.daemon.ticket import load_ticket, new_ticket
    t = new_ticket(pool, project="p", summary="测试缺口:payments", created_by="probe")
    r = client.post(f"/approve/{t.id}")
    assert r.status_code == 302
    assert load_ticket(pool, t.id).state == "p0_proposed"


def test_reject_p0_via_post(pool_client):
    pool, client = pool_client
    from orchestrator.daemon.ticket import load_ticket, new_ticket
    from orchestrator.daemon.statemachine import transition
    t = new_ticket(pool, project="p", summary="x")
    transition(pool, t, "p0_proposed", actor="pm")
    r = client.post(f"/reject/{t.id}")
    assert r.status_code == 302
    assert load_ticket(pool, t.id).state == "closed"


def test_suspend_resume_via_post(pool_client):
    pool, client = pool_client
    from orchestrator.daemon.ticket import load_ticket, new_ticket
    from orchestrator.daemon.statemachine import suspend, transition
    t = new_ticket(pool, project="p", summary="x")
    transition(pool, t, "p0_proposed", actor="pm")
    transition(pool, t, "p1_drafting", actor="boss")
    suspend(pool, t, actor="boss", reason="人工挂起")
    r = client.post(f"/resume/{t.id}")
    assert r.status_code == 302
    assert load_ticket(pool, t.id).state == "p1_drafting"


def test_approvals_groups_p1(pool_client):
    pool, client = pool_client
    from orchestrator.daemon.ticket import new_ticket
    from orchestrator.daemon.statemachine import transition
    t = new_ticket(pool, project="p", summary="P1 需求单")
    transition(pool, t, "p0_proposed", actor="pm")
    transition(pool, t, "p1_drafting", actor="boss")
    transition(pool, t, "p1_proposed", actor="pm")
    r = client.get("/approvals")
    html = r.get_data(as_text=True)
    assert "P1 需求" in html
    assert "P1 需求单" in html                     # p1_proposed 工单出现在该组


def test_reject_p2_back_to_drafting(pool_client):
    pool, client = pool_client
    from orchestrator.daemon.ticket import load_ticket, new_ticket
    from orchestrator.daemon.statemachine import transition
    t = new_ticket(pool, project="p", summary="x")
    transition(pool, t, "p0_proposed", actor="pm")
    transition(pool, t, "p1_drafting", actor="boss")
    transition(pool, t, "p1_proposed", actor="pm")
    transition(pool, t, "p2_designing", actor="boss")
    r = client.post(f"/reject/{t.id}")
    assert r.status_code == 302
    assert load_ticket(pool, t.id).state == "p1_drafting"   # 打回重做,不关闭


def test_approve_illegal_transition_not_500(pool_client):
    pool, client = pool_client
    from orchestrator.daemon.ticket import new_ticket
    t = new_ticket(pool, project="p", summary="x")   # draft(非探针)不可 approve
    r = client.post(f"/approve/{t.id}")
    assert r.status_code == 409
    assert r.status_code < 500


def test_index_shows_percent_and_currency(client, pool):
    append_ledger(pool, "k3", 1000000, "tokens", "T-x", "dev", "k3")
    append_ledger(pool, "deepseek", 2.5, "cny", "T-x", "dev", "deepseek")
    r = client.get("/")
    html = r.get_data(as_text=True)
    assert "50.0%" in html                     # 1000000 / 2000000
    assert "2.5" in html                       # DS 今日现金
    assert "sk-" not in html                   # 页面不显示任何 key 信息


def test_ticket_detail(pool_client):
    pool, client = pool_client
    from orchestrator.daemon.ticket import new_ticket
    from orchestrator.daemon.statemachine import transition
    t = new_ticket(pool, project="quant-lab", summary="详情页测试")
    transition(pool, t, "p0_proposed", actor="pm")
    r = client.get(f"/ticket/{t.id}")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "详情页测试" in html and "quant-lab" in html
    assert "state_changed" in html   # 事件流


def test_ticket_detail_404(pool_client):
    pool, client = pool_client
    r = client.get("/ticket/T-2099-0101-999")
    assert r.status_code == 404


def test_ticket_detail_traversal_id_404(pool_client, tmp_path):
    pool, client = pool_client
    # 池外同名 yaml 存在时,旧实现会拼路径加载渲染(遍历洞);
    # 现 ticket_detail 走 load_ticket,id 校验显式拦截 → 404
    outside = tmp_path / "evil.yaml"
    outside.write_text(
        "id: T-2099-0101-001\ntype: feature\nproject: x\nstate: draft\nowner_role: pm\n",
        encoding="utf-8", newline="\n")
    r = client.get("/ticket/..%5C..%5Cevil")
    assert r.status_code == 404


def test_approve_missing_ticket_404(pool_client):
    pool, client = pool_client
    r = client.post("/approve/T-2099-0101-999")
    assert r.status_code == 404


def test_reject_missing_ticket_404(pool_client):
    pool, client = pool_client
    r = client.post("/reject/T-2099-0101-999")
    assert r.status_code == 404


def test_resume_missing_ticket_404(pool_client):
    pool, client = pool_client
    r = client.post("/resume/T-2099-0101-999")
    assert r.status_code == 404


def test_ticket_detail_shows_tasks_cost_artifacts(pool_client):
    pool, client = pool_client
    from orchestrator.daemon.ticket import load_ticket, new_ticket, save_ticket
    t = new_ticket(pool, project="quant-lab", summary="全字段单")
    t.tasks = [{"id": "task-1", "title": "写测试", "status": "done",
                "attempts": 2, "worktree": ".orc-worktrees/task-1"}]
    t.artifacts = {"p0": "docs/p0.md", "design": "docs/design.md"}
    save_ticket(pool, t)
    append_ledger(pool, "deepseek", 3.25, "cny", t.id, "dev", "deepseek")
    r = client.get(f"/ticket/{t.id}")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "task-1" in html and "done" in html
    assert ".orc-worktrees/task-1" in html
    assert "3.25" in html                      # ds_ticket_cost
    assert "docs/p0.md" in html                # 产物指针


def test_approvals_link_to_detail(pool_client):
    pool, client = pool_client
    from orchestrator.daemon.ticket import new_ticket
    from orchestrator.daemon.statemachine import transition
    t = new_ticket(pool, project="p", summary="带链接的单")
    transition(pool, t, "p0_proposed", actor="pm")
    r = client.get("/approvals")
    html = r.get_data(as_text=True)
    assert f"/ticket/{t.id}" in html


def _p0_ticket(pool):
    from orchestrator.daemon.ticket import new_ticket
    from orchestrator.daemon.statemachine import transition
    t = new_ticket(pool, project="p", summary="CSRF 测试单")
    transition(pool, t, "p0_proposed", actor="pm")
    return t


def test_approve_rejects_foreign_origin(pool_client):
    # 终审 F2:本地 CSRF 防护 —— 恶意 Origin 的 POST 一律 403,工单状态不变
    pool, client = pool_client
    from orchestrator.daemon.ticket import load_ticket
    t = _p0_ticket(pool)
    r = client.post(f"/approve/{t.id}",
                    headers={"Origin": "http://evil.com"})
    assert r.status_code == 403
    assert load_ticket(pool, t.id).state == "p0_proposed"


def test_approve_allows_loopback_origin(pool_client):
    # 终审 F2:127.0.0.1/localhost(含任意端口)的 Origin 放行
    pool, client = pool_client
    from orchestrator.daemon.ticket import load_ticket
    t = _p0_ticket(pool)
    r = client.post(f"/approve/{t.id}",
                    headers={"Origin": "http://127.0.0.1:8321"})
    assert r.status_code == 302
    assert load_ticket(pool, t.id).state == "p1_drafting"


def test_approve_without_origin_allowed(pool_client):
    # 终审 F2:curl/CLI 无 Origin/Referer → 放行(既有行为)
    pool, client = pool_client
    from orchestrator.daemon.ticket import load_ticket
    t = _p0_ticket(pool)
    r = client.post(f"/approve/{t.id}")
    assert r.status_code == 302
    assert load_ticket(pool, t.id).state == "p1_drafting"


def _p2_designing_ticket(pool, owner_role):
    from orchestrator.daemon.ticket import new_ticket, save_ticket
    from orchestrator.daemon.statemachine import transition
    t = new_ticket(pool, project="p", summary="设计中单")
    transition(pool, t, "p0_proposed", actor="pm")
    transition(pool, t, "p1_drafting", actor="boss")
    transition(pool, t, "p1_proposed", actor="pm")
    transition(pool, t, "p2_designing", actor="boss")
    t.owner_role = owner_role           # architect 还在画图,boss 尚未接手
    save_ticket(pool, t)
    return t


def test_overview_pending_excludes_non_boss_p2(pool):
    # 终审 F3:待审批口径与审批中心一致 ——
    # p2_designing 且 owner!=boss(设计未完成)不计入;探针草稿计入
    from orchestrator.daemon.ticket import new_ticket
    _p2_designing_ticket(pool, owner_role="architect")
    p1 = new_ticket(pool, project="p", summary="测试缺口:payments",
                    created_by="probe")             # draft 探针草稿
    p2 = new_ticket(pool, project="p", summary="测试缺口:refund",
                    created_by="probe")             # 第二张探针草稿
    d = overview_data(pool, _cfg())
    # 新口径:2 张探针草稿(architect 的 p2_designing 不计)
    # 旧口径(state in APPROVALS):1(只数了 p2_designing)→ 能区分
    assert d["pending_approval"] == 2
    # 对照:审批中心分组口径
    from orchestrator.dashboard.views import pending_groups
    groups = pending_groups(pool)
    assert sum(len(v) for k, v in groups.items() if k != "suspended") == 2
    assert {t.id for t in groups["probe"]} == {p1.id, p2.id}


def test_approve_rejects_p2_not_owned_by_boss(pool_client):
    # 终审 F3:owner=architect 的 p2_designing 不可批准(与列表过滤口径一致)
    pool, client = pool_client
    from orchestrator.daemon.ticket import load_ticket
    t = _p2_designing_ticket(pool, owner_role="architect")
    r = client.post(f"/approve/{t.id}")
    assert r.status_code == 409
    assert "设计尚未完成" in r.get_data(as_text=True)
    assert load_ticket(pool, t.id).state == "p2_designing"
