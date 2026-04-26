# 🎵 Music Radio Station — 宝塔面板 Linux 部署教程

> 基于 FastAPI + WebSocket 的音乐电台系统，部署到宝塔面板管理的 Linux 服务器。

---

## 一、项目结构概览

```
music-radio/                  # 项目根目录
├── server.py                 # FastAPI 主服务（端口 8765）
├── requirements.txt          # Python 依赖
├── auth.json                 # 管理员账号（默认 admin/admin）
├── static/
│   ├── admin.html            # 主播端（DJ 控制台）
│   └── player.html           # 用户端（收听页面）
└── uploads/
    ├── music/                # 上传的音乐文件
    └── covers/               # 上传的封面图片
```

**技术栈：**
- 后端：FastAPI + Uvicorn
- 通信：WebSocket 实时同步
- 端口：`8765`
- Python：≥ 3.9

---

## 二、服务器要求

| 项目 | 要求 |
|------|------|
| 系统 | CentOS / Ubuntu / Debian |
| 宝塔面板 | ≥ 7.x |
| Python | ≥ 3.9（推荐 3.11+） |
| 内存 | ≥ 512MB |
| 磁盘 | ≥ 1GB（音乐文件会占用更多） |
| 域名 | 可选，用于 HTTPS 访问 |

---

## 三、部署步骤

### 步骤 1：上传项目文件

1. 将本地 `music-radio` 整个文件夹打包成 `music-radio.zip`

2. 登录宝塔面板 → **文件** → 进入 `/www/wwwroot/` 目录

3. **上传** `music-radio.zip` → 右键 **解压**

4. 解压后确认目录结构为：
   ```
   /www/wwwroot/music-radio/
   ├── server.py
   ├── requirements.txt
   ├── auth.json
   ├── static/
   └── uploads/
   ```

5. 设置权限（重要！）：
   ```bash
   chown -R www:www /www/wwwroot/music-radio/
   chmod -R 755 /www/wwwroot/music-radio/
   chmod -R 777 /www/wwwroot/music-radio/uploads/
   ```

---

### 步骤 2：安装 Python 环境

#### 方法 A：通过宝塔「Python 项目」插件（推荐）

1. 宝塔面板 → **软件商店** → 搜索 **Python项目**
2. 点击 **安装**

3. 安装完成后进入插件：
   - 点击 **版本管理** → 安装 **Python 3.11**（或更高）
   - 记下安装路径，通常在 `/www/server/pyporject_evn/` 下

#### 方法 B：手动编译安装（如果插件不可用）

```bash
# Ubuntu/Debian
apt update && apt install -y python3.11 python3.11-venv python3-pip

# CentOS
yum install -y python3.11 python3.11-pip
```

---

### 步骤 3：创建虚拟环境并安装依赖

```bash
cd /www/wwwroot/music-radio/

# 创建虚拟环境
python3.11 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 验证安装成功
pip list | grep -E "fastapi|uvicorn"
```

> 如果下载速度慢，使用国内镜像源：
> ```bash
> pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
> ```

---

### 步骤 4：修改服务器防火墙 / 安全组

确保 **8765 端口开放**：

| 操作位置 | 说明 |
|----------|------|
| **云服务商控制台**（阿里云/腾讯云等） | 安全组入方向添加 TCP 8765 |
| **宝塔面板 → 安全** | 放行端口 `8765` |
| **服务器防火墙**（如果有） | `firewall-cmd --add-port=8765/tcp --permanent && firewall-cmd --reload` |

---

### 步骤 5：配置 Python 项目（宝塔插件方式）

这是最简单的运行方式：

1. 宝塔面板 → **网站** → **Python项目**

2. 点击 **添加项目**，填写：

   | 配置项 | 值 |
   |--------|-----|
   | 项目名称 | music-radio |
   | 项目路径 | `/www/wwwroot/music-radio` |
   | 启动文件 | `server.py` |
   | 运行环境 | 选择已安装的 Python 3.11 |
   | 虚拟环境路径 | `/www/wwwroot/music-radio/venv` |
   | 端口 | `8765` |
   | 启动用户 | `www` |
   | 运行模式 | **生产模式**（自动多 worker） |

3. 点击 **确定** → 项目会自动启动

4. 启动后点击 **日志** 确认无报错

---

### 步骤 6：（备选）手动创建 systemd 服务

如果不使用宝塔插件，手动创建服务：

1. 创建 service 文件：
   ```bash
   cat > /etc/systemd/system/music-radio.service << 'EOF'
   [Unit]
   Description=Music Radio Station
   After=network.target

   [Service]
   User=www
   Group=www
   WorkingDirectory=/www/wwwroot/music-radio
   ExecStart=/www/wwwroot/music-radio/venv/bin/python server.py
   Restart=always
   RestartSec=5
   Environment=PYTHONUNBUFFERED=1

   [Install]
   WantedBy=multi-user.target
   EOF
   ```

2. 启动服务：
   ```bash
   systemctl daemon-reload
   systemctl enable music-radio      # 开机自启
   systemctl start music-radio       # 启动
   systemctl status music-radio      # 查看状态
   ```

