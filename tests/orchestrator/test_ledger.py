from datetime import datetime, timezone
from orchestrator.daemon.ledger import (
    append_ledger, ds_day_cost, ds_daily_exceeded, ds_ticket_cost,
    k3_budget_exceeded, k3_week_tokens,
)

CFG = {"budgets": {"k3_week_token_budget": 1000, "ds_daily_cny": 5}}


def test_append_and_week_sum(pool):
    append_ledger(pool, "k3", 300, "tokens", "T-1", "pm", "k3")
    append_ledger(pool, "k3", 200, "tokens", "T-1", "architect", "k3")
    append_ledger(pool, "deepseek", 1.5, "cny", "T-1", "dev", "deepseek-v4-pro")
    assert k3_week_tokens(pool) == 500
    assert ds_day_cost(pool) == 1.5
    assert ds_ticket_cost(pool, "T-1") == 1.5


def test_budget_flags(pool):
    assert not k3_budget_exceeded(pool, CFG)
    append_ledger(pool, "k3", 1001, "tokens", "T-1", "pm", "k3")
    assert k3_budget_exceeded(pool, CFG)
    assert not ds_daily_exceeded(pool, CFG)
    append_ledger(pool, "deepseek", 6.0, "cny", "T-2", "dev", "deepseek-v4-pro")
    assert ds_daily_exceeded(pool, CFG)


def test_empty_ledger(pool):
    assert k3_week_tokens(pool) == 0
    assert ds_day_cost(pool) == 0.0
