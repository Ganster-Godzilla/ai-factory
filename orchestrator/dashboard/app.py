"""Dashboard Flask 应用工厂。测试可注入 tmp pool。

单实例 PID 锁(T-2026-0921-004 O3):启动前 acquire_pid_lock——活锁拒启
(打印占用 PID,孤儿旧代码抢流量有前科:0921-004 事故直接诱因);
死锁回收+pid_lock_reclaimed 事件;release 只清自己的锁(防退出竞态误删)。
"""
from __future__ import annotations

import atexit
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

from orchestrator.dashboard import office, views
from orchestrator.daemon.events import append_event
from orchestrator.daemon.statemachine import (IllegalTransition,
                                              approval_target, resume, transition)
from orchestrator.daemon.ticket import load_ticket

# 本地 CSRF 防护(终审 F2):POST 的 Origin/Referer host 只认回环
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}

_PID_LOCK = ".dashboard.pid"


def _pid_alive_default(pid: int) -> bool:
    """活判:Windows=ctypes OpenProcess(0x1000),POSIX=os.kill(pid, 0)。"""
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_pid_lock(pool: Path, pid: int | None = None,
                     alive_check=None) -> bool:
    """单实例闸:活锁占用→SystemExit(打印占用 PID);死锁→回收+事件;
    无锁→登记自 PID+启动时刻。"""
    pool = Path(pool)
    pool.mkdir(parents=True, exist_ok=True)
    pid = pid if pid is not None else os.getpid()
    alive_check = alive_check or _pid_alive_default
    lock = pool / _PID_LOCK
    if lock.exists():
        try:
            occupant = json.loads(lock.read_text(encoding="utf-8")).get("pid")
        except (ValueError, AttributeError):
            occupant = None  # 锁内容损坏=来源不明,按死锁回收(可启动)
        if occupant is not None and alive_check(int(occupant)):
            raise SystemExit(
                f"dashboard 已在运行(PID={occupant}),拒启防孤儿;"
                f"确认死进程后可删 {lock} 或走回收启动")
        lock.unlink(missing_ok=True)
        append_event(pool, "dashboard", "system", "pid_lock_reclaimed",
                     note=f"死锁回收(前 PID={occupant}),本次 PID={pid}")
    lock.write_text(json.dumps({
        "pid": pid,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }), encoding="utf-8")
    return True


