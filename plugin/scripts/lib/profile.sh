#!/usr/bin/env bash
# profile.sh — 解析 stack-profile.yaml(扁平二级 YAML,值含中文/空格/冒号均可)
# 用法: source 本文件后调用 profile_get / profile_array(需要 python 在 PATH)

profile_get() {
  local file="$1" path="$2"
  [ -f "$file" ] || return 1
  python - "$file" "$path" <<'PY'
import sys, re
sys.stdout.reconfigure(encoding="utf-8", newline="\n")   # Git Bash on Windows:默认 cp936 且 \r\n,必须强制
file, path = sys.argv[1], sys.argv[2]
sec, key = path.split(".", 1)
cur = None
for line in open(file, encoding="utf-8"):
    if re.match(r"^[A-Za-z_][\w]*:", line):
        cur = line.split(":", 1)[0].strip()
        continue
    m = re.match(r"^\s+([A-Za-z_][\w]*):\s*(.*?)\s*$", line)
    if m and cur == sec and m.group(1) == key:
        v = re.sub(r"\s+#.*$", "", m.group(2)).strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]   # 只剥外层成对引号,保留内层引号
        if v and v != "null":
            print(v)
        break
PY
}

profile_array() {
  local raw
  raw=$(profile_get "$1" "$2") || return 1
  raw="${raw#[}"; raw="${raw%]}"
  printf '%s' "$raw" | tr ',' ' ' | tr -d "\"'" | tr -s ' ' | sed 's/^ //; s/ $//'
}
