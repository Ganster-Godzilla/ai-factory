"""doccheck(R6/D6)测试:排版变体一致通过;缺章节/禁用词判失败并输出 FAIL: 行。"""
from pathlib import Path

from orchestrator.daemon.doccheck import check, main, normalize

REPO_ROOT = Path(__file__).resolve().parents[2]

GOOD_PRD = (
    "# PRD-T-1: 示例工单\n"
    "\n"
    "## Why(问题与价值)\n"
    "\n"
    "状态推进必须有产物和账的双重证据。\n"
    "\n"
    "## What(范围与边界)\n"
    "\n"
    "只做验收器,不改状态机。\n"
    "\n"
    "## 验收标准\n"
    "\n"
    "- AC-1: 排版变体不误判\n"
)


def test_clean_document_passes():
    assert check(GOOD_PRD, ["Why", "What", "验收标准"], []) == []
    assert check(GOOD_PRD, [], ["TODO"]) == []


def test_layout_variants_pass():
    """同一合格产物的排版变体(换行/层级/空白/大小写)判定一致(AC-6)。"""
    variants = [
        GOOD_PRD.replace("\n", "\r\n"),             # CRLF/LF 统一
        GOOD_PRD.replace("## ", "### "),            # 标题层级不敏感
        GOOD_PRD.replace("\n\n", "\n\n\n\n"),       # 连续空白行压缩
        GOOD_PRD.replace("## Why(", "##  Why  ("),  # 行内多余空格忽略
        GOOD_PRD.replace("## Why", "## why"),       # 章节名大小写
    ]
    for v in variants:
        assert check(v, ["Why", "验收标准"], []) == []


def test_missing_section_reports_fail():
    assert check("", ["Why"], []) == ['FAIL: 缺少章节 "Why"']
    assert check(GOOD_PRD, ["Why", "非功能需求"], []) == ['FAIL: 缺少章节 "非功能需求"']


def test_body_mention_is_not_a_section():
    """章点名只认标题行,正文提到同名文字不算数(防口径漂移)。"""
    doc = "正文里提到验收标准三个字,但没有标题。\n"
    assert check(doc, ["验收标准"], []) == ['FAIL: 缺少章节 "验收标准"']


def test_forbidden_word_reports_fail():
    doc = "# 设计\n\n## How\n\nTODO: 待补。\n"
    assert check(doc, ["How"], ["TODO"]) == ['FAIL: 命中禁用词 "TODO"']
    assert check(doc, ["How"], ["FIXME"]) == []


def test_forbidden_word_case_insensitive():
    assert check("正文中出现 todo 字样\n", [], ["TODO"]) == ['FAIL: 命中禁用词 "TODO"']


def test_fail_lines_ordered_sections_then_forbidden():
    fails = check("TODO 和 FIXME 都在正文\n", ["Why", "验收标准"], ["TODO", "FIXME"])
    assert fails == [
        'FAIL: 缺少章节 "Why"',
        'FAIL: 缺少章节 "验收标准"',
        'FAIL: 命中禁用词 "TODO"',
        'FAIL: 命中禁用词 "FIXME"',
    ]


def test_annotated_headings_match_template_names():
    """模板惯用的括注/冒号后缀(`## Why(问题与价值)`)命中章芓名本身。"""
    doc = "## Why(问题与价值)\n\n## What:范围与边界\n\n## 验收标准(AC-1~AC-8)\n"
    assert check(doc, ["Why", "What", "验收标准"], []) == []


def test_prefix_without_boundary_does_not_match():
    """后缀不隔断(WhyNot)或名字嵌在中间(我的验收标准笔记)不算命中。"""
    doc = "## WhyNot一类标题\n\n## 我的验收标准笔记\n"
    assert check(doc, ["Why", "验收标准"], []) == [
        'FAIL: 缺少章节 "Why"',
        'FAIL: 缺少章节 "验收标准"',
    ]


def test_closed_heading_and_indent_tolerance():
    doc = "   ### Why(问题与价值) ##\n"
    assert check(doc, ["Why"], []) == []


