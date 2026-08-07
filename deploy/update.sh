#!/usr/bin/env bash
set -euo pipefail

# =============================================================
# BOMatch 自动更新脚本（由 GitHub Actions 在 push 后调用）
#
# 前置要求:
#   - /opt/bomatch 是 git clone 的公开仓库（无需凭据即可 pull）
#   - fanagent 有权限运行 uv（uv 在 PATH 中）
#   - fanagent 具备 sudo NOPASSWD 执行 `systemctl restart bomatch`
#     （配置方法见 README『自动部署』章节）
# =============================================================

cd /opt/bomatch

echo "==> git pull 拉取最新代码"
git pull --ff-only

echo "==> uv sync 同步依赖"
uv sync --python 3.14 --frozen

echo "==> 重启 BOMatch 服务"
sudo systemctl restart bomatch

echo "==> 服务状态"
systemctl is-active bomatch