def release_pid_lock(pool: Path, pid: int | None = None) -> None:
    """只清自己的锁(锁内容 PID 不符=后启者所有,绝不动)。"""
    lock = Path(pool) / _PID_LOCK
    pid = pid if pid is not None else os.getpid()
    try:
        content = json.loads(lock.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return
    if content.get("pid") == pid:
        lock.unlink(missing_ok=True)


def _register_pid_lock(pool: Path) -> None:
    """启动钩:取锁+登记退出清锁(cli dashboard 路径调用)。"""
    acquire_pid_lock(pool)
    atexit.register(release_pid_lock, pool)


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

    # --- 可视化办公室(T-2026-0911-004):只读 API + 灰盒页 ---
    @app.get("/api/v1/office")
    def api_office():
        """只读:六岗位×关联工单×KPI×待办,轮询消费;4s TTL 缓存(首屏 12-20s 实证),
        前端不得据此改状态。"""
        d = office.office_data_cached(
            app.config["POOL"], app.config["CFG"],
            project=request.args.get("project"))
        return jsonify(d)

    @app.get("/office")
    def office_page():
        # 办公室正式入口 = 新 SPA(方块人沙盒,T-2026-0911-007);旧灰盒 office.html 退役。
        # 产物 index.html 引用 /static/web/ 绝对路径,挂 /office 直出不影响资源解析。
        p = Path(__file__).parent / "static" / "web" / "index.html"
        return p.read_text(encoding="utf-8"), 200, {"Content-Type": "text/html; charset=utf-8"}

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
            _apply_approve(pool, t, _project_dir(t))
        except IllegalTransition as e:
            return _error(f"批准失败({t.id}):{e}")
        office.invalidate_office_cache()
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
        office.invalidate_office_cache()
        return redirect(url_for("approvals"))

    @app.post("/resume/<ticket_id>")
    def resume_ticket(ticket_id: str):
        pool = app.config["POOL"]
        t = load_ticket(pool, ticket_id)
        # T-2026-0902-016:同因强制恢复勾选 → force 透传(R12)
        force = bool(request.form.get("force"))
        try:
            resume(pool, t, actor="boss", force=force)
        except IllegalTransition as e:
            return _error(f"恢复失败({t.id}):{e}")
        office.invalidate_office_cache()
        return redirect(url_for("approvals"))

    # ================= 阶段3:沙盒写操作 JSON API(T-2026-0916-003) =================
    # 与上面 HTML 路由同一套状态语义;写后 invalidate 缓存;base_ts 版本冲突校验。

    def _last_ts(pool, tid: str) -> str:
        """工单当前版本戳 = 最后一条事件 ts(与办公室卡片 last_update 同口径);
        无事件回退 created_at(与 office._ticket_card 一致)。"""
        from orchestrator.daemon.events import read_events
        evs = read_events(pool, tid)
        if evs:
            return evs[-1]["ts"]
        return load_ticket(pool, tid).created_at

    def _check_fresh(pool, tid: str) -> str | None:
        """base_ts 版本冲突:页面快照与当前不一致 → 返回错误消息(409),否则 None。"""
        base = (request.get_json(silent=True) or {}).get("base_ts")
        if base and base != _last_ts(pool, tid):
            return "数据已变化,请刷新后重试"
        return None

    def _apply_approve(pool, t, project_dir) -> None:
        """批准逻辑(与 /approve HTML 路由同语义);失败抛 IllegalTransition。"""
        if t.state == "draft" and t.created_by == "probe":
            transition(pool, t, "p0_proposed", actor="boss", project_dir=project_dir)
        elif t.state == "p2_designing" and t.owner_role != "boss":
            raise IllegalTransition(f"设计尚未完成(owner={t.owner_role})")
        elif approval_target(t) is not None:
            transition(pool, t, approval_target(t), actor="boss",
                       project_dir=project_dir)
        else:
            raise IllegalTransition(f"{t.state} 无可审批迁移")

    @app.post("/api/v1/tickets/<ticket_id>/approve")
    def api_approve(ticket_id: str):
        pool = app.config["POOL"]
        t = load_ticket(pool, ticket_id)
        stale = _check_fresh(pool, ticket_id)
        if stale:
            return jsonify({"ok": False, "error": stale}), 409
        try:
            _apply_approve(pool, t, _project_dir(t))
        except IllegalTransition as e:
            return jsonify({"ok": False, "error": str(e)}), 409
        office.invalidate_office_cache()
        return jsonify({"ok": True, "state": t.state})

    @app.post("/api/v1/tickets/<ticket_id>/reject")
    def api_reject(ticket_id: str):
        pool = app.config["POOL"]
        t = load_ticket(pool, ticket_id)
        stale = _check_fresh(pool, ticket_id)
        if stale:
            return jsonify({"ok": False, "error": stale}), 409
        try:
            if t.state == "p2_designing":
                transition(pool, t, "p1_drafting", actor="boss")
            else:
                transition(pool, t, "closed", actor="boss")
        except IllegalTransition as e:
            return jsonify({"ok": False, "error": str(e)}), 409
        office.invalidate_office_cache()
        return jsonify({"ok": True, "state": t.state})

    @app.post("/api/v1/tickets/<ticket_id>/resume")
    def api_resume(ticket_id: str):
        pool = app.config["POOL"]
        t = load_ticket(pool, ticket_id)
        stale = _check_fresh(pool, ticket_id)
        if stale:
            return jsonify({"ok": False, "error": stale}), 409
        force = bool((request.get_json(silent=True) or {}).get("force"))
        try:
            resume(pool, t, actor="boss", force=force)
        except IllegalTransition as e:
            return jsonify({"ok": False, "error": str(e)}), 409
        office.invalidate_office_cache()
        return jsonify({"ok": True, "state": t.state})

    @app.post("/api/v1/tickets")
    def api_create_ticket():
        """网页建单:project 须已登记;created_by=human(boss 在环语义);
        保存 draft 不触发执行,进 P0→P5 现有流程。"""
        from orchestrator.daemon.ticket import new_ticket
        body = request.get_json(silent=True) or {}
        project = (body.get("project") or "").strip()
        summary = (body.get("summary") or "").strip()
        if not project or project not in (app.config["CFG"].get("projects") or {}):
            return jsonify({"ok": False, "error": f"项目未登记: {project or '<空>'}"}), 400
        if not summary:
            return jsonify({"ok": False, "error": "目标/摘要不能为空"}), 400
        pool = app.config["POOL"]
        t = new_ticket(pool, project, summary, created_by="human")
        office.invalidate_office_cache()
        return jsonify({"ok": True, "id": t.id, "state": t.state})

    @app.get("/api/v1/tickets/<ticket_id>/artifacts/<key>")
    def api_artifact(ticket_id: str, key: str):
        """交付物只读:按工单 artifacts 指针读项目内文件;
        路径必须解析在项目登记目录内(防穿越),找不到/越界 → 404。"""
        from orchestrator.daemon.gates import project_dir_for
        pool = app.config["POOL"]
        t = load_ticket(pool, ticket_id)
        rel = (t.artifacts or {}).get(key)
        base = project_dir_for(app.config["CFG"], t.project)
        if not rel or base is None:
            abort(404)
        target = (base / rel).resolve()
        if not str(target).startswith(str(base.resolve())) or not target.is_file():
            abort(404)
        from flask import send_file
        return send_file(target)

    return app
