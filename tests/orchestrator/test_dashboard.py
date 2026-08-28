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
    from orchestrator.daemon.ticket import new_ticket, save_ticket
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


# ============ Dashboard v2:工单中心 / 项目中心 / 总览可导航化 ============

def _mk(pool, project, summary, state=None, created_by="human"):
    from orchestrator.daemon.ticket import new_ticket, save_ticket
    t = new_ticket(pool, project=project, summary=summary, created_by=created_by)
    if state:
        t.state = state
        save_ticket(pool, t)
    return t


def test_tickets_list_renders(pool_client):
    pool, client = pool_client
    from orchestrator.daemon.statemachine import transition
    t1 = _mk(pool, "alpha", "网关改造")
    transition(pool, t1, "p0_proposed", actor="pm")
    t2 = _mk(pool, "beta", "报表导出")
    r = client.get("/tickets")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "网关改造" in html and "报表导出" in html
    assert f"/ticket/{t1.id}" in html and f"/ticket/{t2.id}" in html
    assert t1.id in html and "alpha" in html and "beta" in html


def test_tickets_default_sort_id_desc(pool_client):
    pool, client = pool_client
    t1 = _mk(pool, "alpha", "先建的")
    t2 = _mk(pool, "alpha", "后建的")
    r = client.get("/tickets")
    html = r.get_data(as_text=True)
    assert html.index(t2.id) < html.index(t1.id)   # 默认 id 倒序,后建在前


def test_tickets_filter_project_state(pool_client):
    pool, client = pool_client
    a = _mk(pool, "alpha", "A单", state="p3_running")
    b = _mk(pool, "beta", "B单", state="p3_running")
    c = _mk(pool, "alpha", "C单", state="suspended")
    r = client.get("/tickets?project=alpha&state=p3_running")
    html = r.get_data(as_text=True)
    assert a.id in html and b.id not in html and c.id not in html
    # 非法值忽略回默认(全量):state / project / sort 三类都验
    for url in ("/tickets?state=not_a_state",
                "/tickets?project=no_such_proj",
                "/tickets?sort=bogus"):
        html2 = client.get(url).get_data(as_text=True)
        assert a.id in html2 and b.id in html2 and c.id in html2, url


def test_tickets_search_q(pool_client):
    pool, client = pool_client
    a = _mk(pool, "alpha", "Gateway 熔断")
    b = _mk(pool, "beta", "报表导出")
    html = client.get("/tickets?q=gateway").get_data(as_text=True)   # 大小写不敏感
    assert a.id in html and b.id not in html
    html = client.get(f"/tickets?q={b.id.lower()}").get_data(as_text=True)
    assert b.id in html and a.id not in html
    html = client.get("/tickets?q=不存在的词").get_data(as_text=True)
    assert a.id not in html and "无匹配工单" in html


def test_tickets_sort_mtime(pool_client):
    import os
    pool, client = pool_client
    t1 = _mk(pool, "alpha", "旧单")
    t2 = _mk(pool, "alpha", "新单")
    # 显式造 mtime:t1 更新更晚(模拟 t1 最近有状态迁移)
    p1 = pool / "tickets" / f"{t1.id}.yaml"
    p2 = pool / "tickets" / f"{t2.id}.yaml"
    os.utime(p2, (1000000, 1000000))
    os.utime(p1, (2000000, 2000000))
    html = client.get("/tickets?sort=mtime_desc").get_data(as_text=True)
    assert html.index(t1.id) < html.index(t2.id)
    html = client.get("/tickets?sort=id_asc").get_data(as_text=True)
    assert html.index(t1.id) < html.index(t2.id)


def test_swimlanes_grouping_all_states(pool):
    from orchestrator.dashboard.views import swimlanes
    from orchestrator.daemon.ticket import VALID_STATES
    tickets = {s: _mk(pool, "proj", f"单-{s}", state=s) for s in VALID_STATES}
    _mk(pool, "proj", "探针草稿", created_by="probe")   # draft
    d = swimlanes(pool)
    keys = [c["key"] for c in d["columns"]]
    assert keys == ["p0", "p1", "p2", "p3", "p4", "p5", "mon", "susp"]
    row = next(r for r in d["rows"] if r["project"] == "proj")
    placed = [t.id for cell in row["cells"].values() for t in cell]
    expected_col = {
        "draft": "p0", "p0_proposed": "p0", "p1_drafting": "p1",
        "p1_proposed": "p1", "p2_designing": "p2", "p2_approved": "p2",
        "p3_queued": "p3", "p3_running": "p3", "p4_verifying": "p4",
        "p5_ready": "p5", "p5_releasing": "p5", "monitoring": "mon",
        "suspended": "susp",
    }
    for s, col in expected_col.items():
        assert tickets[s].id in [t.id for t in row["cells"][col]], s
    # closed/done 不进泳道;探针草稿入 p0;每单恰出现一次
    assert tickets["closed"].id not in placed and tickets["done"].id not in placed
    assert len(placed) == len(set(placed))


