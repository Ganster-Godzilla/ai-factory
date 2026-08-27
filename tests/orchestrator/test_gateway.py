import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from orchestrator.daemon.gateway import gateway_week_tokens, k3_effective_week_tokens
from orchestrator.daemon.ledger import append_ledger


@pytest.fixture
def fake_gateway():
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({
                "kimi1": {"weekInputTokens": 700, "weekOutputTokens": 200},
                "kimi2": {"weekInputTokens": 90, "weekOutputTokens": 10},
            }).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *a): pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_gateway_week_tokens(fake_gateway):
    assert gateway_week_tokens(fake_gateway) == 1000


def test_gateway_unreachable_returns_none():
    assert gateway_week_tokens("http://127.0.0.1:1", timeout=1) is None


def test_effective_prefers_gateway(pool, fake_gateway):
    append_ledger(pool, "k3", 50, "tokens", "T-1", "pm", "k3")
    cfg = {"gateway": {"url": fake_gateway}}
    assert k3_effective_week_tokens(pool, cfg) == 1000   # 网关优先,不是 50


def test_effective_fallback_local(pool):
    cfg = {"gateway": {"url": "http://127.0.0.1:1"}}
    append_ledger(pool, "k3", 42, "tokens", "T-1", "pm", "k3")
    assert k3_effective_week_tokens(pool, cfg, timeout=1) == 42


def test_effective_fallback_logs_event(pool):
    # Finding S1:网关配置了但不可达,回退本地台账时必须留 gateway_fallback 事件
    from orchestrator.daemon.events import read_events
    cfg = {"gateway": {"url": "http://127.0.0.1:1"}}
    append_ledger(pool, "k3", 42, "tokens", "T-1", "pm", "k3")
    assert k3_effective_week_tokens(pool, cfg, timeout=1) == 42
    evts = read_events(pool, "system")
    assert any(e["event"] == "gateway_fallback" and e["actor"] == "system"
               for e in evts)
