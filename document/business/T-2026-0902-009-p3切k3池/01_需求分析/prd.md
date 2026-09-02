# PRD:P3 执行层切 k3 订阅池

## Why

- DS 余额 0,runner 断粮;k3 四订阅账号边际成本 0,昨天 ¥16/91M tokens 的消耗可全转
- zen-k3 翻译层(006)已证明 Anthropic↔OpenAI 翻译在 failover 组可行——DS/GLM 同为 OpenAI 兼容,同法可挂
- boss 决策(2026-09-02):B 方案=k3 主力 + 付费通道冷却期溢出

## What

1. relay:failover 组 = kimi1/2/3/4 → glm-flash(translate)→ ds-flash(translate)→ zen-k3(translate,既有)
2. runner:dev/qa/release/sre 角色路由 k3 适配器;dev 真实小切片首验(过不了回退路由)
3. k3 水位闸 150M→600M,明放 warn-only 观察一周(复审 2026-09-09)
4. Dashboard「DS 成本(现金)」标注"仅 DeepSeek 通道,k3 池按周水位计"

## 验收标准

- node --test 全绿(4+3 后端断言;翻译层活集成)
- 顺位演练:伪造 kimi 全冷却 → 请求落 glm-flash;再冷却 glm → 落 ds-flash(如 DS 有余额;无余额则冷却到 zen-k3,记录行为)
- dev 小切片经 k3 适配器真实完成(TDD 流程跑通,产物真实)
- pytest 全绿;check-pool-load 0 bad;Dashboard 标注上线
