"""gitguard 守卫测试(T-2026-0902-006 S1):临时仓四场景。

场景矩阵(design):干净过 / 他人提交拦 / 脏树拦 / 白名单放;
另有 CLI 退出码、.orc-base 记号豁免、白名单可配置、loop_merge 字段助手。
"""
import subprocess

import pytest

from orchestrator.daemon.cli import main as cli_main
from orchestrator.daemon.gitguard import (
    DEFAULT_ALLOWED_PREFIXES,
    check_pre_merge,
    make_loop_merge_fields,
)


def _git(repo, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, f"git {' '.join(args)} 失败: {r.stderr.strip()}"
    return r.stdout


def _commit(repo, msg: str) -> str:
    # 内容随消息变化,保证每次提交都有实际变更
    (repo / "README.md").write_text(msg, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", msg)
    return _git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path):
    """临时仓:main 基线已提交,refs/remotes/origin/main = 基线(模拟已推送)。

    不用真实 push/fetch:本沙箱 git push/fetch 会拉起 msys sh 被拦
    (CreateFileMapping 拒绝,存量环境问题),且守卫只消费本地 origin/main ref;
    update-ref 落 ref 与 fetch 后效果一致,测试免网络、可复现。
    """
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=r, check=True,
                   capture_output=True)
    _git(r, "config", "user.email", "guard@test")
    _git(r, "config", "user.name", "守卫测试")
    (r / "README.md").write_text("base", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "init: 基线")
    _git(r, "update-ref", "refs/remotes/origin/main", "HEAD")
    return r


# ---- 四场景:干净过 / 他人提交拦 / 脏树拦 / 白名单放 ----

def test_clean_all_pushed_passes(repo):
    assert check_pre_merge(repo) == []


def test_other_unpushed_commit_blocked(repo):
    head = _commit(repo, "feat: 会话侧未推送提交")
    blockers = check_pre_merge(repo)
    assert len(blockers) == 1
    b = blockers[0]
    assert b.kind == "unpushed"
    assert b.detail.startswith("origin/main 之后存在 1 个非 loop 签名提交")
    assert head[:12] in b.detail        # hash 指名
    assert "守卫测试" in b.detail       # 作者指名
    assert "会话侧未推送提交" in b.detail   # 首行指名


def test_dirty_tree_blocked(repo):
    (repo / "README.md").write_text("未提交的他人改动", encoding="utf-8")
    blockers = check_pre_merge(repo)
    assert len(blockers) == 1
    b = blockers[0]
    assert b.kind == "dirty"
    assert "README.md" in b.detail


def test_dirty_untracked_blocked(repo):
    (repo / "stray.txt").write_text("来路不明的文件", encoding="utf-8")
    blockers = check_pre_merge(repo)
    assert blockers and blockers[0].kind == "dirty"
    assert "stray.txt" in blockers[0].detail


@pytest.mark.parametrize("msg", [
    "docs(T-2026-0902-006): 守卫说明",           # 工单号线 docs
    "feat(T-2026-0902-006): 守卫实现",           # 工单号线 feat
    "fix(T-2026-0902-006): 修补",                 # 工单号线 fix
    "merge(T-2026-0902-006): 合入",               # 工单号线 merge
    "release(T-2026-0902-006): 发布",             # 工单号线 release
    "chore(S1): 小修",                            # loop 切片签名 chore(S
    "merge(S1): 集成",                            # loop 切片签名 merge(S
    "merge(orc/T-2026-0902-006-S1): 分支合入",    # worktree 分支签名 merge(orc/
])
def test_whitelisted_prefix_passes(repo, msg):
    _commit(repo, msg)
    assert check_pre_merge(repo) == []


def test_mixed_only_others_flagged(repo):
    _commit(repo, "docs(T-2026-0902-006): 自建说明")
    _commit(repo, "feat: 他人提交混入")
    blockers = check_pre_merge(repo)
    assert len(blockers) == 1
    assert "他人提交混入" in blockers[0].detail
    assert "自建说明" not in blockers[0].detail


def test_missing_origin_main_blocks(repo):
    """origin/main 无法定位(无 remote/从未 fetch)→ 宁可误拦,不静默放行。"""
    _git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    blockers = check_pre_merge(repo)
    assert blockers and blockers[0].kind == "unpushed"
    assert "无法定位 origin/main" in blockers[0].detail


def test_allowed_prefixes_override(repo):
    _commit(repo, "custom-xyz: 特殊签名")
    # 默认白名单不认 → 拦
    assert len(check_pre_merge(repo)) == 1
    # 覆盖白名单后放行(可配置,歧义澄清 Q2)
    assert check_pre_merge(
        repo, allowed_prefixes=DEFAULT_ALLOWED_PREFIXES + ("custom-xyz:",)) == []


# ---- 编排器记号豁免:worktree 内 .orc-base 是 harness 书签,不算脏 ----

def test_orc_base_marker_dirty_ignored(repo):
    (repo / ".orc-base").write_text("deadbeef\n", encoding="utf-8")
    assert check_pre_merge(repo) == []


# ---- CLI:orc guard pre-merge(0 过 / 2 拦 / 1 守卫失败) ----

def test_cli_guard_pre_merge_pass_then_block(repo):
    assert cli_main(["guard", "pre-merge", str(repo)]) == 0
    _commit(repo, "feat: 他人未推送")
    assert cli_main(["guard", "pre-merge", str(repo)]) == 2


def test_cli_guard_pre_merge_defaults_to_cwd(repo, monkeypatch):
    # 验收形态:python -m orchestrator.daemon.cli guard pre-merge .
    monkeypatch.chdir(repo)
    assert cli_main(["guard", "pre-merge"]) == 0


def test_cli_guard_pre_merge_not_a_repo(tmp_path):
    assert cli_main(["guard", "pre-merge", str(tmp_path)]) == 1


# ---- loop_merge 审计字段助手(design:合并点由 dev-loop 报告) ----

def test_make_loop_merge_fields_after_merge(repo):
    base = _git(repo, "rev-parse", "origin/main").strip()
    _commit(repo, "docs(T-2026-0902-006): 切片已合入 main")
    fields = make_loop_merge_fields(repo)
    assert set(fields) == {"base", "head_before", "head_after"}
    assert fields["base"] == base
    assert fields["head_after"] == _git(repo, "rev-parse", "HEAD").strip()
    # 快道时序:先同步到 origin/main 再合 → 合并前 main HEAD = merge-base
    assert fields["head_before"] == base
