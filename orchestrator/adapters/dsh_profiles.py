"""dsh provider 配置生成:settings.yaml 文本(apiKeyEnv 只引用 env 名,不落 key 值)。"""
from __future__ import annotations

_SETTINGS_YAML = """\
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
      baseURL: https://open.bigmodel.cn/api/coding/paas/v4   # GLM Coding 套餐专用端点(标准 /api/paas/v4 会 429 余额不足)
      models:
        - id: glm-5.3-flash
          input: [text, image]
"""


def settings_yaml(cfg: dict) -> str:
    return _SETTINGS_YAML
