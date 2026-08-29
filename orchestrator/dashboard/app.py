"""Dashboard Flask 应用工厂。测试可注入 tmp pool。"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, abort, redirect, render_template, request, url_for

from orchestrator.dashboard import views
from orchestrator.daemon.statemachine import (APPROVALS, IllegalTransition,
                                              resume, transition)
from orchestrator.daemon.ticket import load_ticket

# 本地 CSRF 防护(终审 F2):POST 的 Origin/Referer host 只认回环
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}


def create_app(pool_dir: Path, cfg: dict) -> Flask:
    app = Flask(__name__)
    app.config["POOL"] = Path(pool_dir)
    app.config["CFG"] = cfg

    @app.before_request
    def csrf_origin_guard():
        if request.method != "POST":
            return None
        origin = request.headers.get("Origin") or request.headers.get("Referer")
        if not origin:
            return None   # curl/CLI 无头场景放行
        host = urlparse(origin).hostname or ""
        if host not in _LOOPBACK_HOSTS:
            abort(403)
        return None

    @app.get("/")
    def index():
        return render_template("index.html", **views.overview_data(
            app.config["POOL"], app.config["CFG"]))

    @app.get("/approvals")
    def approvals():
        return render_template("approvals.html",
                               groups=views.pending_groups(app.config["POOL"]))

    @app.get("/tickets")
    def tickets():
        d = views.ticket_list(
            app.config["POOL"],
            project=request.args.get("project"),
            state=request.args.get("state"),
            q=request.args.get("q"),
            sort=request.args.get("sort", "id_desc"))
        return render_template("tickets.html", **d)

    @app.get("/projects")
    def projects():
        return render_template("projects.html",
                               **views.swimlanes(app.config["POOL"]))

    def _error(msg: str):
        return render_template(
            "approvals.html",
            groups=views.pending_groups(app.config["POOL"]),
            error=msg), 409

    @app.errorhandler(FileNotFoundError)
    @app.errorhandler(ValueError)
    def ticket_not_found(e):
        # load_ticket 对不存在工单抛 FileNotFoundError(T5 搭车);
        # id 格式非法(路径遍历)抛 ValueError(T7 搭车)→ 统一 404
        return "工单不存在", 404

    @app.get("/ticket/<ticket_id>")
    def ticket(ticket_id: str):
        # id 非法/工单不存在 → ValueError/FileNotFoundError → errorhandler 404
        d = views.ticket_detail(app.config["POOL"], ticket_id)
        return render_template("ticket.html", **d)

    def _project_dir(t) -> Path | None:
        """工单项目名 → cfg projects 登记目录(共置 gates.project_dir_for)。"""
        from orchestrator.daemon.gates import project_dir_for
        return project_dir_for(app.config["CFG"], t.project)

    @app.post("/approve/<ticket_id>")
    def approve(ticket_id: str):
        pool = app.config["POOL"]
        t = load_ticket(pool, ticket_id)
        try:
            if t.state == "draft" and t.created_by == "probe":
                # 探针草稿"采纳" = 老板直接提交 P0(裁决:actor=boss 真实记录)
                transition(pool, t, "p0_proposed", actor="boss",
                           project_dir=_project_dir(t))
            elif t.state == "p2_designing" and t.owner_role != "boss":
                # owner 门禁(终审 F3):设计尚未交还 boss,与审批中心列表过滤口径一致
                return _error(f"批准失败({t.id}):设计尚未完成(owner={t.owner_role})")
            elif t.state in APPROVALS:
                transition(pool, t, APPROVALS[t.state], actor="boss",
                           project_dir=_project_dir(t))
            else:
                raise IllegalTransition(f"{t.state} 无可审批迁移")
        except IllegalTransition as e:
            return _error(f"批准失败({t.id}):{e}")
        return redirect(url_for("approvals"))

    @app.post("/reject/<ticket_id>")
    def reject(ticket_id: str):
        pool = app.config["POOL"]
        t = load_ticket(pool, ticket_id)
        try:
            if t.state == "p2_designing":
                # P2 设计驳回 = 打回 P1 重做(closed 非法,见状态机)
                transition(pool, t, "p1_drafting", actor="boss")
            else:
                transition(pool, t, "closed", actor="boss")
        except IllegalTransition as e:
            return _error(f"驳回失败({t.id}):{e}")
        return redirect(url_for("approvals"))

    @app.post("/resume/<ticket_id>")
    def resume_ticket(ticket_id: str):
        pool = app.config["POOL"]
        t = load_ticket(pool, ticket_id)
        try:
            resume(pool, t, actor="boss")
        except IllegalTransition as e:
            return _error(f"恢复失败({t.id}):{e}")
        return redirect(url_for("approvals"))

    return app
