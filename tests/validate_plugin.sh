#!/usr/bin/env bash
# validate_plugin.sh — 插件结构静态校验;新增产物在此追加检查
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ROOTW="$(cd "$(dirname "$0")/.." && pwd -W)"   # Windows 风格(d:/...),内嵌 python 代码必须用此值
fail=0
err() { echo "VALIDATE FAIL: $1"; fail=1; }

# 1. JSON 合法性
python -c "import json;d=json.load(open(r'$ROOTW/.claude-plugin/plugin.json',encoding='utf-8'));assert d.get('name')=='ai-factory'" \
  || err "plugin.json 非法"
python -c "import json;json.load(open(r'$ROOTW/hooks/hooks.json',encoding='utf-8'))" \
  || err "hooks.json 非法"
python -c "import json;d=json.load(open(r'$ROOTW/.claude-plugin/marketplace.json',encoding='utf-8'));assert d.get('plugins')" \
  || err "marketplace.json 非法"

# 2. 无 CRLF(.sh 文件)
while IFS= read -r f; do
  if head -c 2000 "$f" | grep -q $'\r'; then err "CRLF 行尾: $f"; fi
done < <(find "$ROOT" -name '*.sh' -not -path '*/tmp/*')

# 3. SKILL.md 前置元数据(name + description)
for s in "$ROOT"/skills/*/SKILL.md; do
  [ -e "$s" ] || continue
  head -5 "$s" | grep -q '^name:' || err "$s 缺 name"
  head -5 "$s" | grep -q '^description:' || err "$s 缺 description"
done

# 4. agents 前置元数据
for a in "$ROOT"/agents/*.md; do
  [ -e "$a" ] || continue
  head -6 "$a" | grep -q '^name:' || err "$a 缺 name"
  head -6 "$a" | grep -q '^tools:' || err "$a 缺 tools"
done

# 5. hooks.json 引用的脚本存在(python 在 Windows 输出 \r\n,必须 tr 剥离)
for p in $(python -c "
import json,sys
sys.stdout.reconfigure(encoding='utf-8',newline='\n')
d=json.load(open(r'$ROOTW/hooks/hooks.json',encoding='utf-8'))
for ev,entries in d.get('hooks',{}).items():
    for e in entries:
        for h in e.get('hooks',[]):
            cmd=h.get('command','')
            if 'CLAUDE_PLUGIN_ROOT' in cmd:
                print(cmd.split('CLAUDE_PLUGIN_ROOT}/')[-1])
" | tr -d '\r'); do
  [ -f "$ROOT/$p" ] || err "hooks.json 引用缺失脚本: $p"
done

# 6. 模板存在性与合法性
for t in stack-profile.yaml claude-md.template.md backlog.template.md state.template.json \
         memory-index.template.md rules-registry.md proposal.template.md prd.template.md design.template.md; do
  [ -f "$ROOT/templates/$t" ] || err "缺模板: $t"
done
python -c "import json;json.load(open(r'$ROOTW/templates/state.template.json',encoding='utf-8'))" \
  || err "state.template.json 非法"

# 7. 门禁清单
for n in 1 2 3 4 5; do
  [ -f "$ROOT/templates/gate-checklists/phase$n-gate.md" ] || err "缺门禁清单 phase$n"
done

# 8. 文档存在且非空
for d in architecture.md adoption-guide.md mes-migration-guide.md; do
  [ -s "$ROOT/docs/$d" ] || err "缺文档: docs/$d"
done

[ "$fail" -eq 0 ] && echo "VALIDATE PASS"
exit "$fail"
