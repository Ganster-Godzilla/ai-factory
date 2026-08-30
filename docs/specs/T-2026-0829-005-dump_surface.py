#!/usr/bin/env python
"""dump_surface —— 导出后端公共面(行为基线的机器可读快照)。

S1 任务件:在 T2 拆分 main.py 之前,把"对外可观测的行为面"固化为 JSON,
供 check_baseline.py 做拆分前后的硬对比。

产物分三段:
- meta:   生成环境(python / fastapi / pydantic / uvicorn 版本),
          仅供人工诊断依赖漂移,不参与基线硬对比。
- http:   FastAPI 应用对外 HTTP 面 —— 路由注册序列(顺序即路由优先级,
          含 /media 挂载与 /docs 等内置路由)+ 完整 openapi.json。
- module: apps/api 下全部 Python 源码的结构快照(imports / 顶层赋值 /
          顶层 def·class 及其签名与装饰器),按文件名排序。

用法:
    python dump_surface.py                 # JSON 输出到 stdout
    python dump_surface.py --out <file>    # 写入 UTF-8 文件,stdout 打印摘要

需要 apps/api/.venv(依赖已安装),通常经 tools/validate.ps1 调用。
"""

from __future__ import annotations

import argparse
import ast
import json
import platform
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = REPO_ROOT / "apps" / "api"

_SUMMARY_LIMIT = 240


def _truncated(text: str) -> str:
    if len(text) <= _SUMMARY_LIMIT:
        return text
    return text[:_SUMMARY_LIMIT] + " …"


def _decorators(node: ast.AST) -> list[str]:
    return [ast.unparse(decorator) for decorator in getattr(node, "decorator_list", [])]


def _import_entry(node: ast.AST) -> dict[str, Any]:
    if isinstance(node, ast.ImportFrom):
        module = "." * (node.level or 0) + (node.module or "")
        names = ", ".join(
            alias.name + (f" as {alias.asname}" if alias.asname else "")
            for alias in node.names
        )
        return {"kind": "import", "name": f"from {module} import {names}"}
    names = ", ".join(
        alias.name + (f" as {alias.asname}" if alias.asname else "")
        for alias in node.names
    )
    return {"kind": "import", "name": f"import {names}"}


