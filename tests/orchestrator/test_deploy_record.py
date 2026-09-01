"""G3:发布记录章节写入(部署清单/冒烟结果/回滚方案)+ 冒烟失败自动建 incident
(T-2026-0901-004 F4/F5,design §4)。

覆盖(design §4 / 测试用例设计映射):
- F4 回滚说明生成:remote/local 双形态回滚方案章节含上一版回切命令
- F5 失败建 incident 不静默:tmp pool 断言 incident 单 + 回链 + 非零退出
- 部署清单章节:版本/目标/时间 + 依赖/.env 差异清单(仅 key 名,值不落库)
- 冒烟结果章节:URL/状态码/耗时全量留痕 + 总体判定
- 未登记 deploy:部署清单章节显式声明"未登记 deploy,本单纯代码交付"
"""
from orchestrator.daemon.deploy import (
    EXIT_DEPLOY_FAILED, SECTION_DEPLOY, SECTION_FAILURE, SECTION_ROLLBACK,
    SECTION_SMOKE, UNREGISTERED_DEPLOY_NOTE, SmokeResult, create_incident,
    handle_deploy_failure, release_record_path, render_deploy_manifest,
    render_smoke_section, render_unregistered_deploy, rollback_plan,
    write_release_record,
)
from orchestrator.daemon.events import read_events
from orchestrator.daemon.ticket import load_ticket, new_ticket

REMOTE_CFG = {
    "target": "remote",
    "host": "deploy@47.109.84.154",
    "ssh_key": "~/.ssh/sk-aliyun-47",
    "app_dir": "/opt/sk-video-studio",
    "restart_cmd": "sudo -n systemctl restart sk-api",
    "requirements": "apps/api/requirements.txt",
    "env_example": ".env.example",
    "remote_env": "/opt/sk-video-studio/.env",
    "smoke": ["http://47.109.84.154/api/health", "http://47.109.84.154/"],
}

LOCAL_CFG = {
    "target": "local",
    "processes": [
        {"name": "dashboard", "pidfile": ".orc-local/dashboard.pid",
         "start_cmd": "python -m orchestrator.dashboard.app"},
    ],
    "smoke": ["http://127.0.0.1:8765/"],
}


def _make_ticket(pool, tmp_path, project="sk-video-studio"):
    """建真实工单 + 建对应工单文件夹(document/business/<tid>-<短名>/05_部署交付)。"""
    t = new_ticket(pool, project=project, summary="G3 发布记录写入测试",
                   created_by="test")
    tid_dir = tmp_path / "document" / "business" / f"{t.id}-记录测试"
    (tid_dir / "05_部署交付").mkdir(parents=True)
    return t


def _smoke(ok, status, url, elapsed_ms=12):
    return SmokeResult(url=url, status=status, elapsed_ms=elapsed_ms, ok=ok)


# --- 发布记录路径与写入 ---


def test_release_record_path_resolves_tid_dir(tmp_path, pool):
    t = _make_ticket(pool, tmp_path)
    p = release_record_path(tmp_path, t.id)
    assert p is not None
    assert p == tmp_path / "document" / "business" \
        / f"{t.id}-记录测试" / "05_部署交付" / "发布记录.md"


def test_release_record_path_none_without_folder(tmp_path, pool):
    t = new_ticket(pool, project="p", summary="无文件夹", created_by="test")
    assert release_record_path(tmp_path, t.id) is None


def test_write_release_record_creates_then_appends(tmp_path):
    p = tmp_path / "05_部署交付" / "发布记录.md"
    write_release_record(p, ["## 合并清单\n\n- abc123"])
    write_release_record(p, ["## 版本\n\n- v1.0"])
    text = p.read_text(encoding="utf-8")
    assert text.startswith("# 发布记录")
    assert "## 合并清单" in text and "- abc123" in text
    assert "## 版本" in text and "- v1.0" in text
    # 追加不覆盖:两次写入的章节都在
    assert text.index("## 合并清单") < text.index("## 版本")


