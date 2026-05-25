#!/bin/bash
# Harvester 容器内菜单入口（统一委托给 start.py）
set -e
exec python3 /app/start.py
