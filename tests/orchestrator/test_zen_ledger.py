"""T-2026-0901-001 Z3:zen-usage-ledger 周对账脚本测试。"""
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "zen_usage_ledger",
        Path(__file__).resolve().parents[2] / "scripts" / "zen-usage-ledger.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


zul = _load_script()


@pytest.fixture
def fake_relay():
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({
                "kimi1": {"weekInputTokens": 700, "weekOutputTokens": 200},
                "zen": {"weekId": "2026-W36",
                        "weekInputTokens": 1_000_000, "weekOutputTokens": 100_000},
                # T-2026-0901-006:翻译兜底后端同样计费,合计入账
                "zen-k3": {"weekId": "2026-W36",
                           "weekInputTokens": 500_000, "weekOutputTokens": 50_000},
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


@pytest.fixture
def sandbox(tmp_path, monkeypatch, fake_relay):
    """tmp ROOT:最小 orchestrator.yaml + 空 pool,指向假 relay。"""
    (tmp_path / "orchestrator.yaml").write_text(
        f"pool: pool\ngateway:\n  url: {fake_relay}\n"
        "rates:\n  opencode:\n    input_per_m: 21.6\n    output_per_m: 108.0\n",
        encoding="utf-8")
    (tmp_path / "pool").mkdir()
    monkeypatch.setattr(zul, "ROOT", tmp_path)
    return tmp_path


def test_fetch_zen_week(sandbox):
    week = zul.fetch_zen_week(zul.yaml.safe_load(
        (sandbox / "orchestrator.yaml").read_text(encoding="utf-8"))["gateway"]["url"])
    # zen + zen-k3 合计
    assert week == {"weekId": "2026-W36", "input": 1_500_000, "output": 150_000}


def test_week_cost_cny():
    # 1.5M in × ¥21.6 + 0.15M out × ¥108 = 32.4 + 16.2
    assert zul.week_cost_cny({"input": 1_500_000, "output": 150_000},
                             {"input_per_m": 21.6, "output_per_m": 108.0}) == 48.6


def test_dry_run_writes_nothing(sandbox, capsys):
    assert zul.main(["--dry-run"]) == 0
    assert not (sandbox / "pool" / "ledger.jsonl").exists()
    assert "¥48.6" in capsys.readouterr().out


def test_record_then_idempotent(sandbox, capsys):
    assert zul.main([]) == 0
    f = sandbox / "pool" / "ledger.jsonl"
    entries = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 1
    e = entries[0]
    assert e["resource"] == "opencode" and e["unit"] == "cny"
    assert e["amount"] == 48.6 and e["estimated"] is True
    assert e["tokens"]["weekId"] == "2026-W36"
    # 同周再跑:幂等跳过
    assert zul.main([]) == 0
    assert "已入过账" in capsys.readouterr().out
    assert len(f.read_text(encoding="utf-8").splitlines()) == 1
