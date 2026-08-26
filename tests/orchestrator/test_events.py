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