# --- 部署清单章节(F4 成功路径) ---


def test_deploy_manifest_section_contains_version_target_time():
    text = render_deploy_manifest(version="v1.2.3", target="remote",
                                  when="2026-09-01T10:00:00Z")
    assert f"## {SECTION_DEPLOY}" in text
    assert "`v1.2.3`" in text
    assert "`remote`" in text
    assert "`2026-09-01T10:00:00Z`" in text


def test_deploy_manifest_env_diff_keys_only_no_values():
    text = render_deploy_manifest(version="v1", target="remote", when="t",
                                  deps_note="无差异",
                                  env_diff=["DB_PASS", "API_KEY"])
    assert "DB_PASS" in text and "API_KEY" in text
    # 值永不入记录(R9):render 只接 key 名,若误传 key=value 字样也不该出现值
    assert "secret" not in text


def test_deploy_manifest_env_diff_none_omits_line():
    text = render_deploy_manifest(version="v1", target="local", when="t")
    assert ".env 差异" not in text
    text2 = render_deploy_manifest(version="v1", target="local", when="t",
                                   env_diff=[])
    assert ".env 差异:无" in text2


def test_unregistered_deploy_section_explicit_note():
    text = render_unregistered_deploy()
    assert f"## {SECTION_DEPLOY}" in text
    assert UNREGISTERED_DEPLOY_NOTE in text
    assert "本单纯代码交付" in text


# --- 冒烟结果章节(F3 留痕写入) ---


def test_smoke_section_records_all_results():
    results = [
        _smoke(ok=True, status=200, url="http://h/api/health", elapsed_ms=12),
        _smoke(ok=False, status=404, url="http://h/missing", elapsed_ms=34),
    ]
    text = render_smoke_section(results)
    assert f"## {SECTION_SMOKE}" in text
    assert "http://h/api/health" in text and "http://h/missing" in text
    assert "200" in text and "404" in text
    assert "12ms" in text and "34ms" in text
    assert "PASS" in text and "FAIL" in text
    assert "存在失败,发布失败" in text  # 任一非 200 即整体失败


def test_smoke_section_all_green_verdict():
    results = [_smoke(ok=True, status=200, url="http://h/", elapsed_ms=5)]
    assert "全绿,发布成功" in render_smoke_section(results)


# --- F4:回滚说明生成(remote/local 双形态) ---


def test_rollback_plan_remote_contains_prev_switch_cmd():
    text = rollback_plan(REMOTE_CFG, prev_version="v1.1.0")
    assert f"## {SECTION_ROLLBACK}" in text
    assert "ln -sfn releases/v1.1.0 current" in text
    assert REMOTE_CFG["restart_cmd"] in text
    assert "回切上一版包" in text


def test_rollback_plan_remote_restart_cmd_override():
    text = rollback_plan(REMOTE_CFG, prev_version="v1.1.0",
                         restart_cmd="sudo -n systemctl restart sk-api-new")
    assert "sk-api-new" in text


def test_rollback_plan_remote_placeholder_when_prev_unknown():
    text = rollback_plan(REMOTE_CFG)
    assert "ln -sfn releases/<上一版> current" in text


def test_rollback_plan_local_contains_tag_checkout_and_restart():
    text = rollback_plan(LOCAL_CFG, prev_version="v1.0.0")
    assert f"## {SECTION_ROLLBACK}" in text
    assert "git checkout v1.0.0" in text
    assert "python -m orchestrator.dashboard.app" in text
    assert "dashboard" in text


def test_rollback_plan_local_placeholder_tag():
    text = rollback_plan(LOCAL_CFG)
    assert "git checkout <上一 tag>" in text


# --- F5:失败自动建 incident + 回链 + 非零退出 ---


