import json
from datetime import datetime, timezone
from orchestrator.daemon.ledger import (
    append_ledger, ds_day_calls, ds_day_cost, ds_daily_exceeded, ds_ticket_cost,
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
    assert ds_day_calls(pool) == 0


# ---- 三字段口径对齐(T-2026-0828-003 D3):amount + tokens + calls ----

def test_entry_has_tokens_and_calls(pool):
    append_ledger(pool, "deepseek", 0.42, "cny", "T-1", "dev", "dsh",
                  tokens={"input": 1000, "output": 500})
    append_ledger(pool, "k3", 150, "tokens", "T-1", "pm", "k3")
    lines = (pool / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    d, k = json.loads(lines[0]), json.loads(lines[1])
    assert d["tokens"] == {"input": 1000, "output": 500} and d["calls"] == 1
    assert k["tokens"] == {} and k["calls"] == 1   # k3 侧结构一致,由 _record_cost 填 tokens


def test_ds_day_calls_counts_deepseek_calls(pool):
    append_ledger(pool, "deepseek", 0.1, "cny", "T-1", "dev", "dsh")
    append_ledger(pool, "deepseek", 0.2, "cny", "T-1", "qa", "dsh")
    append_ledger(pool, "k3", 100, "tokens", "T-1", "pm", "k3")   # k3 不计
    # 旧格式 entry(无 tokens/calls 字段):calls 按 1 兜底,与 entry 数等价
    legacy = {"ts": datetime.now(timezone.utc).isoformat(), "resource": "deepseek",
              "amount": 0.3, "unit": "cny", "ticket": "T-0", "role": "dev",
              "model": "deepseek-v4-pro"}
    with (pool / "ledger.jsonl").open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(legacy, ensure_ascii=False) + "\n")
    assert ds_day_calls(pool) == 3


def test_ds_day_calls_sums_explicit_calls(pool):
    # 未来批量写账(calls>1)按字段求和,不按行数
    append_ledger(pool, "deepseek", 0.5, "cny", "T-2", "dev", "dsh", calls=5)
    assert ds_day_calls(pool) == 5


def test_gates_fire_once_recorded(pool):
    # 缺口③回归:真实台账补上后,¥30 日线与 ¥10 工单帽自然生效(闸门逻辑零改动)
    cfg = {"budgets": {"k3_week_token_budget": 10**9, "ds_daily_cny": 5}}
    budget = {"token_cap_cny": 10.0}
    for _ in range(4):
        append_ledger(pool, "deepseek", 3.0, "cny", "T-1", "dev", "dsh",
                      tokens={"input": 600000, "output": 40000})
    assert ds_daily_exceeded(pool, cfg)                 # 12 > ¥5 日线
    assert ds_ticket_cost(pool, "T-1") > budget["token_cap_cny"]   # 12 > ¥10 帽
    assert ds_day_calls(pool) == 4