def test_projects_page_and_row_links(pool_client):
    pool, client = pool_client
    t = _mk(pool, "sk-video-studio", "泳道单", state="p3_running")
    r = client.get("/projects")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "sk-video-studio" in html and t.id in html
    assert f"/ticket/{t.id}" in html                          # chip 进详情
    assert "/tickets?project=sk-video-studio" in html         # 行头联动
    assert "P3 执行" in html and "挂起" in html


def test_projects_empty(pool_client):
    pool, client = pool_client
    html = client.get("/projects").get_data(as_text=True)
    assert "暂无" in html


def test_index_events_linked(pool_client):
    pool, client = pool_client
    t = _mk(pool, "alpha", "事件摘要单")
    html = client.get("/").get_data(as_text=True)
    assert f'<a href="/ticket/{t.id}">{t.id}</a>' in html


def test_project_strips_counts(pool):
    from orchestrator.dashboard.views import project_strips
    from orchestrator.daemon.statemachine import transition
    _mk(pool, "alpha", "运行单", state="p3_running")
    pend = _mk(pool, "alpha", "待审单")
    transition(pool, pend, "p0_proposed", actor="pm")
    _mk(pool, "alpha", "挂起单", state="suspended")
    _mk(pool, "beta", "B项目单")
    strips = {s["project"]: s for s in project_strips(pool)}
    assert strips["alpha"]["running"] == 1
    assert strips["alpha"]["pending"] == 1     # suspended 组不计 pending
    assert strips["alpha"]["suspended"] == 1
    assert strips["beta"]["running"] == 0


def test_index_shows_strips(pool_client):
    pool, client = pool_client
    _mk(pool, "quant-lab", "条带单", state="p3_running")
    html = client.get("/").get_data(as_text=True)
    assert "quant-lab" in html and "/tickets?project=quant-lab" in html


def test_nav_active(pool_client):
    pool, client = pool_client
    cases = {"/": "总览", "/tickets": "工单中心",
             "/projects": "项目中心", "/approvals": "审批中心"}
    for path, label in cases.items():
        html = client.get(path).get_data(as_text=True)
        assert f'class="active">{label}' in html, path
    t = _mk(pool, "p", "详情归属")
    html = client.get(f"/ticket/{t.id}").get_data(as_text=True)
    assert 'class="active">工单中心' in html   # 详情页导航归工单中心


def test_swimlane_columns_cover_valid_states():
    # 评审加固:VALID_STATES 扩列时映射漏配会静默丢单,这里显式锁全集
    from orchestrator.dashboard.views import SWIMLANE_COLUMNS
    from orchestrator.daemon.ticket import VALID_STATES
    mapped = {s for _, _, states in SWIMLANE_COLUMNS for s in states}
    assert set(VALID_STATES) - mapped == {"closed", "done"}


def test_swimlanes_closed_only_project_keeps_row(pool_client):
    # 评审 A5:工单全部已完结的项目仍保留行(PRD 验收#3:每个有工单的项目一行)
    pool, client = pool_client
    _mk(pool, "closed-proj", "已完结单", state="closed")
    html = client.get("/projects").get_data(as_text=True)
    assert "closed-proj" in html
    assert "已完结单" not in html        # closed 工单本身不进 chip


def test_project_links_urlencoded(pool_client):
    # 评审 A1:项目名含 & 等特殊字符时,泳道行头/总览条带链接必须编码
    pool, client = pool_client
    _mk(pool, "R&D", "特殊项目名单", state="p3_running")
    assert "project=R%26D" in client.get("/projects").get_data(as_text=True)
    assert "project=R%26D" in client.get("/").get_data(as_text=True)
    # 编码链接真的可达:R&D 的过滤结果只含该项目
    html = client.get("/tickets?project=R%26D").get_data(as_text=True)
    assert "特殊项目名单" in html


def test_null_summary_no_500(pool_client):
    # 评审 A2:yaml 手改 summary 留空(None)时,搜索/泳道不 500
    pool, client = pool_client
    t = _mk(pool, "alpha", "", state="p3_running")
    import yaml as _yaml
    p = pool / "tickets" / f"{t.id}.yaml"
    d = _yaml.safe_load(p.read_text(encoding="utf-8"))
    d["summary"] = None
    p.write_text(_yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    assert client.get("/tickets?q=x").status_code == 200
    assert client.get("/projects").status_code == 200


def test_index_pending_card_links_approvals(pool_client):
    # 评审:断言必须区分卡片链接与导航链接(nav 每页都有 /approvals)
    pool, client = pool_client
    html = client.get("/").get_data(as_text=True)
    assert '<a class="card card-link" href="/approvals">' in html


def test_index_events_system_not_linked(pool_client):
    # 评审 A4:gateway 回退写入的 system 伪工单不链接化(否则点了必 404)
    pool, client = pool_client
    append_event(pool, "system", "system", "gateway_fallback")
    html = client.get("/").get_data(as_text=True)
    assert "/ticket/system" not in html
    assert "system" in html              # 计数仍可见,纯文本