def test_create_incident_backlinks_original(pool):
    orig = new_ticket(pool, project="sk-video-studio", summary="原单",
                      created_by="test")
    inc = create_incident(pool, orig, "部署/冒烟失败:原单")
    assert inc.type == "incident"
    assert inc.id != orig.id
    assert inc.related_ticket == orig.id  # 事故单 → 原单
    loaded = load_ticket(pool, inc.id)
    assert loaded.related_ticket == orig.id
    # 原单事件流回链:incident_created 带 incident id(双向可查)
    events = read_events(pool, orig.id)
    assert any(e["event"] == "incident_created" and e["incident"] == inc.id
               for e in events)


def test_handle_deploy_failure_incident_backlink_nonzero_exit(pool, tmp_path):
    t = _make_ticket(pool, tmp_path)
    results = [_smoke(ok=False, status=404, url="http://47.109.84.154/missing",
                      elapsed_ms=30)]
    code = handle_deploy_failure(pool, t, tmp_path, REMOTE_CFG,
                                 results=results,
                                 detail="冒烟失败:关键新路由 404")
    assert code == EXIT_DEPLOY_FAILED
    assert code != 0  # 非零退出:release 角色判负,不静默放行

    # incident 单已建 + 回链
    pool_tickets = list((pool / "tickets").glob("T-*.yaml"))
    inc_ids = [p.stem for p in pool_tickets if p.stem != t.id]
    assert len(inc_ids) == 1
    inc = load_ticket(pool, inc_ids[0])
    assert inc.type == "incident"
    assert inc.related_ticket == t.id
    events = read_events(pool, t.id)
    assert any(e["event"] == "incident_created" and e["incident"] == inc.id
               for e in events)

    # 发布记录写失败详情 + 冒烟留痕 + 回滚说明
    record = release_record_path(tmp_path, t.id)
    assert record is not None and record.is_file()
    text = record.read_text(encoding="utf-8")
    assert f"## {SECTION_FAILURE}" in text
    assert inc.id in text
    assert "冒烟失败:关键新路由 404" in text
    assert f"## {SECTION_SMOKE}" in text
    assert "FAIL" in text
    assert f"## {SECTION_ROLLBACK}" in text
    assert "ln -sfn releases/<上一版> current" in text


def test_handle_deploy_failure_default_rollback_and_no_results(pool, tmp_path):
    t = _make_ticket(pool, tmp_path)
    code = handle_deploy_failure(pool, t, tmp_path, LOCAL_CFG,
                                 detail="本地冒烟端口未监听")
    assert code == EXIT_DEPLOY_FAILED
    record = release_record_path(tmp_path, t.id)
    text = record.read_text(encoding="utf-8")
    assert "本地冒烟端口未监听" in text
    assert "git checkout <上一 tag>" in text  # local 形态自动生成回滚


def test_failure_without_ticket_folder_still_creates_incident(pool, tmp_path):
    # 工单文件夹未建(record 不可写):incident 与退出码不受影响,不静默
    t = new_ticket(pool, project="p", summary="无文件夹单", created_by="test")
    code = handle_deploy_failure(pool, t, tmp_path, REMOTE_CFG,
                                 results=[_smoke(False, 500, "http://h/")])
    assert code == EXIT_DEPLOY_FAILED
    assert release_record_path(tmp_path, t.id) is None  # 无可写记录
    inc_ids = [p.stem for p in (pool / "tickets").glob("T-*.yaml")
               if p.stem != t.id]
    assert len(inc_ids) == 1
    assert load_ticket(pool, inc_ids[0]).related_ticket == t.id


def test_handle_deploy_failure_custom_rollback_used(pool, tmp_path):
    t = _make_ticket(pool, tmp_path)
    custom = f"## {SECTION_ROLLBACK}\n\n人工回滚步骤:revert 提交并重启"
    code = handle_deploy_failure(pool, t, tmp_path, REMOTE_CFG, rollback=custom)
    assert code == EXIT_DEPLOY_FAILED
    text = release_record_path(tmp_path, t.id).read_text(encoding="utf-8")
    assert "人工回滚步骤" in text
