#!/usr/bin/env bash
# init-project.sh — 在目标目录生成 AI Factory 骨架
set -e
DIR="."; NAME=""; PTYPE=""; LANG="python"; LINT=""; TESTC=""; FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dir) DIR="$2"; shift 2;;
    --name) NAME="$2"; shift 2;;
    --type) PTYPE="$2"; shift 2;;
    --language) LANG="$2"; shift 2;;
    --lint-cmd) LINT="$2"; shift 2;;
    --test-cmd) TESTC="$2"; shift 2;;
    --force) FORCE=1; shift;;
    *) echo "未知参数: $1" >&2; exit 1;;
  esac
done
[ -z "$NAME" ] && { echo "缺少 --name" >&2; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ "$FORCE" -ne 1 ]; then
  # 防覆盖(E3):关键文件已存在 → 拒绝
  for f in CLAUDE.md backlog.md stack-profile.yaml .claude/state.json; do
    if [ -e "$DIR/$f" ]; then
      echo "ai-factory: $DIR/$f 已存在,拒绝覆盖。" >&2
      echo "  - 想合并:请手工把模板章节追加到现有文件" >&2
      echo "  - 想重建:备份后加 --force 重跑" >&2
      exit 1
    fi
  done
  # 项目隔离(E3):子目录已含独立项目骨架 → 目标是多项目容器,拒绝在容器根初始化
  for sub in "$DIR"/*/; do
    [ -d "$sub" ] || continue
    for f in CLAUDE.md backlog.md stack-profile.yaml .claude/state.json; do
      if [ -e "$sub$f" ]; then
        echo "ai-factory: $DIR 疑似多项目容器(${sub}已含项目骨架 $f),拒绝在容器根初始化。" >&2
        echo "  - 正确做法:一目录一项目,用 --dir \"$DIR/<项目目录名>\" 指定独立子目录" >&2
        echo "  - 确需在容器根初始化:加 --force" >&2
        exit 1
      fi
    done
  done
fi

mkdir -p "$DIR/.claude/memory" "$DIR/docs/superpowers/specs" "$DIR/docs/superpowers/plans"

render() {  # render <模板名> <输出相对路径>
  sed -e "s|{{PROJECT_NAME}}|$NAME|g" \
      -e "s|{{PROJECT_TYPE}}|$PTYPE|g" \
      -e "s|{{LANGUAGE}}|$LANG|g" \
      -e "s|{{LINT_CMD}}|$LINT|g" \
      -e "s|{{TEST_CMD}}|$TESTC|g" \
      "$ROOT/templates/$1" > "$DIR/$2"
}

render claude-md.template.md CLAUDE.md
render backlog.template.md backlog.md
render state.template.json .claude/state.json
render stack-profile.yaml stack-profile.yaml
render memory-index.template.md .claude/memory/MEMORY.md
render rules-registry.md .claude/rules-registry.md

# 插件启用补齐:目标目录无 .claude/settings.json 时补写(已有则不动,不覆盖)
if [ ! -e "$DIR/.claude/settings.json" ]; then
  cat > "$DIR/.claude/settings.json" <<'EOF'
{
  "enabledPlugins": {
    "ai-factory@ai-factory-local": true
  }
}
EOF
  echo "ai-factory: 已补写 $DIR/.claude/settings.json(插件启用;marketplace 名称不同请手工调整)"
fi

echo "ai-factory 骨架已生成于 $DIR"
echo "下一步:审阅 stack-profile.yaml,然后阅读 CLAUDE.md"
