#!/usr/bin/env bash
# S1 冒烟入口(契约要求 .sh):调用 smoke.py(venv python)
set -e
apps/api/.venv/Scripts/python.exe docs/specs/T-2026-0829-005-smoke.py "$@"
