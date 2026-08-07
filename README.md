# BOMatch

个人电子元件物料管理系统（自托管、单用户、在线 Web）。

- **随时知道**：有什么料、放在哪个库位、还剩多少（库存管理）
- **只买缺失的**：新设计导入 BOM，自动匹配库存，生成缺料报告
- **剩料复用**：剩余物料入库后可被后续设计等效匹配复用

## 技术栈

FastAPI + SQLite(WAL) + SQLAlchemy + Jinja2 SSR + HTMX/Alpine.js，无 Node 构建链，低资源占用，适合低配服务器。

## 目录结构

```.
app/            # 应用代码（main / routers / services / parsers / templates）
deploy/         # 部署产物（systemd、nginx、部署/备份脚本）
data/           # 运行数据（SQLite + secret_key，已 gitignore）
local_dev/      # 本地开发辅助脚本与初始数据（已 gitignore）
tests/          # pytest 集成测试
dev.py          # 开发工具（check / test / run / db-init）
```

## 本地开发

要求 Python ≥ 3.14，使用 [uv](https://docs.astral.sh/uv/) 管理。

```bash
uv sync                    # 安装依赖
uv run python dev.py run   # 启动开发服务器 http://127.0.0.1:8000
uv run python dev.py test  # 运行测试
uv run python dev.py check # 代码质量检查（ruff + ty）
```

首次启动自动建库、播种类别、创建默认管理员账号（admin，初始密码见运行日志提示，**登录后请立即修改**）。

---

## 部署到 Debian 服务器

### 部署架构

```mermaid
flowchart LR
    A[本地 git push] --> B[GitHub Actions]
    B -->|SSH| C[服务器 git pull]
    C --> D[uv sync 依赖]
    D --> E[systemctl restart bomatch]
```

> **开源说明**：本项目开源，但**仅支持私人部署**（不提供公开在线服务）。
> 仓库中不含任何个人数据 —— `data/`（数据库/密钥）与 `local_dev/`（初始数据）均已 gitignore，
> 绝不会被推送到 GitHub；数据只存储在你自己的服务器上。

### 前置条件

| 项目 | 要求 | 说明 |
| ---- | ---- | ---- |
| 系统 | Debian 12 / 13 | 以 Debian 13 (trixie) 验证 |
| Python | **服务器无需装 3.14** | 部署脚本用 uv 自动安装 3.14（不污染系统 Python） |
| uv | 已安装 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| 域名 | A 记录指向服务器（如 bom.fantastair.cn） | certbot 自动申请 HTTPS 证书 |
| 端口 | 80 / 443 / 22 已放行 | 80/443 供网站，22 供 GitHub Actions SSH 部署 |

### 第 1 步：首次部署（一次性，手动）

```bash
# 1. clone 公开仓库（无需凭据）
sudo git clone https://github.com/<你的用户名>/BOMatch.git /opt/bomatch
sudo chown -R fanagent:fanagent /opt/bomatch
cd /opt/bomatch

# 2. 初始化：装 Python 3.14 / 依赖 / systemd / nginx 站点 / certbot 证书
bash deploy/deploy.sh bom.fantastair.cn
```

> Windows 传文件后若报 `$'\r'` 错误：`sed -i 's/\r$//' deploy/*.sh`

脚本会依次完成：

1. 用 uv 安装 Python 3.14（不动系统 Python）
2. 同步项目依赖到虚拟环境
3. 安装 systemd 服务 `bomatch.service`（开机自启 + 崩溃自动拉起 + 仅监听 127.0.0.1）
4. 新增一个 nginx 反向代理站点（反代到 8000），并用 certbot 自动签发 HTTPS 证书
5. 启动服务

> 说明：脚本**沿用服务器已有的 nginx + certbot**，只为 BOMatch 新增一个站点，
> 不会动你现有的其他站点；证书为独立域名证书（如 `bom.fantastair.cn`）。

### 第 2 步：迁移已有数据（可选但推荐）

如果你在本机已经使用过 BOMatch，把本机 `data/` 目录（含 `bomatch.db` 和 `secret_key`）整个传上去，登录会话与数据都会保留：

```bash
rsync -av data/ fanagent@<服务器IP>:/opt/bomatch/data/
```

> 数据目录已 gitignore，不会随仓库提交，必须单独传输。

### 第 3 步：配置 GitHub Actions 自动部署

之后每次 `git push` 到 `master`，Actions 会自动 SSH 到服务器拉代码并重启服务。

#### 3.1 生成部署密钥并在服务器授权

```bash
# 在服务器上生成专用部署密钥（不要用你日常的 SSH 私钥）
ssh-keygen -t ed25519 -f ~/.ssh/bomatch_deploy -N "" -C "github-actions"
cat ~/.ssh/bomatch_deploy.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
cat ~/.ssh/bomatch_deploy   # 记下私钥全文，下一步填入 GitHub
```

#### 3.2 授权 sudo 重启服务（最小权限）

```bash
sudo tee /etc/sudoers.d/bomatch > /dev/null <<'EOF'
fanagent ALL=(root) NOPASSWD: /usr/bin/systemctl restart bomatch
EOF
sudo visudo -c   # 校验语法
```

#### 3.3 配置 GitHub Secrets

仓库 → **Settings → Secrets and variables → Actions → New repository secret**：

| Secret | 值 |
| ---- | ---- |
| `SERVER_HOST` | 服务器公网 IP（如 8.152.101.207） |
| `SERVER_PORT` | 22 |
| `SERVER_USER` | fanagent |
| `SERVER_SSH_KEY` | 上一步的 `bomatch_deploy` 私钥全文 |

#### 3.4 测试

推送任意提交，在仓库 **Actions** 页观察 `部署 BOMatch` 工作流；
也可点击 `workflow_dispatch` 手动触发。

### 配置自动备份

```bash
mkdir -p /opt/bomatch/backups
crontab -e
```

加入一行（每天凌晨 3 点备份，保留最近 30 份）：

```.
0 3 * * * /opt/bomatch/deploy/backup.sh >> /opt/bomatch/backups/backup.log 2>&1
```

恢复备份：把 `backups/bomatch_xxxx.db` 替换回 `data/bomatch.db` 后 `sudo systemctl restart bomatch`。

### 日常运维

```bash
systemctl status bomatch      # 查看状态
journalctl -u bomatch -f      # 实时日志
sudo systemctl restart bomatch  # 手动重启
```

**更新代码**：正常情况只需 `git push` 到 GitHub，Actions 会自动部署。
如需在服务器上手动更新：

```bash
cd /opt/bomatch
git pull
uv sync --python 3.14 --frozen
sudo systemctl restart bomatch
```

### 环境变量（可选）

| 变量 | 默认 | 说明 |
| ---- | ---- | ---- |
| `BOMATCH_DB_PATH` | `data/bomatch.db` | 数据库路径 |
| `BOMATCH_SECRET_KEY` | `data/secret_key` | 会话签名密钥（自动生成） |
| `BOMATCH_COOKIE_SECURE` | `0` | 设 `1` 启用 cookie 安全位（HTTPS 下部署脚本已自动开启） |

---

## 常见问题

**Q: 开源会不会泄露我的数据？**
不会。`data/`（数据库、secret_key）与 `local_dev/`（初始盘点、立创 pid）均已 gitignore，推送/开源均不含任何个人数据；数据只存在你部署的服务器上。

**Q: 访问提示证书错误 / 无法访问？**
检查域名 A 记录是否已生效、80/443 是否放行；首次申请证书需要 1-2 分钟，`sudo certbot certificates` 查看签发情况，`journalctl -u nginx -f` 查看 nginx 日志。

**Q: 多 worker 会不会更快？**
不建议。SQLite 单文件不适合多进程并发写，单 worker 对个人使用完全足够，也最稳。
