# 模型网关 v1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development。Steps 用 checkbox。

**Goal:** 密钥统一收编(D:\Tool\keys\)+ kimi-relay 升级为带周水位统计的模型网关 + 编排器配额闸对接真实水位 + dsh 双 provider(GLM/DeepSeek)落地。

**Architecture:** 两个改动面:D:\Tool(relay,Node 单文件无依赖,本计划为其 git init)与 ai-factory 仓库(orchestrator 侧)。密钥全部收进 `D:\Tool\keys\*.env`(格式 `KEY=sk-...`),不进 git、不进全局环境变量;dsh adapter 读 key 文件注入子进程 env。编排器 k3 配额闸从静态预算改为优先读网关 `/__stats` 周滚动 token 数。

**Tech Stack:** Node(系统已装,relay 在跑)、Python 3.11、pytest

**Spec:** `docs/superpowers/specs/2026-08-19-dual-harness-orchestrator-design.md` §5.3(双资源台账)+ 会话确认:k3 双 key 为双人共享池,编排器是"有礼貌的消费者";GLM 7 天免费额度作对照组

## Global Constraints

- 密钥只允许出现在 `D:\Tool\keys\*.env`;任何代码、测试、git 历史中不得硬编码 key 值(k3 迁移后立即从 kimi-relay.js 删除)
- `D:\Tool\.gitignore` 必须含 `keys/`、`relay-stats.json`、`key.txt`
- relay 保持零依赖(纯 Node 标准库);端口默认 8787,支持 `PORT` 环境变量覆盖(测试用)
- Python 侧:encoding="utf-8",写文件 newline="\n";subprocess 加 encoding="utf-8", errors="replace"
- 既有 61 个 pytest 全绿;relay 用 `node --test`
- ai-factory 分支 `feature/model-gateway`;D:\Tool 单独 git 仓库(main)

---

### Task 1: keys 目录 + relay 读 key 文件 + D:\Tool git 化

**Files:**
- Create: `D:\Tool\keys\k3-a.env`、`k3-b.env`(值从 kimi-relay.js 现有 BACKENDS 迁移)、`glm.env`、`deepseek.env`(占位 `KEY=TODO-FILL`)
- Modify: `D:\Tool\kimi-relay.js`(删硬编码 key,改启动时读 keys 文件;加 PORT env)
- Create: `D:\Tool\.gitignore`、`D:\Tool\test\relay-keys.test.js`
- `D:\Tool` git init

**Interfaces:**
- Produces:
  - key 文件格式:每行 `KEY=sk-...`(允许 `#` 注释、空行)
  - relay 新增:`loadKey(name)` — 读 `D:\Tool\keys\<name>.env` 的 `KEY=` 值,文件缺失或无 KEY 行时**启动报错并列出缺哪些**(不误用空 key)
  - `PORT = process.env.PORT || 8787`
  - BACKENDS 定义改为 `{ name, base, keyFile, model }`,启动时 resolve

- [ ] **Step 1: 建 keys 目录与 .gitignore**

```bash
mkdir -p /d/Tool/keys
```

`.gitignore`(D:\Tool):

```
keys/
relay-stats.json
key.txt
node_modules/
```

k3-a.env / k3-b.env:从 kimi-relay.js 第 7-8 行迁移(kimi1→k3-a,kimi2→k3-b),格式:

```
# k3 账号A(共享池)
KEY=sk-kimi-...
```

glm.env / deepseek.env:

```
# TODO: 用户填入后删除本行
KEY=TODO-FILL
```

- [ ] **Step 2: 写失败测试** `D:\Tool\test\relay-keys.test.js`

```js
const { test } = require('node:test');
const assert = require('node:assert');
const { spawn } = require('child_process');

test('relay 启动并暴露两个后端', async () => {
  const child = spawn('node', ['D:\\Tool\\kimi-relay.js'], {
    env: { ...process.env, PORT: '18787' }, stdio: 'pipe',
  });
  try {
    // 等就绪
    for (let i = 0; i < 50; i++) {
      try {
        const r = await fetch('http://127.0.0.1:18787/__status');
        const j = await r.json();
        assert.equal(j.backends.length, 2);
        return;
      } catch { await new Promise(r => setTimeout(r, 200)); }
    }
    assert.fail('relay 未在 10s 内就绪');
  } finally { child.kill(); }
});

test('缺 key 文件时启动报错且指明缺失', async () => {
  // 用临时 KEYS_DIR 覆盖测试
  const child = spawn('node', ['D:\\Tool\\kimi-relay.js'], {
    env: { ...process.env, PORT: '18788', KEYS_DIR: 'D:\\Tool\\keys-nonexist' },
    stdio: 'pipe',
  });
  let out = '';
  child.stderr.on('data', c => out += c);
  child.stdout.on('data', c => out += c);
  const code = await new Promise(r => child.on('exit', r));
  assert.notEqual(code, 0);
  assert.match(out, /k3-a/);
});
```

