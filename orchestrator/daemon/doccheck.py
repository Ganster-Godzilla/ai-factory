"""doccheck:规范化文档验收器(R6/D6)。文档类产物的验收命令统一走本模块,
不再用裸 grep 字面量/行数判定。先规范化再匹配:CRLF/LF 统一、连续空白行压缩、
标题层级/编号不敏感、行内多余空格忽略,章节名允许括注后缀(`## Why(问题与价值)`);
判定失败按 D5 约定打印 `FAIL: <子句>` 行,exit=1。

用法:
    python -m orchestrator.daemon.doccheck <md文件> \
        --require-section "Why" --require-section "验收标准" [--forbid "TODO"]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 行内空白(含全角空格/不间断空格)压成单个空格;换行不参与,禁用词不会跨行拼接
_INLINE_WS = re.compile(r"[ \t\u00a0\u3000]+")
# ATX 标题:最多容忍 3 个前导空格缩进(CommonMark);`#NoSpace` 不算标题
_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*$")
_TRAILING_HASHES = re.compile(r"[ \t]+#+$")   # `## Why ##` 闭合序列
# 标题前导编号(`## 2. 设计决策`/`## 2.1 接口`/`## 第三章 X`/`##（一）X`):属排版不算内容。
# 章节名同时拿「全文」与「去编号」两个变体参与匹配,照抄整个标题也命中
_LEADING_NUM = re.compile(
    r"^(?:"
    r"(?:第[一二三四五六七八九十百\d]+[章节部分]"
    r"|[（(]\d{1,3}[)）]|[（(][一二三四五六七八九十百]+[)）])\s*"
    r"|(?:\d+(?:\.\d+)*|[一二三四五六七八九十百]+)(?:[.、:：]\s*|\s+)"
    r")")
# 章节名后允许的注解边界:模板惯用 `## Why(问题与价值)` 这类后缀,视作同一章节。
# 全是标点/空白,不含字母汉字 → `WhyNot`、`我的验收标准笔记` 不会误命中
_BOUNDARY = " (（:：.,。、;；!！?？—)"


def normalize(text: str) -> str:
    """排版规范化:只归一排版变体,不动内容。顺序=BOM→换行→行尾空格→行内空白→连续空行。"""
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    lines = [_INLINE_WS.sub(" ", ln.rstrip()) for ln in text.split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n")
    return text + "\n" if text else text


def _headings(norm: str) -> list[tuple[str, str]]:
    """文档全部标题名,每个给 (全文, 去编号) 两个变体(小写折叠,供章节匹配)。"""
    out = []
    for ln in norm.split("\n"):
        m = _HEADING.match(ln)
        if m:
            full = _TRAILING_HASHES.sub("", m.group(2)).strip()
            out.append((full.casefold(), _LEADING_NUM.sub("", full).strip().casefold()))
    return out


def _title_matches(title: str, name: str) -> bool:
    if not name:
        return False
    return title == name or (
        title.startswith(name) and len(title) > len(name)
        and title[len(name)] in _BOUNDARY
    )


def check(text: str, require_sections=(), forbid=()) -> list[str]:
    """返回 FAIL 子句列表(缺章节在前、禁用词在后);空列表=通过。"""
    norm = normalize(text)
    titles = _headings(norm)
    fails = []
    for name in require_sections:
        k = name.casefold()
        if not any(_title_matches(f, k) or _title_matches(s, k) for f, s in titles):
            fails.append(f'FAIL: 缺少章节 "{name}"')
    folded = norm.casefold()
    fails += [f'FAIL: 命中禁用词 "{w}"' for w in forbid
              if w and w.casefold() in folded]
    return fails


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="doccheck", description="规范化文档验收器(章节存在性 + 禁用词)")
    ap.add_argument("file", help="待验收的 md 文档")
    ap.add_argument("--require-section", action="append", default=[],
                    dest="require_sections", metavar="X",
                    help="必须存在的章节标题,可重复(层级/大小写/空白变体不敏感)")
    ap.add_argument("--forbid", action="append", default=[], metavar="W",
                    help="禁止出现的词(大小写不敏感),可重复")
    args = ap.parse_args(argv)
    path = Path(args.file)
    if not path.is_file():
        print(f"FAIL: 文件不存在: {args.file}")
        return 1
    fails = check(path.read_text(encoding="utf-8", errors="replace"),
                  args.require_sections, args.forbid)
    for line in fails:
        print(line)
    if fails:
        return 1
    print(f"OK: {args.file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
