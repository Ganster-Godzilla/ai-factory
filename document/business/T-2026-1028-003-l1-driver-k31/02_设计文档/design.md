# 设计:T-2026-1028-003 L1 驾驶员模型切 k3.1-pro

## Architecture

```
runner._driver_for_level(ticket)          claude_code.ClaudeCodeAdapter
  L1    → 'k3.1-pro'  (本单变更)    →      DRIVER_MODELS ∪= {'k3.1-pro'}
  L2/L3 → 'k2.6'      (不变)        →      packet.model ∈ 白名单 → --model <m>
       │                                     │
       ▼                                     ▼
  claude -p --model k3.1-pro  →  relay :8787  →  defaultChain(未知 model)
                                              →  kimi1-4 透传(model:null)
                                              →  api.kimi.com/coding ✓ 已实证 200
```

关键事实(2026-10-28 生产 relay 实证,证据见 04_测试/验收报告.md):

- `POST /v1/messages {"model":"k3.1"}` → 400,endpoint 明示:可用 ID 为
  `k3`、`k3.1-pro`、`k3.1-pro-highspeed`
- `{"model":"k3.1-pro"}` → 200,content 带 thinking 块,usage 正常
- relay `ROUTES` 无 k3.1-pro 键 → 走 `defaultChain`(kimi1-4 → glm → zy-ds →
  ds-flash → zen-k3),与原 k3 完全同链;水位计量(kimi* 前缀)不受影响

## How

| 步 | 文件 | 改动 |
|---|---|---|
| 1 | tests/orchestrator/test_level.py | L1 driver 断言 `is None` → `== 'k3.1-pro'`;dispatch 注入断言同步(先红) |
| 2 | tests/orchestrator/test_claude_code_adapter.py | 白名单通过集加 `'k3.1-pro'`(先红) |
| 3 | orchestrator/daemon/runner.py | `_driver_for_level`:L1 返回 `'k3.1-pro'`,注释更新(后绿) |
| 4 | orchestrator/adapters/claude_code.py | `DRIVER_MODELS = {"k2.6", "gpt-6-astra", "k3.1-pro"}`(后绿) |
| 5 | scripts/canary-report.py | `DRIVER_OF["L1"] = "k3.1-pro"`(报告口径) |
| 6 | docs/orchestrator-guide.md | 路由表 L1 行驾驶员列更新 |
| 7 | 冒烟 | `claude -p --model k3.1-pro` 经 relay 真实出字 |

dsh 路径零触碰:`_driver_for_level` 返回值只经 DRIVER_MODELS 白名单变 `--model`;
dsh 的 `_model_for(cfg, role)`(orchestrator.yaml models.dev/qa=deepseek-v4-flash)不动。

## Checkpoints

- [ ] 步 1-2 后 `pytest test_level.py test_claude_code_adapter.py` **红**(证明断言咬现状)
- [ ] 步 3-4 后同命令**绿**
- [ ] `pytest tests/ -q` 全量绿
- [ ] `python -m pyflakes` 改动文件零告警
- [ ] `python scripts/check-complexity.py` 过闸(合 main 前)
- [ ] `python scripts/check-pool-load.py` 过闸(合 main 前)
- [ ] 冒烟输出非空且 is_error=false;relay /__stats kimi* 计数增长

## Rollback

单行还原 `runner._driver_for_level` L1 分支为 `None`(恢复 CLI 全局默认隐式决定),
revert 本单合并提交即可;relay/zen/水位口径本就未动,无连带回滚。
