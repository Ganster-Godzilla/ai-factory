"""开发角色的工位:每任务一个 git worktree,崩了最多损失一个。"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# 工位依赖目录(T-2026-0901-002):验收命令以工位内相对路径执行
# (apps/api/.venv/Scripts/python.exe ...),新 worktree 没有这些目录,
# 验收在 runner 内必败——003/004 全部切片此前因此只能手工验收。
_DEP_DIR_NAMES = (".venv", "node_modules")


def _git(project: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=project, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def _registered(project: Path, wt: Path) -> bool:
    """wt 是否在 git worktree 注册表内(porcelain 路径分隔符与大小写规整)。"""
    want = os.path.normcase(os.path.normpath(str(wt)))
    out = _git(project, "worktree", "list", "--porcelain")
    for line in out.splitlines():
        if line.startswith("worktree "):
            have = os.path.normcase(os.path.normpath(line[len("worktree "):].strip()))
            if have == want:
                return True
    return False


def ensure_worktree(project: Path, name: str, base: str = "main") -> Path:
    wt = project / ".orc-worktrees" / name
    if wt.exists():
        # 僵尸残骸防线(T-2026-0901-002 续):回收半途被锁文件打断时,目录残留但
        # git 已注销——直接复用会带上过期 .orc-base,scope 闸把基线后的所有
        # 提交全判越界(003-S6 三连败实证)。未注册即 wipe 重建。
        if _registered(project, wt):
            return wt
        shutil.rmtree(wt, ignore_errors=True)
        if wt.exists():
            raise RuntimeError(f"工位残骸清不掉(文件被占用?): {wt}")
    wt.parent.mkdir(parents=True, exist_ok=True)
    branch = f"orc/{name}"
    if branch in _git(project, "branch", "--list", branch):
        # 僵尸分支(工位没了分支还在,可能带未合并提交):复用而非删除,不丢工作
        _git(project, "worktree", "add", str(wt), branch)
    else:
        _git(project, "worktree", "add", str(wt), "-b", branch, base)
    # R7 scope 越界检查:创建时把当前 HEAD 落盘为 .orc-base,
    # runner 事后用 `git diff --name-only <base>` 找出已提交的越界改动。
    # 该文件是编排器记号而非 dev 产物,收集改动清单时会排除。
    head = _git(wt, "rev-parse", "HEAD").strip()
    (wt / ".orc-base").write_text(head + "\n", encoding="utf-8")
    _link_dep_dirs(project, wt)
    return wt


def _find_dep_dirs(project: Path) -> list[Path]:
    """主仓 <=2 层内的依赖目录(.venv/node_modules),不深入其内部,秒级返回。"""
    hits: list[Path] = []

    def scan(d: Path, depth: int) -> None:
        if depth > 2:
            return
        try:
            children = [c for c in d.iterdir() if c.is_dir()]
        except OSError:
            return
        for c in children:
            if c.name in {".git", ".orc-worktrees"}:
                continue
            if c.name in _DEP_DIR_NAMES:
                hits.append(c)
                continue
            scan(c, depth + 1)

    scan(project, 0)
    return hits


def _junction(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    # Windows 目录联接免管理员;symlink 要开发者权限,不用
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(
            f"mklink /J {link} -> {target}: {(r.stderr or r.stdout).strip()}")


def _link_dep_dirs(project: Path, wt: Path) -> None:
    """把主仓依赖目录接进工位:junction(免管理员)指回主仓,.env 复制不链接
    (工位内写入不回流主仓)。非 Windows 暂无需求,跳过。"""
    if os.name != "nt":
        return
    for dep in _find_dep_dirs(project):
        dst = wt / dep.relative_to(project)
        if not dst.exists():
            _junction(dst, dep)
    env = project / ".env"
    if env.exists() and not (wt / ".env").exists():
        shutil.copy2(env, wt / ".env")


def list_worktrees(project: Path) -> list[str]:
    root = project / ".orc-worktrees"
    if not root.exists():
        return []
    return [p.name for p in root.iterdir() if p.is_dir()]


def recycle_worktree(project: Path, name: str) -> None:
    wt = project / ".orc-worktrees" / name
    if wt.exists():
        # 先摘掉依赖目录 junction:git 递归删除不认目录联接(Invalid argument);
        # junction 上 os.rmdir 只删联接本身不伤主仓;若是真实非空目录 rmdir 自然
        # 失败跳过,交给下面 git --force 删(T-2026-0901-002)
        for dep in _find_dep_dirs(project):
            try:
                os.rmdir(wt / dep.relative_to(project))
            except OSError:
                pass
    try:
        _git(project, "worktree", "remove", "--force", str(wt))
    except RuntimeError as e:
        if "not a working tree" not in str(e):
            raise
        # 上半程已摘掉注册(如首次带 junction 删除失败后的残骸):目录直接清
        if wt.exists():
            shutil.rmtree(wt, ignore_errors=True)
    # 回收必须验尸(003-S6 教训):Windows 锁文件会让 remove/rmtree 半途而废,
    # 留下未注册残骸毒化下一次 ensure(过期 .orc-base → scope 闸全越界)
    if wt.exists():
        shutil.rmtree(wt, ignore_errors=True)
    if wt.exists():
        raise RuntimeError(f"工位回收不净(文件被占用?): {wt}")
    # 分支可能已在早前失败的回收中删过(zombie 场景),不存在不视为错误
    if f"orc/{name}" in _git(project, "branch", "--list", f"orc/{name}"):
        _git(project, "branch", "-D", f"orc/{name}")
