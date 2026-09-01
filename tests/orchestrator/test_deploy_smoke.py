"""G2:冒烟检查器 + 差异检查(T-2026-0901-004 F3/F6 + design §2.3)。

覆盖(design §3 / §2.4 / §2.3 与测试用例设计映射):
- F3 smoke 留痕:本地 HTTP fixture 全 200 / 非 200 判负 / 重试后转绿 /
  retries 用尽判负 / 连接失败判负 / 自定义期望码 / 空清单保守判负
- F6 .env 差异仅 key 名:注释/空行/export/无等号解析、对称差按名排序、
  值不出现在任何输出、基准缺失报错
- requirements 哈希差异:sha256 稳定且对内容敏感、远端基准缺失判 changed
"""
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from orchestrator.daemon import deploy
from orchestrator.daemon.deploy import (SmokeResult, env_key_diff,
                                        requirements_changed, requirements_sha,
                                        smoke, smoke_passed)


class _PlanHandler(BaseHTTPRequestHandler):
    """本地 HTTP fixture:按请求次序消费 status_plan,plan 耗尽后重复最后值
    (恒 [500] 即恒失败);hits 记录每个请求的 path 用于断言尝试次数。"""

    plan: list[int] = [200]
    hits: list[str] = []

    def do_GET(self):  # noqa: N802 (http.server 协议方法名)
        type(self).hits.append(self.path)
        code = type(self).plan[min(len(type(self).hits) - 1,
                                   len(type(self).plan) - 1)]
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):  # 不刷日志
        pass


@pytest.fixture
def http_server():
    _PlanHandler.plan = [200]
    _PlanHandler.hits = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _PlanHandler)
    threading.Thread(target=srv.serve_forever,
                     kwargs={"poll_interval": 0.02}, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def no_sleep(monkeypatch):
    """把重试退避换成记录器:断言重试次数且用例不真实等待(默认退避累计 6 秒)。"""
    calls: list[float] = []
    monkeypatch.setattr(deploy, "_sleep", lambda s: calls.append(s))
    return calls


def _url(srv, path="/") -> str:
    return f"http://127.0.0.1:{srv.server_address[1]}{path}"


# --- F3:冒烟留痕(design §3) ---


def test_all_200_passes(http_server, no_sleep):
    _PlanHandler.plan = [200, 200]
    results = smoke([_url(http_server, "/health"), _url(http_server, "/")])
    assert smoke_passed(results) is True
    assert [r.ok for r in results] == [True, True]
    assert [r.status for r in results] == [200, 200]
    assert all(r.elapsed_ms >= 0 for r in results)
    assert [r.url for r in results] == [_url(http_server, "/health"),
                                        _url(http_server, "/")]
    assert isinstance(results[0], SmokeResult)
    assert _PlanHandler.hits == ["/health", "/"]
    assert no_sleep == []  # 全绿一次成功,不触发退避


def test_non_200_fails_overall(http_server, no_sleep):
    _PlanHandler.plan = [404]
    results = smoke([_url(http_server, "/missing")])
    assert results[0].ok is False
    assert results[0].status == 404
    assert results[0].elapsed_ms >= 0
    assert smoke_passed(results) is False  # 任一非 200 即整体失败


def test_retry_eventually_green(http_server, no_sleep):
    _PlanHandler.plan = [500, 500, 200]
    results = smoke([_url(http_server, "/flaky")], retries=3)
    assert results[0].ok is True
    assert results[0].status == 200
    assert len(_PlanHandler.hits) == 3  # 两次失败 + 一次成功
    assert len(no_sleep) == 2  # 每次重试前退避一次
    assert smoke_passed(results) is True


def test_retry_exhausted_still_fails(http_server, no_sleep):
    _PlanHandler.plan = [500]  # 恒 500
    results = smoke([_url(http_server, "/boom")], retries=2)
    assert results[0].ok is False
    assert results[0].status == 500
    assert len(_PlanHandler.hits) == 3  # 首次 + 2 次重试
    assert len(no_sleep) == 2
    assert smoke_passed(results) is False


def test_connection_error_retried_then_fails(monkeypatch, no_sleep):
    # 连接类失败(status=None)参与重试;注入 _fetch_status 保持用例确定且快速
    # (本机对已关闭端口实测单次 urlopen 约 2s,真实延迟不应拖慢单测)。
    calls: list[str] = []
    def refused(url, timeout):
        calls.append(url)
        return None

    monkeypatch.setattr(deploy, "_fetch_status", refused)
    results = smoke(["http://127.0.0.1:9/"], retries=1)
    assert results[0].ok is False
    assert results[0].status is None
    assert calls == ["http://127.0.0.1:9/", "http://127.0.0.1:9/"]  # 首次+1 重试
    assert len(no_sleep) == 1


def test_fetch_status_connection_error_returns_none(monkeypatch):
    def boom(url, timeout):
        raise urllib.error.URLError("conn refused")

    monkeypatch.setattr(deploy._urlrequest, "urlopen", boom)
    assert deploy._fetch_status("http://x/", 5.0) is None


def test_custom_expect(http_server, no_sleep):
    _PlanHandler.plan = [201]
    results = smoke([_url(http_server, "/created")], expect=201)
    assert results[0].ok is True
    assert results[0].status == 201


def test_empty_urls_list():
    assert smoke([]) == []
    assert smoke_passed([]) is False  # 无冒烟证据保守判负


# --- F6:.env 差异仅 key 名(design §2.4) ---


def test_env_key_diff_only_key_names(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text("A=secret-value-1\nB=secret-value-2\n", encoding="utf-8")
    diff = env_key_diff(example, {"A", "C"})
    assert diff == ["B", "C"]  # 对称差、按名排序
    blob = "|".join(diff)
    assert "secret-value" not in blob  # 值永不进输出(F6)


def test_env_key_diff_ignores_comments_blank_export(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text(
        "# 注释行\n\nA=1\nexport B=2\n   C   =  3\nD\n", encoding="utf-8")
    assert env_key_diff(example, {"A", "B", "C", "D"}) == []


def test_env_key_diff_no_diff_when_keys_equal(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text("A=1\nB=2\n", encoding="utf-8")
    assert env_key_diff(example, {"A", "B"}) == []


def test_env_key_diff_deterministic_sorted(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text("Z=1\nA=2\nM=3\n", encoding="utf-8")
    assert env_key_diff(example, {"A"}) == ["M", "Z"]


def test_env_key_diff_missing_example_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        env_key_diff(tmp_path / "ghost.env.example", {"A"})


# --- requirements 哈希差异(design §2.3) ---


def test_requirements_sha_stable_and_content_sensitive(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("flask\npyyaml\n", encoding="utf-8")
    h1 = requirements_sha(req)
    assert h1 == requirements_sha(req)  # 同内容哈希稳定
    req.write_text("flask\npyyaml\n# 新增注释\n", encoding="utf-8")
    assert requirements_sha(req) != h1  # 内容变哈希变


def test_requirements_sha_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        requirements_sha(tmp_path / "ghost-requirements.txt")


def test_requirements_changed_matches_baseline(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("flask==3.0\n", encoding="utf-8")
    baseline = requirements_sha(req)
    assert requirements_changed(req, baseline) is False
    assert requirements_changed(req, "deadbeef" * 8) is True


def test_requirements_changed_missing_baseline_is_changed(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("flask\n", encoding="utf-8")
    assert requirements_changed(req, None) is True  # 首装无基准:保守判差异
    assert requirements_changed(req, "") is True
    assert requirements_changed(req, "  ") is True