def _definition_entries(tree: ast.Module) -> list[dict[str, Any]]:
    """按源码顺序提取单个文件的顶层结构(顺序本身即信息,不做排序)。"""
    entries: list[dict[str, Any]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = ast.unparse(node.args)
            returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
            prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            entries.append(
                {
                    "kind": prefix,
                    "name": node.name,
                    "signature": f"{node.name}({args}){returns}",
                    "decorators": _decorators(node),
                }
            )
        elif isinstance(node, ast.ClassDef):
            entries.append(
                {
                    "kind": "class",
                    "name": node.name,
                    "bases": [ast.unparse(base) for base in node.bases],
                    "decorators": _decorators(node),
                }
            )
        elif isinstance(node, ast.Assign):
            targets = [
                target.id for target in node.targets if isinstance(target, ast.Name)
            ]
            entries.append(
                {
                    "kind": "assign",
                    "name": ", ".join(targets),
                    "value": _truncated(ast.unparse(node.value)),
                }
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            entries.append(
                {
                    "kind": "ann-assign",
                    "name": node.target.id,
                    "annotation": ast.unparse(node.annotation),
                    "value": _truncated(
                        ast.unparse(node.value) if node.value is not None else ""
                    ),
                }
            )
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            entries.append(_import_entry(node))
        else:
            entries.append(
                {
                    "kind": type(node).__name__,
                    "name": "",
                    "value": _truncated(ast.unparse(node)),
                }
            )
    return entries


def _module_surface() -> dict[str, Any]:
    py_files = sorted(
        path
        for path in API_DIR.rglob("*.py")
        if not any(part in {".venv", "__pycache__"} for part in path.parts)
    )
    surface: dict[str, Any] = {}
    for path in py_files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        surface[rel] = _definition_entries(tree)
    return surface


def _http_surface(app: Any) -> dict[str, Any]:
    routes: list[dict[str, Any]] = []
    for route in app.routes:
        route_type = type(route).__name__
        entry: dict[str, Any] = {
            "type": route_type,
            "path": getattr(route, "path", None),
        }
        methods = getattr(route, "methods", None)
        if methods:
            entry["methods"] = sorted(methods)
        name = getattr(route, "name", None)
        if name is not None:
            entry["name"] = name
        if route_type == "APIRoute":
            entry["status_code"] = getattr(route, "status_code", None)
            entry["include_in_schema"] = getattr(route, "include_in_schema", None)
        routes.append(entry)
    return {"routes": routes, "openapi": app.openapi()}


def _meta() -> dict[str, Any]:
    import fastapi
    import pydantic
    import uvicorn

    return {
        "python": platform.python_version(),
        "fastapi": fastapi.__version__,
        "pydantic": pydantic.__version__,
        "uvicorn": uvicorn.__version__,
    }


def build_surface() -> dict[str, Any]:
    """导入 apps/api/main.py 并构建公共面快照(需 venv 依赖已安装)。"""
    if str(API_DIR) not in sys.path:
        sys.path.insert(0, str(API_DIR))
    try:
        import main  # noqa: PLC0415 —— 被测对象本身就是这个单体模块
    except ImportError as exc:
        print(
            f"[dump_surface] 导入 apps/api/main.py 失败:{exc}\n"
            "[dump_surface] 请先执行 .\\tools\\validate.ps1 venv 安装依赖。",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    return {
        "meta": _meta(),
        "http": _http_surface(main.app),
        "module": _module_surface(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="导出后端公共面快照")
    parser.add_argument("--out", help="写入指定文件(UTF-8);缺省打印到 stdout")
    parser.add_argument("--check", help="与基线 JSON 硬对比(http+module 段,meta 不参与);一致退出 0,不一致打印差异退出 1")
    args = parser.parse_args()

    surface = build_surface()
    text = json.dumps(surface, ensure_ascii=False, indent=2) + "\n"

    openapi_paths = len((surface["http"].get("openapi") or {}).get("paths") or {})
    module_defs = sum(len(entries) for entries in surface["module"].values())
    summary = (
        f"[dump_surface] routes={len(surface['http']['routes'])} "
        f"openapi_paths={openapi_paths} "
        f"module_files={len(surface['module'])} module_entries={module_defs}"
    )

    if args.check:
        baseline = json.loads(Path(args.check).read_text(encoding="utf-8"))
        # http 段(路由/openapi=行为契约)严格比对;
        # module 段按"def/class 符号集"扁平化比对(拆分重构会新增文件,文件归属变化不算行为变更)
        if surface.get("http") != baseline.get("http"):
            print(f"[check] FAIL: http 面(路由/openapi)与基线不一致 -> {args.check}")
            return 1
        def flat(mod):
            out = {}
            for fname, entries in (mod or {}).items():
                for e in entries:
                    if isinstance(e, dict) and e.get("kind") in ("def", "class"):
                        out.setdefault(e.get("name"), []).append(
                            json.dumps(e.get("signature"), ensure_ascii=False, sort_keys=True))
            return out
        cur_f, base_f = flat(surface.get("module")), flat(baseline.get("module"))
        missing = [k for k in base_f if k not in cur_f]
        added = [k for k in cur_f if k not in base_f]
        changed = [k for k in base_f if k in cur_f and sorted(base_f[k]) != sorted(cur_f[k])]
        if missing or changed:
            print(f"[check] FAIL: 符号缺失={missing} 签名变化={changed} -> {args.check}")
            return 1
        if added:
            print(f"[check] 提示: 新增符号(拆分移动所致属正常): {added[:5]}")
        print(f"[check] OK: http 面一致 + 符号集一致({args.check})")
        return 0

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        print(f"{summary} -> {out_path}")
    else:
        print(text, end="")
        print(summary, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
