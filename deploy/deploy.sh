#!/usr/bin/env bash
set -euo pipefail

# =============================================================
# BOMatch 一键部署脚本（在 Debian 服务器上运行）
#
# 用法:
#   bash deploy/deploy.sh [域名]
# 示例:
#   bash deploy/deploy.sh bom.fantastair.cn
#
# 依赖服务器已有的 nginx + certbot（多站点场景），
# 只为 BOMatch 新增一个反向代理站点，不动现有站点。
#
# 前置条件:
#   - 已在项目根目录（代码通过 git clone 或 rsync 同步，含 deploy/）
#   - uv 已安装（`curl -LsSf https://astral.sh/uv/install.sh | sh`）
#   - nginx、certbot 已安装（服务器已有站点则天然满足）
#   - 域名 A 记录已指向本机公网 IP
#   - 有 sudo 权限
# =============================================================

APP_DIR="$(pwd)"
DOMAIN="${1:-bom.fantastair.cn}"
# 用应用目录属主作为服务运行用户（避免以 root 运行）
APP_USER="$(stat -c '%U' "$APP_DIR" 2>/dev/null || echo "${SUDO_USER:-$USER}")"
SITE_CONF="/etc/nginx/sites-available/${DOMAIN}"

echo "==> [1/5] 安装 Python 3.14（由 uv 管理，不动系统 Python）"
uv python install 3.14

echo "==> [2/5] 同步项目依赖到虚拟环境"
uv sync --python 3.14 --frozen

echo "==> [3/5] 安装 systemd 服务 bomatch.service"
sed -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__USER__|$APP_USER|g" \
  "$APP_DIR/deploy/bomatch.service" | sudo tee /etc/systemd/system/bomatch.service >/dev/null
sudo systemctl daemon-reload

echo "==> [4/5] 配置 nginx 反向代理并签发 HTTPS 证书"
# 写入站点配置（先只监听 80，certbot 会自动补 443/SSL）
sed "s|__DOMAIN__|$DOMAIN|g" "$APP_DIR/deploy/bomatch.nginx.conf" \
  | sudo tee "$SITE_CONF" >/dev/null
sudo ln -sf "$SITE_CONF" "/etc/nginx/sites-enabled/${DOMAIN}"
sudo nginx -t
sudo systemctl reload nginx
echo "    - 为 $DOMAIN 申请 HTTPS 证书（certbot，独立域名证书，不影响现有站点）..."
if ! sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --redirect; then
  echo "    ! certbot 自动签发失败，请稍后手动执行:"
  echo "      sudo certbot --nginx -d $DOMAIN --redirect"
fi

echo "==> [5/5] 启动 BOMatch"
sudo systemctl enable --now bomatch

echo
echo "==============================================="
echo "  部署完成！"
echo "  访问地址: https://$DOMAIN"
echo "  查看状态: systemctl status bomatch"
echo "  实时日志: journalctl -u bomatch -f"
echo "  数据目录: $APP_DIR/data/"
echo "==============================================="
echo "  下一步建议:"
echo "    1. 设置备份定时任务（见 README 备份章节）"
echo "    2. 如需迁移本机已有数据，见 README『迁移数据』"
echo "==============================================="