(relay 相应支持 `KEYS_DIR = process.env.KEYS_DIR || 'D:\\Tool\\keys'`)

- [ ] **Step 3: 改造 kimi-relay.js**

配置区改为:

```js
const KEYS_DIR = process.env.KEYS_DIR || 'D:\\Tool\\keys';
const PORT = Number(process.env.PORT || 8787);

function loadKey(name) {
  const file = `${KEYS_DIR}\\${name}.env`;
  let txt;
  try { txt = fs.readFileSync(file, 'utf8'); }
  catch { throw new Error(`key 文件缺失: ${file}`); }
  const m = txt.match(/^KEY=(.+)$/m);
  if (!m) throw new Error(`key 文件无 KEY 行: ${file}`);
  return m[1].trim();
}

const BACKENDS = [
  { name: 'kimi1', base: 'https://api.kimi.com/coding', keyFile: 'k3-a', model: null },
  { name: 'kimi2', base: 'https://api.kimi.com/coding', keyFile: 'k3-b', model: null },
];

// 启动时 resolve,缺失即退出并列出
const missing = [];
BACKENDS.forEach(b => {
  try { b.key = loadKey(b.keyFile); }
  catch (e) { missing.push(e.message); }
});
if (missing.length) { console.error('[relay] key 缺失:\n' + missing.join('\n')); process.exit(1); }
```

`tryBackend` 中 `b.key` 引用不变;listen 用 `PORT`。删除原硬编码 key 行。

- [ ] **Step 4: 跑测试**

```bash
cd /d/Tool && node --test test/
```

Expected: 2 passed(注意:8787 上正在跑旧 relay,测试用独立端口,不冲突)

- [ ] **Step 5: git init + commit(两个仓库)**

```bash
cd /d/Tool && git init -b main && git add -A && git commit -m "relay: key 外置到 keys/ 目录 + PORT/KEYS_DIR 可配"
```

ai-factory 侧仅提交本计划文档(另行)。

---

### Task 2: relay 周滚动 token 窗口

**Files:**
- Create: `D:\Tool\relay-stats.js`(可 require 的纯逻辑模块)
- Modify: `D:\Tool\kimi-relay.js`(require 它)
- Test: `D:\Tool\test\relay-stats.test.js`

**Interfaces:**
- Produces:
  - `isoWeek(d: Date) -> string`(如 "2026-W35")
  - `createBackendStats() -> {requests, errors, inputTokens, outputTokens, lastUsed, weekId, weekInputTokens, weekOutputTokens}`
  - `recordUsage(st, inT, outT, now = new Date())` — 若 `st.weekId !== isoWeek(now)` 则周窗口清零再累计;同时累计总量
  - relay 的 `/__stats` 输出自然携带周字段

- [ ] **Step 1: 写失败测试**

```js
const { test } = require('node:test');
const assert = require('node:assert');
const { isoWeek, createBackendStats, recordUsage } = require('D:\\Tool\\relay-stats.js');

test('isoWeek 格式', () => {
  assert.match(isoWeek(new Date('2026-08-27T00:00:00Z')), /^\d{4}-W\d{2}$/);
});

test('同周累计', () => {
  const st = createBackendStats();
  recordUsage(st, 100, 50, new Date('2026-08-27T01:00:00Z'));
  recordUsage(st, 200, 60, new Date('2026-08-27T02:00:00Z'));
  assert.equal(st.weekInputTokens, 300);
  assert.equal(st.inputTokens, 300);
});

test('跨周窗口清零但总量保留', () => {
  const st = createBackendStats();
  recordUsage(st, 300, 100, new Date('2026-08-20T01:00:00Z'));  // 上周
  recordUsage(st, 50, 10, new Date('2026-08-27T01:00:00Z'));   // 本周
  assert.equal(st.weekInputTokens, 50);
  assert.equal(st.inputTokens, 350);
});
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现 relay-stats.js**

```js
function isoWeek(d) {
  const t = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  const day = (t.getUTCDay() + 6) % 7;
  t.setUTCDate(t.getUTCDate() - day + 3);
  const firstThu = new Date(Date.UTC(t.getUTCFullYear(), 0, 4));
  const week = 1 + Math.round(((t - firstThu) / 86400000 - 3 + ((firstThu.getUTCDay() + 6) % 7)) / 7);
  return `${t.getUTCFullYear()}-W${String(week).padStart(2, '0')}`;
}

