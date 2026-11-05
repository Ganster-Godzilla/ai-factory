from orchestrator.daemon.events import append_event, read_events


def test_append_and_read(pool):
    append_event(pool, "T-2026-0819-001", "pm", "created", detail="探针草稿")
    append_event(pool, "T-2026-0819-001", "boss", "approved")
    events = read_events(pool, "T-2026-0819-001")
    assert [e["event"] for e in events] == ["created", "approved"]
    assert events[0]["actor"] == "pm"
    assert events[0]["detail"] == "探针草稿"
    assert "ts" in events[0]


def test_read_missing_returns_empty(pool):
    assert read_events(pool, "T-0000-0000-000") == []


def test_append_is_append_only(pool):
    append_event(pool, "T-1", "pm", "a")
    append_event(pool, "T-1", "pm", "b")
    assert len(read_events(pool, "T-1")) == 2


def test_append_event_writes_utf8_no_bom(pool):
    """T-2026-1104-001 G3:台账写手必须 UTF-8 无 BOM;
    BOM 会撞 404 处理器装死总览(0c4c587 读端已容错,本钉防写端回潮)。"""
    append_event(pool, "T-bom", "pm", "created", detail="首行")
    append_event(pool, "T-bom", "pm", "note", note="次行")
    path = pool / "tickets" / "T-bom.events.jsonl"
    raw = path.read_bytes()
    assert raw[:3] != b"\xef\xbb\xbf", "events.jsonl 写入带 BOM"
    lines = [l for l in raw.decode("utf-8").splitlines() if l.strip()]
    assert len(lines) == 2
    import json
    for line in lines:
        json.loads(line)
