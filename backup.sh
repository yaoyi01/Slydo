#!/bin/bash
# Slydo 自动备份脚本
# 用法: bash backup.sh [commit message]

set -e

cd "$(dirname "$0")"

REPO="/mnt/c/Users/kiven/Documents/个人知识库/Coding/Slydo"
cd "$REPO"

# 检查是否有未提交的变更
if [ -z "$(git status --porcelain)" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M')] ✓ 仓库干净，无需备份"
    exit 0
fi

# 生成提交信息
MSG="${1:-自动备份 $(date '+%Y-%m-%d %H:%M')}"

git add -A
git commit -m "$MSG"

echo "[$(date '+%Y-%m-%d %H:%M')] ✓ 备份完成"
echo "  提交: $MSG"
echo "  文件数: $(git diff --name-only HEAD~1..HEAD 2>/dev/null | wc -l)"