function createBackendStats() {
  return { requests: 0, errors: 0, inputTokens: 0, outputTokens: 0,
           lastUsed: null, weekId: null, weekInputTokens: 0, weekOutputTokens: 0 };
}

function recordUsage(st, inT, outT, now = new Date()) {
  const w = isoWeek(now);
  if (st.weekId !== w) { st.weekId = w; st.weekInputTokens = 0; st.weekOutputTokens = 0; }
  st.inputTokens += inT; st.outputTokens += outT;
  st.weekInputTokens += inT; st.weekOutputTokens += outT;
  st.lastUsed = now.toISOString();
}

module.exports = { isoWeek, createBackendStats, recordUsage };
```

kimi-relay.js:stats 初始化与 `up.on('end')` 累计处改用该模块(存量 relay-stats.json 字段兼容:读入时缺周字段补默认)。

- [ ] **Step 4: 跑测试** → `node --test test/` 全过
- [ ] **Step 5: Commit(D:\Tool)** —— `relay: 周滚动 token 窗口(共享池水位)`

---

### Task 3: 编排器 gateway.py —— 配额闸读真实水位

**Files:**
- Create: `orchestrator/daemon/gateway.py`
- Modify: `orchestrator/daemon/runner.py`(配额闸改走 gateway 包装)、`orchestrator.yaml`(加 gateway.url)
- Test: `tests/orchestrator/test_gateway.py`

**Interfaces:**
- Produces:
  - `gateway_week_tokens(url: str, timeout: float = 5.0) -> int | None`(GET `<url>/__stats`,合计各后端 weekInputTokens+weekOutputTokens;任何异常返回 None)
  - `k3_effective_week_tokens(pool, cfg) -> int`(cfg 有 gateway.url 且可达 → 网关值;否则回退 ledger.k3_week_tokens)
  - runner 的 `k3_budget_exceeded` 调用替换为基于 `k3_effective_week_tokens` 的判断(阈值仍 cfg["budgets"]["k3_week_token_budget"])

`orchestrator.yaml` 追加:

```yaml
gateway:
  url: http://127.0.0.1:8787
