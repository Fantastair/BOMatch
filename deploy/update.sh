#!/usr/bin/env bash
set -euo pipefail

# =============================================================
# BOMatch 自动更新脚本（由 GitHub Actions 在 push 后调用）
#
# 逻辑：
#   1. git pull 拉取最新代码
#   2. 仅当 pyproject.toml / uv.lock 变化时才 uv sync（依赖没变则跳过，加快部署）
#   3. 重启 bomatch 服务
#   4. 健康检查（服务活跃 + 本地 HTTP 可访问）
#
# 前置要求:
#   - /opt/bomatch 是 git clone 的公开仓库（无需凭据 pull）
#   - 以 deployer 身份运行，具备 sudo NOPASSWD: systemctl restart bomatch
#   - deployer 已配置 uv 镜像（~/.config/uv/uv.toml），下载依赖更快
# =============================================================

cd /opt/bomatch

BEFORE="$(git rev-parse HEAD)"

echo "==> git pull"
git pull --ff-only

AFTER="$(git rev-parse HEAD)"
if [ "$BEFORE" = "$AFTER" ]; then
  echo "==> 无新提交，跳过部署"
  exit 0
fi

if git diff --name-only "$BEFORE" HEAD | grep -qE '^(pyproject.toml|uv.lock)$'; then
  echo "==> 依赖有变化，更新依赖（清华镜像，绕开 uv.lock 慢速源）"
  /usr/local/bin/uv export --frozen --no-hashes --format requirements.txt -o /tmp/bomatch_reqs.txt
  /usr/local/bin/uv pip install -r /tmp/bomatch_reqs.txt
  rm -f /tmp/bomatch_reqs.txt
else
  echo "==> 依赖未变化，跳过依赖更新"
fi

echo "==> 重启服务"
sudo systemctl restart bomatch

echo "==> 健康检查"
sleep 3
if systemctl is-active --quiet bomatch && curl -sf -o /dev/null http://127.0.0.1:8000/; then
  echo "OK: bomatch 运行正常"
else
  echo "警告: 服务可能未就绪，请查看日志 journalctl -u bomatch"
  exit 1
fi