3. 常用管理命令：
   ```bash
   systemctl restart music-radio     # 重启
   systemctl stop music-radio        # 停止
   journalctl -u music-radio -f      # 实时查看日志
   ```

---

### 步骤 7：（可选）配置反向代理 + HTTPS

如果你有域名，建议用 Nginx 反向代理 + SSL：

#### 7.1 添加站点

1. 宝塔面板 → **网站** → **添加站点**
2. 填写域名（如 `radio.yourdomain.com`）
3. PHP 版本选择 **纯静态**

#### 7.2 配置反向代理

1. 进入站点设置 → **反向代理**
2. 添加反向代理：

   | 配置项 | 值 |
   |--------|-----|
   | 代理名称 | music-radio |
   | 目标URL | `http://127.0.0.1:8765` |
   | 发送域名 | `$host` |

3. 或者手动编辑 Nginx 配置，加入 WebSocket 支持：
   
   点击 **配置文件**，在 `server {}` 块中添加：

   ```nginx
   location / {
       proxy_pass http://127.0.0.1:8765;
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
       
       # WebSocket 关键配置
       proxy_http_version 1.1;
       proxy_set_header Upgrade $http_upgrade;
       proxy_set_header Connection "upgrade";
       proxy_read_timeout 86400s;
       proxy_send_timeout 86400s;
   }
   
   # 文件上传大小限制（根据需要调整）
   client_max_body_size 100m;
   ```

4. 保存 → 重载 Nginx

#### 7.3 申请 SSL 证书

1. 站点设置 → **SSL** → **Let's Encrypt**
2. 选择域名 → 申请证书
3. 开启 **强制HTTPS**

> ⚠️ **WebSocket 必须用 HTTPS/WSS** 才能在浏览器正常工作。如果你配了 HTTPS，前端连接地址需要确认是否自动适配（当前代码中 WS 地址是相对路径 `/ws`，会自动跟随协议，无需额外修改）。

---

## 四、验证部署

### 1. 本地测试连通性

```bash
curl http://你的服务器IP:8765/api/status
# 或域名
curl http://radio.yourdomain.com/api/status
```

应返回类似：
```json
{"is_playing":false,"current_index":-1,"current_track":null,"position":0,"listeners":0,"user_count":0}
```

### 2. 浏览器访问

| 页面 | 地址 |
|------|------|
| **主播端（Admin）** | `http://IP:8765/admin` |
| **用户端（Player）** | `http://IP:8765/player` |
| 或带域名 | `https://radio.yourdomain.com/admin` |

### 3. 功能检查清单

- [ ] 主播端能打开 DJ 控制台界面
- [ ] 用户端能打开播放器界面
- [ ] 主播端可以上传音乐文件
- [ ] 主播端点击播放，用户端能看到进度同步
- [ ] 聊天弹幕能双向显示
- [ ] 在线用户数量实时更新

---

## 五、常见问题排查

### 问题 1：端口无法访问

```bash
# 检查服务是否在监听
ss -tlnp | grep 8765

# 检查防火墙
iptables -L -n | grep 8765
firewall-cmd --list-ports

# 云服务商安全组是否放行 8765（最常遗漏！）
```

### 问题 2：上传失败 / 权限错误

```bash
chown -R www:www /www/wwwroot/music-radio/
chmod -R 777 /www/wwwroot/music-radio/uploads/
```

### 问题 3：WebSocket 连接断开

- **必须**配置 Nginx 的 `Upgrade` 和 `Connection` 头（见步骤 7.2）
- 如果用了 HTTPS，确认证书有效且浏览器信任

### 问题 4：服务崩溃重启

```bash
# 查看日志
journalctl -u music-radio -n 50        # systemd 方式
# 或宝塔 Python项目 → 日志             # 插件方式
```

### 问题 5：内存不足

```bash
# 查看内存使用
free -h

# 如需限制 Uvicorn 内存，可改用单 worker 模式
# 在启动参数中加入 --workers 1
```

---

## 六、后续运维备忘

| 操作 | 命令 |
|------|------|
| 重启服务 | `systemctl restart music-radio` 或宝塔 Python项目 → 重启 |
| 查看日志 | `journalctl -u music-radio -f` |
| 更新代码 | 上传覆盖后重启即可 |
| 备份数据 | 打包 `music-radio/` 文件夹（含 uploads 和 auth.json） |
| 修改密码 | 编辑 `auth.json` 中 `password_hash`（SHA256 值）或通过管理界面修改 |
| 清理缓存 | 删除 `uploads/music/` 中不需要的文件 |

---

## 七、安全建议（生产环境必读）

1. **修改默认密码** — 登录主播端后立即修改 admin 密码
2. **开启 HTTPS** — 否则聊天内容和控制信号明文传输
3. **限制 IP**（可选）— 在 Nginx 层对 `/admin` 路径做 IP 白名单
4. **定期备份** — 设置定时任务打包 `music-radio/` 目录
5. **更新依赖** — 定期执行 `pip install -U -r requirements.txt`