```

- [ ] **Step 1: 写失败测试(起本地假 HTTP 服务)**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**

```python
"""模型网关对接:k3 共享池的真实周水位。spec §5.3 双资源台账的联网版。"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from orchestrator.daemon.ledger import k3_week_tokens


def gateway_week_tokens(url: str, timeout: float = 5.0) -> int | None:
    try:
        with urllib.request.urlopen(f"{url}/__stats", timeout=timeout) as r:
            stats = json.loads(r.read().decode("utf-8"))
        return sum(int(v.get("weekInputTokens", 0)) + int(v.get("weekOutputTokens", 0))
                   for v in stats.values())
    except Exception:
        return None


def k3_effective_week_tokens(pool: Path, cfg: dict, timeout: float = 5.0) -> int:
    url = (cfg.get("gateway") or {}).get("url")
    if url:
        remote = gateway_week_tokens(url, timeout=timeout)
        if remote is not None:
            return remote
    return k3_week_tokens(pool)
```

runner.py:`k3_budget_exceeded(pool, cfg)` 调用处改为 `k3_effective_week_tokens(pool, cfg) > cfg["budgets"]["k3_week_token_budget"]`(import 更新;ledger.k3_budget_exceeded 保留供无网关场景,k3_effective 内部已回退)。

- [ ] **Step 4: 跑测试确认通过** → 4 passed;全量 61+ 全绿
- [ ] **Step 5: Commit(ai-factory)** —— `feat(orchestrator): 配额闸对接网关周水位(共享池礼貌消费)`

---

### Task 4: dsh adapter 落地(shim + key 注入 + 模型维度)

**Files:**
- Modify: `orchestrator/adapters/dsh.py`、`orchestrator/adapters/base.py`(TaskPacket 加 `model: str | None = None`)、`orchestrator/daemon/slicer.py`(make_packet 透传 model)、`orchestrator/daemon/runner.py`(ROLE_ROUTING 值改为 (adapter, model) 或新增 ROLE_MODEL 表)
- Create: `orchestrator/adapters/dsh_profiles.py`(生成 dsh provider 配置)
- Modify: `orchestrator.yaml`(加 keys_dir、models 段)
- Test: `tests/orchestrator/test_dsh_adapter.py` 追加

**Interfaces:**
- Produces:
  - `DshAdapter(keys_dir: Path | None = None, profile: str = "headless")`;run 时:exe=shutil.which("dsh") 或 "dsh";env = os.environ + 从 `<keys_dir>/deepseek.env` 读出的 `DEEPSEEK_API_KEY`(KEY= 值映射到 `DEEPSEEK_API_KEY` 名)+ zhipu 同理;命令 `dsh --profile <profile> <prompt>`;FileNotFoundError 包装为 HarnessResult(status="failed", output="dsh 未安装")
  - `ROLE_MODEL = {"dev": "deepseek-v4-flash", "qa": "deepseek-v4-flash", "release": "deepseek-v4-flash", "sre": "deepseek-v4-flash"}`(GLM 对照实验时切 glm-5.3-flash)
  - `dsh_profiles.settings_yaml(cfg) -> str`:生成含 deepseek/zhipu 双 provider 的 settings.yaml 文本(apiKeyEnv 引用 env 名,不含 key 值)

`orchestrator.yaml` 追加:

```yaml
keys_dir: D:/Tool/keys
models:
  dev: deepseek-v4-flash
  qa: deepseek-v4-flash
```

- [ ] **Step 1: 写失败测试**

```python
import subprocess
from pathlib import Path
from unittest.mock import patch
from orchestrator.adapters.base import TaskPacket
from orchestrator.adapters.dsh import DshAdapter
from orchestrator.adapters.dsh_profiles import settings_yaml


def test_env_injected_from_keys_dir(tmp_path):
    (tmp_path / "deepseek.env").write_text("KEY=sk-test-123\n", encoding="utf-8")
    fake = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
    with patch("subprocess.run", return_value=fake) as m:
        DshAdapter(keys_dir=tmp_path).run(
            TaskPacket(role="dev", prompt="p", workdir=tmp_path, budget={}))
    env = m.call_args.kwargs["env"]
    assert env["DEEPSEEK_API_KEY"] == "sk-test-123"


def test_missing_dsh_wrapped(tmp_path):
    with patch("shutil.which", return_value=None), \
         patch("subprocess.run", side_effect=FileNotFoundError):
        r = DshAdapter().run(TaskPacket(role="dev", prompt="p", workdir=tmp_path, budget={}))
    assert r.status == "failed" and "dsh" in r.output


def test_settings_yaml_has_both_providers():
    txt = settings_yaml({})
    assert "deepseek" in txt and "zhipu" in txt
    assert "DEEPSEEK_API_KEY" in txt and "ZHIPU_API_KEY" in txt
    assert "sk-" not in txt   # 不含任何 key 值
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现要点**

dsh.py:

```python
import os
import shutil
import subprocess
from pathlib import Path

from orchestrator.adapters.base import HarnessAdapter, HarnessResult, TaskPacket

PROVIDER_ENV = {"deepseek": "DEEPSEEK_API_KEY", "zhipu": "ZHIPU_API_KEY"}


class DshAdapter(HarnessAdapter):
    name = "dsh"

    def __init__(self, keys_dir: Path | None = None, profile: str = "headless"):
        self.keys_dir = Path(keys_dir) if keys_dir else None
        self.profile = profile

    def _env(self) -> dict:
        env = dict(os.environ)
        if self.keys_dir:
            for provider, env_name in PROVIDER_ENV.items():
                f = self.keys_dir / f"{provider}.env"
                if f.exists():
                    for line in f.read_text(encoding="utf-8").splitlines():
                        if line.startswith("KEY=") and not line.startswith("#"):
                            env[env_name] = line[4:].strip()
        return env

    def run(self, packet: TaskPacket) -> HarnessResult:
        exe = shutil.which("dsh") or "dsh"
        profile = f"headless-{packet.model}" if packet.model else self.profile
        cmd = [exe, "--profile", profile, packet.prompt]
        try:
            r = subprocess.run(cmd, cwd=packet.workdir, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=packet.timeout, env=self._env())
        except FileNotFoundError:
            return HarnessResult(status="failed", output="dsh 未安装(shutil.which 未找到)")
        except subprocess.TimeoutExpired:
            return HarnessResult(status="timeout", output=f"timeout {packet.timeout}s")
        output = (r.stdout + r.stderr)[:4000]
        return HarnessResult(status="done" if r.returncode == 0 else "failed", output=output)
```

dsh_profiles.py:`settings_yaml(cfg)` 返回(逐字):

```yaml
llm-pi-ai:
  providers:
    deepseek:
      apiKeyEnv: DEEPSEEK_API_KEY
      api: openai-completions
      baseURL: https://api.deepseek.com/v1
      models:
        - id: deepseek-v4-flash
        - id: deepseek-v4-flash-vision-exp
          input: [text, image]
    zhipu:
      apiKeyEnv: ZHIPU_API_KEY
      api: openai-completions
      baseURL: https://open.bigmodel.cn/api/paas/v4
      models:
        - id: glm-5.3-flash
          input: [text, image]
```

runner.py:`ROLE_ROUTING` 保留;新增 `ROLE_MODEL`(上表);run_dev_tasks 中 make_packet 后 `packet.model = ROLE_MODEL.get("dev")`;DshAdapter 实例化点(cli.py advance)传 `keys_dir=cfg.get("keys_dir")`。

- [ ] **Step 4: 跑测试确认通过** → 全绿
- [ ] **Step 5: Commit** —— `feat(orchestrator): dsh adapter shim/key 注入/模型维度 + provider 配置生成`

---

### Task 5: 集成验证(slow,人工协同)

**前置**:用户已填 `D:\Tool\keys\deepseek.env`(GLM 选填)

- [ ] **Step 1: 重启 relay 生效新代码**

```bash
# 找 8787 占用 PID 并结束(只杀监听该端口的进程)
netstat -ano | grep ':8787' | grep LISTENING
taskkill //PID <pid> //F
# 用计划任务同款方式重启(或前台 nohup 验证)
cd /d/Tool && nohup node kimi-relay.js > relay.log 2>&1 &
curl -s http://127.0.0.1:8787/__status
```

- [ ] **Step 2: claude -p 经 relay 真实调用 + 水位验证**

```bash
curl -s http://127.0.0.1:8787/__stats   # 记 baseline
cd /d/workspace/tmp/orc-e2e && claude -p "只回复两个字:就绪" --output-format json
curl -s http://127.0.0.1:8787/__stats   # weekTokens 应增长
```

- [ ] **Step 3: dsh 真实调用(DeepSeek)**

按 T4 生成的 settings 配好 dsh profile 后:

```bash
cd /d/workspace/ai-factory
python -c "from orchestrator.adapters.dsh import DshAdapter; from orchestrator.adapters.base import TaskPacket; from pathlib import Path; r = DshAdapter(keys_dir=Path('D:/Tool/keys')).run(TaskPacket(role='dev', prompt='只回复两个字:就绪', workdir=Path('d:/workspace/tmp/orc-e2e'), budget={}, timeout=300)); print(r.status); print(r.output[:200])"
```

- [ ] **Step 4: GLM 对照(若 key 已填)** —— 同 Step 3,profile 切 zhipu
- [ ] **Step 5: 结果记录 + commit** —— 验证结果(各 provider status/耗时)记入报告;ai-factory 提交收尾

---

## Self-Review 记录

- **覆盖**:密钥统一(T1)、周水位(T2)、配额闸对接(T3,spec §5.3 共享池语义)、dsh 落地(T4,M2 走查前置清单的 dsh shim + provider 配置)、真实验证(T5)
- **类型一致**:loadKey/isoWeek/recordUsage/gateway_week_tokens/k3_effective_week_tokens/DshAdapter(keys_dir, profile)/settings_yaml 跨任务签名一致
- **有意留白**:relay 多模型路由(k3 以外的模型经 relay)暂不做 —— GLM/DS 由 dsh 直连官方端点,relay 专职 k3 池;GLM 对照实验的 A/B 任务派发在走查后定