def test_numbered_headings_match():
    """`## 2. 设计决策` 这类编号标题命中章芓名(编号属排版);照抄全名也命中。"""
    doc = ("## 1. 现状诊断(根因)\n\n## 2. 设计决策\n\n## 2.1 接口\n\n"
           "## 第三章 总体设计\n\n## (一)总则\n")
    assert check(doc, ["现状诊断", "设计决策", "接口", "总体设计", "总则"], []) == []
    assert check(doc, ["2. 设计决策", "2.1 接口"], []) == []


def test_bare_word_heading_not_swallowed_by_number_rule():
    """非编号标题不受去编号影响(`WhyNot`/`我的验收标准笔记` 仍不误命中)。"""
    doc = "## WhyNot一类标题\n\n## 2024 计划\n"
    assert check(doc, ["Why"], []) == ['FAIL: 缺少章节 "Why"']
    assert check(doc, ["2024 计划"], []) == []
    assert check(doc, ["计划"], []) == []


def test_normalize_unifies_layout_and_is_idempotent():
    raw = "# A  b\r\n\r\n\r\n\r\n## B\t c \n"
    assert normalize(raw) == "# A b\n\n## B c\n"
    assert normalize(normalize(raw)) == normalize(raw)
    assert normalize("") == ""


def test_cli_pass_exit0(capsys, tmp_path):
    f = tmp_path / "good.md"
    f.write_text(GOOD_PRD, encoding="utf-8")
    assert main([str(f), "--require-section", "Why", "--forbid", "TODO"]) == 0
    assert "FAIL" not in capsys.readouterr().out


def test_cli_fail_exit1_prints_fail_lines(capsys, tmp_path):
    f = tmp_path / "bad.md"
    f.write_text(GOOD_PRD.replace("## 验收标准\n", ""), encoding="utf-8")
    rc = main([str(f), "--require-section", "验收标准", "--forbid", "TODO"])
    out = capsys.readouterr().out
    assert rc == 1
    assert 'FAIL: 缺少章节 "验收标准"' in out


def test_cli_missing_file_fails(capsys, tmp_path):
    rc = main([str(tmp_path / "nope.md"), "--require-section", "Why"])
    assert rc == 1
    assert capsys.readouterr().out.startswith("FAIL:")


def test_cli_module_entry(tmp_path):
    """`python -m orchestrator.daemon.doccheck` 入口契约(验收命令即此形态)。"""
    import os
    import subprocess
    import sys

    f = tmp_path / "bad.md"
    f.write_text("没有要求章节的文档\n", encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONPATH=str(REPO_ROOT))
    r = subprocess.run(
        [sys.executable, "-m", "orchestrator.daemon.doccheck", str(f),
         "--require-section", "Why"],
        capture_output=True, text=True, encoding="utf-8", env=env,
        cwd=str(REPO_ROOT), timeout=60)
    assert r.returncode == 1
    assert 'FAIL: 缺少章节 "Why"' in r.stdout


# ---- G2:--require-content(T-2026-0829-001 设计 D5) ----

def test_require_content_hit_and_miss(tmp_path):
    from orchestrator.daemon.doccheck import check
    text = "# 功能清单\n\n| # | 功能 | 优先级 |\n|---|---|---|\n| F1 | x | P0 |\n"
    assert check(text, require_content=["优先级"]) == []
    fails = check(text, require_content=["优先级", "验收标准"])
    assert fails == ['FAIL: 缺少内容 "验收标准"']


def test_require_content_normalization(tmp_path):
    from orchestrator.daemon.doccheck import check
    # 行内多余空白/全角空格不影响子串命中(与 require-section 同套规整)
    text = "# A\n\n功能  清单　带优先级\n"
    assert check(text, require_content=["功能 清单"]) == []
    # 大小写不敏感(forbid 同款口径)
    assert check(text, require_content=["PRIORITY".replace("PRIORITY", "优先级")]) == []
    assert check("abc DeF\n", require_content=["def"]) == []


def test_require_content_cli(tmp_path):
    from orchestrator.daemon.doccheck import main
    f = tmp_path / "a.md"
    f.write_text("# X\n含优先级\n", encoding="utf-8")
    assert main([str(f), "--require-content", "优先级"]) == 0
    assert main([str(f), "--require-content", "不存在词"]) == 1
