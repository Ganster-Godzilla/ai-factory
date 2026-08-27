"""Dashboard Flask 应用工厂。测试可注入 tmp pool。"""
from __future__ import annotations

from pathlib import Path

from flask import Flask, redirect, render_template, url_for

from orchestrator.dashboard import views
from orchestrator.daemon.statemachine import (APPROVALS, IllegalTransition,
                                              resume, transition)
from orchestrator.daemon.ticket import load_ticket


def create_app(pool_dir: Path, cfg: dict) -> Flask:
    app = Flask(__name__)
    app.config["POOL"] = Path(pool_dir)
    app.config["CFG"] = cfg

    @app.get("/")
    def index():
        return render_template("index.html", **views.overview_data(
            app.config["POOL"], app.config["CFG"]))

    @app.get("/approvals")
    def approvals():
        return render_template("approvals.html",
                               groups=views.pending_groups(app.config["POOL"]))

    def _error(msg: str):
        return render_template(
            "approvals.html",
            groups=views.pending_groups(app.config["POOL"]),
            error=msg), 409

    @app.post("/approve/<ticket_id>")
    def approve(ticket_id: str):
        pool = app.config["POOL"]
        t = load_ticket(pool, ticket_id)
        try:
            if t.state == "draft" and t.created_by == "probe":
                # 探针草稿"采纳" = 老板直接提交 P0(裁决:actor=boss 真实记录)
                transition(pool, t, "p0_proposed", actor="boss")
            elif t.state in APPROVALS:
                transition(pool, t, APPROVALS[t.state], actor="boss")
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
