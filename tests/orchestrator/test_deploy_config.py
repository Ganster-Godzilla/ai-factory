"""G1:deploy 配置 schema 加载校验(T-2026-0901-004 F1)。

覆盖:双形态加载 / 未登记 None / 缺必填键报错 / target 非法 / 类型结构校验 /
本地基准文件路径存在性 / orchestrator.yaml 登记契约。
"""
import yaml
import pytest
from pathlib import Path

from orchestrator.daemon.deploy import load_deploy_config

REMOTE_CFG = {
    "target": "remote",
    "host": "deploy@47.109.84.154",
    "ssh_key": "~/.ssh/sk-aliyun-47",
    "app_dir": "/opt/sk-video-studio",
    "service": "sk-api",
    "build_cmd": "npm run build --prefix apps/web",
    "dist_dir": "apps/web/dist",
    "requirements": "apps/api/requirements.txt",
    "env_example": ".env.example",
    "remote_env": "/opt/sk-video-studio/.env",
    "restart_cmd": "sudo -n systemctl restart sk-api",
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


def _cfg(**kw) -> dict:
    d = {"deploy": {"sk-video-studio": dict(REMOTE_CFG), "ai-factory": dict(LOCAL_CFG)}}
    d.update(kw)
    return d


# --- 双形态加载 ---


def test_remote_form_loads():
    conf = load_deploy_config(_cfg(), "sk-video-studio")
    assert conf is not None
    assert conf["target"] == "remote"
    assert conf["host"] == "deploy@47.109.84.154"
    assert conf["smoke"][0] == "http://47.109.84.154/api/health"


def test_local_form_loads():
    conf = load_deploy_config(_cfg(), "ai-factory")
    assert conf is not None
    assert conf["target"] == "local"
    assert conf["processes"][0]["name"] == "dashboard"
    assert conf["processes"][0]["pidfile"] == ".orc-local/dashboard.pid"
    assert conf["processes"][0]["start_cmd"] == "python -m orchestrator.dashboard.app"


# --- 未登记 None ---


def test_unregistered_project_returns_none():
    assert load_deploy_config(_cfg(), "ghost-project") is None


def test_no_deploy_section_returns_none():
    assert load_deploy_config({"projects": {}}, "sk-video-studio") is None


def test_deploy_section_not_dict_returns_none():
    assert load_deploy_config({"deploy": "oops"}, "sk-video-studio") is None


def test_registered_but_not_dict_raises():
    bad = _cfg()
    bad["deploy"]["ai-factory"] = ["not", "a", "dict"]
    with pytest.raises(ValueError, match="映射"):
        load_deploy_config(bad, "ai-factory")


# --- 缺必填键报错 ---


def test_missing_required_key_remote():
    bad = _cfg()
    del bad["deploy"]["sk-video-studio"]["restart_cmd"]
    with pytest.raises(ValueError, match="restart_cmd"):
        load_deploy_config(bad, "sk-video-studio")


def test_missing_required_key_local():
    bad = _cfg()
    del bad["deploy"]["ai-factory"]["smoke"]
    with pytest.raises(ValueError, match="smoke"):
        load_deploy_config(bad, "ai-factory")


def test_missing_processes_local():
    bad = _cfg()
    del bad["deploy"]["ai-factory"]["processes"]
    with pytest.raises(ValueError, match="processes"):
        load_deploy_config(bad, "ai-factory")


def test_missing_target():
    bad = _cfg()
    del bad["deploy"]["ai-factory"]["target"]
    with pytest.raises(ValueError, match="target"):
        load_deploy_config(bad, "ai-factory")


def test_invalid_target():
    bad = _cfg()
    bad["deploy"]["ai-factory"]["target"] = "cloud"
    with pytest.raises(ValueError, match="target"):
        load_deploy_config(bad, "ai-factory")


# --- 类型/结构校验 ---


def test_smoke_must_be_nonempty_list():
    bad = _cfg()
    bad["deploy"]["ai-factory"]["smoke"] = []
    with pytest.raises(ValueError, match="smoke"):
        load_deploy_config(bad, "ai-factory")


def test_smoke_entries_must_be_http_urls():
    bad = _cfg()
    bad["deploy"]["ai-factory"]["smoke"] = ["ftp://x/"]
    with pytest.raises(ValueError, match="smoke"):
        load_deploy_config(bad, "ai-factory")
    bad = _cfg()
    bad["deploy"]["ai-factory"]["smoke"] = ["http://x/", 123]
    with pytest.raises(ValueError, match="smoke"):
        load_deploy_config(bad, "ai-factory")


def test_remote_string_fields_nonempty():
    for k in ("host", "ssh_key", "app_dir", "restart_cmd", "requirements",
              "env_example", "remote_env"):
        bad = _cfg()
        bad["deploy"]["sk-video-studio"][k] = "   "
        with pytest.raises(ValueError, match=k):
            load_deploy_config(bad, "sk-video-studio")


def test_remote_optional_key_type_checked():
    bad = _cfg()
    bad["deploy"]["sk-video-studio"]["service"] = 123
    with pytest.raises(ValueError, match="service"):
        load_deploy_config(bad, "sk-video-studio")


def test_process_entry_missing_keys():
    bad = _cfg()
    bad["deploy"]["ai-factory"]["processes"] = [{"name": "x"}]  # 缺 pidfile/start_cmd
    with pytest.raises(ValueError, match="pidfile"):
        load_deploy_config(bad, "ai-factory")


def test_process_entry_not_dict():
    bad = _cfg()
    bad["deploy"]["ai-factory"]["processes"] = ["dashboard"]
    with pytest.raises(ValueError, match="processes\\[0\\]"):
        load_deploy_config(bad, "ai-factory")


# --- 路径存在性(加载时校验,design §1) ---


def test_remote_local_files_must_exist(tmp_path):
    pd = tmp_path / "proj"
    pd.mkdir()
    (pd / ".env.example").write_text("A=1\n", encoding="utf-8")
    (pd / "apps" / "api").mkdir(parents=True)
    (pd / "apps" / "api" / "requirements.txt").write_text("flask\n", encoding="utf-8")
    cfg = _cfg(projects={"sk-video-studio": str(pd)})
    # 全齐 → 通过
    assert load_deploy_config(cfg, "sk-video-studio") is not None
    # 删 requirements → 报错
    (pd / "apps" / "api" / "requirements.txt").unlink()
    with pytest.raises(ValueError, match="requirements"):
        load_deploy_config(cfg, "sk-video-studio")
    # 删 env_example → 报错
    (pd / "apps" / "api" / "requirements.txt").write_text("flask\n", encoding="utf-8")
    (pd / ".env.example").unlink()
    with pytest.raises(ValueError, match="env_example"):
        load_deploy_config(cfg, "sk-video-studio")


def test_path_check_resolves_via_projects_section(tmp_path):
    # project_dir 缺省时从 cfg["projects"] 反查(checkout 与 load 同源)
    pd = tmp_path / "proj"
    (pd / "apps" / "api").mkdir(parents=True)
    (pd / "apps" / "api" / "requirements.txt").write_text("flask\n", encoding="utf-8")
    (pd / ".env.example").write_text("A=1\n", encoding="utf-8")
    cfg = _cfg(projects={"sk-video-studio": str(pd)})
    assert load_deploy_config(cfg, "sk-video-studio") is not None


def test_path_check_skipped_without_project_dir():
    # 无 projects 登记也无显式 project_dir:只做结构校验,不做路径存在性
    conf = load_deploy_config(_cfg(), "sk-video-studio")
    assert conf is not None and conf["requirements"] == "apps/api/requirements.txt"


def test_explicit_project_dir_wins(tmp_path):
    pd = tmp_path / "proj"
    (pd / "apps" / "api").mkdir(parents=True)
    (pd / "apps" / "api" / "requirements.txt").write_text("flask\n", encoding="utf-8")
    (pd / ".env.example").write_text("A=1\n", encoding="utf-8")
    cfg = _cfg()   # 故意不带 projects 段
    assert load_deploy_config(cfg, "sk-video-studio", project_dir=pd) is not None


# --- 容错与登记契约 ---


def test_unknown_keys_tolerated():
    # 与 Ticket.load 同哲学:未知键不崩(向前兼容)
    cfg = _cfg()
    cfg["deploy"]["ai-factory"]["future_key"] = "x"
    assert load_deploy_config(cfg, "ai-factory") is not None


def test_real_orchestrator_yaml_registers_dual_forms():
    """登记契约(F1):双形态在 orchestrator.yaml 落盘且结构校验通过。
    结构校验不依赖真实 checkout(去 projects 跳过路径存在性);
    本机有 checkout 时再验真实路径存在性(真实配置不得指向不存在的基准文件)。"""
    cfg = yaml.safe_load(Path("orchestrator.yaml").read_text(encoding="utf-8"))
    deploy = cfg.get("deploy") or {}
    assert set(deploy) >= {"sk-video-studio", "ai-factory"}
    cfg_no_projects = {k: v for k, v in cfg.items() if k != "projects"}
    assert load_deploy_config(cfg_no_projects, "sk-video-studio")["target"] == "remote"
    assert load_deploy_config(cfg_no_projects, "ai-factory")["target"] == "local"
    pd = (cfg.get("projects") or {}).get("sk-video-studio")
    if pd and Path(pd).is_dir():
        assert load_deploy_config(cfg, "sk-video-studio") is not None
