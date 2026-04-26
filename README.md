# 🎧 Music Radio Station

> 自建实时音乐电台系统 — FastAPI + WebSocket，支持 DJ 控制台 + 听众同步收听

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green?logo=fastapi)
![WebSocket](https://img.shields.io/badge/WebSocket-Realtime-orange)
[![Demo](https://img.shields.io/badge/Demo-fm.yuhanghome.icu-brightgreen?style=flat)](https://fm.yuhanghome.icu/)

---

## ✨ 特性

- 🎵 **三种曲目来源** — 上传文件 / URL 添加 / 本地音乐目录浏览
- 📡 **WebSocket 实时同步** — 听众端自动跟随 DJ 播放，零延迟切换
- 🔄 **服务端驱动循环播放** — 歌曲播完自动切下一首，DJ 关页面也不停
- 📊 **边下边播** — HTTP Range 请求流式传输，支持 seek
- 🎤 **多源歌词搜索** — LRCLIB / 网易云音乐，支持同步歌词 (LRC)
- 🖼️ **封面自动提取** — 支持 MP3/M4A/FLAC/OGG/WMA 内嵌封面
- 🗑️ **定时清理** — 每日 00:00 自动清理上传缓存，播放中跳过
- 🎛️ **DJ 控制台** — 播放控制、播放列表拖拽排序、在线听众管理、踢人
- 💬 **实时聊天** — 听众和主播即时互动
- 📱 **移动端适配** — 响应式布局，触控优化
- 🌙 **Apple Music Night 主题** — 深色玻璃态 UI

## 📸 截图

| 听众播放页 | DJ 控制台 |
|:---:|:---:|
| ![Player](screenshots/player.png) | ![Admin](screenshots/admin.png) |

> 🎧 **在线体验**：[https://fm.yuhanghome.icu/](https://fm.yuhanghome.icu/)

---

## 🏗️ 系统架构

### 整体设计

```
┌─────────────┐     WebSocket      ┌──────────────────────────────┐
│  🎧 Player   │◄──────────────────►│                              │
│  (听众页面)   │                    │     🖥️ server.py             │
├─────────────┤     WebSocket      │  ┌────────────────────────┐  │
│  🎛️ Admin   │◄──────────────────►│  │   RadioState (内存)     │  │
│  (DJ 控制台)  │                    │  │  - playlist            │  │
└─────────────┘                    │  │  - current_index       │  │
                                   │  │  - is_playing          │  │
                                   │  │  - play_position       │  │
                                   │  │  - auto_loop           │  │
                                   │  └────────────────────────┘  │
                                   │                              │
                                   │  ┌────────────────────────┐  │
                                   │  │   WSManager             │  │
                                   │  │  - clients (uid→ws)    │  │
                                   │  │  - broadcast()         │  │
                                   │  └────────────────────────┘  │
                                   │                              │
                                   │  ┌────────────────────────┐  │
                                   │  │   tick_position()       │  │
                                   │  │  每秒检查:             │  │
                                   │  │  → 歌曲结束自动切歌    │  │
                                   │  │  → 广播位置更新        │  │
                                   │  │  → 空闲时自动开始      │  │
                                   │  └────────────────────────┘  │
                                   └──────────────────────────────┘
```

### 核心原则

1. **服务端驱动播放**：所有播放状态存储在 `RadioState` 中，不依赖任何客户端。DJ 关闭浏览器，音乐继续播放
2. **WebSocket 广播同步**：状态变更后立即 `broadcast()` 推送到所有连接的客户端，听众端零延迟跟随
3. **三种音源统一抽象**：上传文件、URL、本地目录三种来源统一为 `track` 对象，`/stream/{id}` 根据 `source_type` 自动路由

---

## 🧠 API 实现原理

### 1. 播放状态管理 — RadioState

所有播放状态集中在一个内存对象中，无需数据库：

```python
class RadioState:
    playlist: List[dict]        # 播放列表（有序）
    current_index: int          # 当前播放索引
    is_playing: bool            # 是否正在播放
    play_start_time: float      # 开始播放的 time.time()
    play_position: float        # 开始时的偏移量（秒）
    auto_loop: bool             # 自动循环模式
    admin_paused: bool          # 主播主动暂停标志
```

**播放位置计算**：不依赖客户端上报，服务端自行计算：

```python
def get_position(self, track_duration=0) -> float:
    if self.is_playing:
        elapsed = time.time() - self.play_start_time
        pos = self.play_position + elapsed
        if track_duration > 0 and pos > track_duration:
            return track_duration  # 防止溢出
        return pos
    return self.play_position
```

**admin_paused 标志**：区分「从未开始」和「主播主动暂停」两种状态——歌曲自然结束后 `admin_paused=False`，auto_loop 可以自动恢复；主播点暂停后 `admin_paused=True`，auto_loop 不会自动恢复。

### 2. 自动循环播放 — tick_position()

每秒执行一次的后台协程，是整个系统的心跳：

```
每秒执行:
├── 正在播放 + 歌曲结束 (position >= duration - 0.5s)
│   ├── auto_loop=True  → 切到下一首 (循环), 广播 now_playing
│   └── auto_loop=False → 停止播放, 广播 now_playing(is_playing=false)
├── 正在播放 + 未结束
│   └── 广播 position_update (让听众端同步进度条)
└── 未播放 + auto_loop=True + admin_paused=False + 有曲目
    └── 自动开始播放 (覆盖"添加歌但没按播放"等场景)
```

提前 0.5 秒切歌，减少空窗期。

### 3. 音频流式传输 — Range 请求

`/stream/{track_id}` 根据 `source_type` 自动路由：

| source_type | 处理方式 |
|-------------|----------|
| `upload` | 读取 `uploads/music/` 中的文件，支持 Range 请求 |
| `url` | 302 重定向到原始 URL（浏览器直接加载远程资源） |
| `local` | 302 重定向到 `/api/local-music/stream/{path}` |

**Range 请求实现**（upload 类型）：

```
1. 解析 Range 头: "bytes=0-1048575"
2. 校验范围: start >= 0, end < file_size
3. 返回 206 Partial Content + Content-Range 头
4. 使用异步生成器 file_stream() 分块读取
```

这使浏览器可以边下载边播放，拖动进度条时只需请求新的 Range。

### 4. 文件上传与元数据提取

上传流程：

```
POST /api/upload/music (multipart/form-data)
│
├── 1. 生成 UUID 作为 track_id
├── 2. 保存文件到 uploads/music/{track_id}.mp3
├── 3. extract_metadata() 自动提取:
│   ├── 标题/艺术家/专辑 (mutagen ID3/MP4/Vorbis/FLAC/ASF)
│   ├── 封面图 → 保存到 uploads/covers/{track_id}.jpg
│   ├── 时长 (mutagen.info.length)
│   └── 内嵌歌词 (USLT/SYLT/lyrics tag)
├── 4. 构建 track 对象, 加入 state.playlist
└── 5. 广播 playlist_update
```

**封面提取**支持 5 种音频格式：

| 格式 | 库 | 封面字段 |
|------|-----|---------|
| MP3 | mutagen.id3 | APIC frame |
| M4A/AAC | mutagen.mp4 | covr tag (0x0d=JPEG, 0x0e=PNG) |
| FLAC | mutagen.flac | FLAC.pictures[0] |
| OGG/Opus | mutagen.oggvorbis | metadata_block_picture (Base64 编码的 Vorbis Comment) |
| WMA | mutagen.asf | WM/Picture |

### 5. WebSocket 实时通信 — WSManager

```python
class WSManager:
    clients: Dict[str, ClientInfo]   # uid → WebSocket 连接信息

    async def broadcast(msg)         # 向所有客户端广播
    async def send_to(uid, msg)      # 向指定用户发送
```

**连接生命周期**：

```
客户端连接 WS /ws
│
├── 分配 uid, 创建 ClientInfo
├── 发送 init 消息 (uid, playlist, now_playing, user_count, auto_loop)
├── 广播 user_count 更新
│
├── [运行中] 接收客户端消息:
│   ├── set_username → 更新用户名
│   ├── chat → 广播聊天消息
│   ├── report_duration → 上报收听时长
│   └── admin_auth → Token 认证
│
├── [运行中] 服务端推送:
│   ├── position_update (每秒)
│   ├── now_playing (曲目变更)
│   ├── playlist_update (列表变更)
│   ├── seek (DJ 跳转同步)
│   └── user_count (人数变更)
│
└── 断开 → 移除客户端, 广播 user_count
```

### 6. 歌词搜索 — 多源策略

`GET /api/lyrics/search?title=&artist=&source=` 支持三个源：

| 源 | 搜索策略 | 适用场景 |
|----|----------|----------|
| `lrclib` | 先精确搜索 `?track_name=&artist_name=`，404 后回退模糊搜索 `?q=` | 默认源，英文/日文歌词 |
| `lrclib-alt` | 模糊搜索后按匹配度排序，返回第 2 个结果（不同版本） | 同一首歌的备选歌词 |
| `netease` | 网易云音乐搜索 API → 取第一个结果 → 请求歌词 API | 中文歌词覆盖更广 |

优先返回 `syncedLyrics`（同步歌词，LRC 格式），无则回退 `plainLyrics`。

### 7. 本地音乐浏览 — 安全设计

`/api/local-music/browse` 只返回相对路径，不暴露服务器绝对路径：

```
请求: GET /api/local-music/browse?path=Album1
                         ↓
_safe_local_path("Album1")
├── 解析: LOCAL_MUSIC_DIR / "Album1" → 绝对路径
├── 安全校验: resolve() 后必须以 LOCAL_MUSIC_DIR 开头 (防路径遍历)
└── 返回相对路径: "Album1/song.mp3" (不含 /data/music 前缀)
```

**路径遍历防护**：`_safe_local_path()` 中 `resolve()` 解析符号链接后，校验目标路径必须在 `LOCAL_MUSIC_DIR` 下。

### 8. 定时清理机制

每日凌晨 00:00 自动执行的后台协程：

```
daily_cleanup():
│
├── 计算到明天 00:00 的等待时间
├── sleep 等待
├── 检查: 正在播放? → 跳过, 明天再试
├── 清理 uploads/music/ 中不属于任何 playlist track 的文件
├── 清理 uploads/covers/ 中孤立的封面文件
└── 只删 source_type="upload" 的 track (保留 local 和 url)
```

---

## 📖 API 使用方法

### 认证流程

DJ 控制台需要密码认证，密码以 **SHA-256 哈希**传输（不明文）：

```bash
# 1. 计算密码的 SHA-256
echo -n "your_password" | sha256sum
# 输出: a1b2c3d4...

# 2. 用哈希值认证
curl -X POST http://localhost:8765/api/admin/auth \
  -H "Content-Type: application/json" \
  -d '{"password": "a1b2c3d4..."}'

# 返回: {"status": "ok", "token": "xxx"}
```

后续需要认证的请求在 URL 参数中携带 token：
```bash
curl http://localhost:8765/api/users?token=xxx
```

### 播放控制

```bash
# 播放
curl -X POST http://localhost:8765/api/playback/play?token=xxx

# 暂停
curl -X POST http://localhost:8765/api/playback/pause?token=xxx

# 下一首
curl -X POST http://localhost:8765/api/playback/next?token=xxx

# 跳转到 60 秒处
curl -X POST http://localhost:8765/api/playback/seek?token=xxx \
  -H "Content-Type: application/json" \
  -d '{"position": 60}'

# 播放第 3 首歌（索引从 0 开始）
curl -X POST http://localhost:8765/api/playback/play-index?token=xxx \
  -H "Content-Type: application/json" \
  -d '{"index": 2}'

# 开关自动循环
curl -X POST http://localhost:8765/api/playback/auto-loop?token=xxx \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

### 播放列表管理

```bash
# 获取播放列表
curl http://localhost:8765/api/playlist

# 通过 URL 添加曲目
curl -X POST http://localhost:8765/api/playlist/add?token=xxx \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/song.mp3", "title": "My Song"}'

# 删除曲目
curl -X DELETE http://localhost:8765/api/playlist/{track_id}?token=xxx

# 拖拽排序（传入新的 ID 顺序）
curl -X PUT http://localhost:8765/api/playlist/reorder?token=xxx \
  -H "Content-Type: application/json" \
  -d '{"track_ids": ["id3", "id1", "id2"]}'

# 修改曲目信息
curl -X PUT http://localhost:8765/api/playlist/track/{track_id}?token=xxx \
  -H "Content-Type: application/json" \
  -d '{"title": "新标题", "artist": "新艺术家"}'
```

### 文件上传

```bash
# 上传音乐文件（支持多文件）
curl -X POST http://localhost:8765/api/upload/music?token=xxx \
  -F "files=@song1.mp3" \
  -F "files=@song2.flac"

# 上传封面
curl -X POST http://localhost:8765/api/upload/cover/{track_id}?token=xxx \
  -F "file=@cover.jpg"
```

上传成功后自动提取：标题、艺术家、专辑、时长、封面图、内嵌歌词。

### 音频流式传输

```bash
# 完整下载
curl http://localhost:8765/stream/{track_id} -o song.mp3

# Range 请求（从 1MB 处继续下载）
curl -H "Range: bytes=1048576-" http://localhost:8765/stream/{track_id} \
  -o song_partial.mp3
```

### 本地音乐

```bash
# 浏览根目录
curl http://localhost:8765/api/local-music/browse

# 浏览子目录
curl "http://localhost:8765/api/local-music/browse?path=Album1"

# 添加本地音乐到播放列表
curl -X POST http://localhost:8765/api/local-music/add?token=xxx \
  -H "Content-Type: application/json" \
  -d '{"path": "Album1/song.mp3"}'
```

### 歌词搜索

```bash
# LRCLIB 搜索（默认）
curl "http://localhost:8765/api/lyrics/search?title=Bohemian+Rhapsody&artist=Queen"

# 网易云搜索
curl "http://localhost:8765/api/lyrics/search?title=晴天&artist=周杰伦&source=netease"

# LRCLIB 备选版本
curl "http://localhost:8765/api/lyrics/search?title=Yesterday&source=lrclib-alt"
```

### 用户管理

```bash
# 查看在线用户
curl http://localhost:8765/api/users?token=xxx

# 踢出用户
curl -X POST http://localhost:8765/api/users/kick?token=xxx \
  -H "Content-Type: application/json" \
  -d '{"uid": "user_xxx"}'
```

### WebSocket 连接

```javascript
// 连接
const ws = new WebSocket('ws://localhost:8765/ws');

// 接收初始化消息
ws.onmessage = (e) => {
  const data = JSON.parse(e.data);
  switch(data.type) {
    case 'init':        // { uid, playlist, now_playing, user_count, auto_loop }
    case 'now_playing': // { track, position, is_playing }
    case 'position_update': // { position } — 每秒推送
    case 'playlist_update': // { playlist }
    case 'seek':        // { position } — DJ 跳转同步
    case 'chat':        // { username, message }
    case 'user_count':  // { count }
    case 'kicked':      // 被踢出
  }
};

// 设置用户名
ws.send(JSON.stringify({ type: 'set_username', username: '听众小明' }));

// 发送聊天消息
ws.send(JSON.stringify({ type: 'chat', message: '这首歌好听！' }));

// 上报收听时长
ws.send(JSON.stringify({ type: 'report_duration', duration: 120 }));
```

---

## 📡 API 端点总览

| 分类 | 端点 | 方法 | 认证 | 说明 |
|------|------|------|:----:|------|
| **认证** | `/api/admin/auth` | POST | ❌ | Admin 密码认证 |
| | `/api/admin/verify` | GET | ❌ | 验证 Token 有效性 |
| | `/api/login` | POST | ❌ | 设置用户名 |
| | `/api/logout` | POST | ❌ | 清除用户名 |
| | `/api/check` | GET | ❌ | 检查登录状态 |
| **播放控制** | `/api/playback/play` | POST | ✅ | 恢复播放 |
| | `/api/playback/pause` | POST | ✅ | 暂停 |
| | `/api/playback/next` | POST | ✅ | 下一首 |
| | `/api/playback/prev` | POST | ✅ | 上一首 |
| | `/api/playback/seek` | POST | ✅ | 跳转进度 |
| | `/api/playback/play-index` | POST | ✅ | 播放指定曲目 |
| | `/api/playback/auto-loop` | POST | ✅ | 切换自动循环 |
| | `/api/status` | GET | ❌ | 当前播放状态 |
| **播放列表** | `/api/playlist` | GET | ❌ | 获取列表 |
| | `/api/playlist/list` | POST | ❌ | 批量获取 |
| | `/api/playlist/add` | POST | ✅ | URL 添加曲目 |
| | `/api/playlist/reorder` | PUT | ✅ | 重新排序 |
| | `/api/playlist/{id}` | DELETE | ✅ | 删除曲目 |
| | `/api/playlist/track/{id}` | PUT | ✅ | 更新曲目信息 |
| **文件上传** | `/api/upload/music` | POST | ✅ | 上传音频文件 |
| | `/api/upload/cover/{id}` | POST | ✅ | 上传封面图 |
| **音频流** | `/stream/{id}` | GET | ❌ | 流式传输（Range） |
| **本地音乐** | `/api/local-music/browse` | GET | ❌ | 浏览目录 |
| | `/api/local-music/stream/{path}` | GET | ❌ | 流式播放本地文件 |
| | `/api/local-music/add` | POST | ✅ | 添加到播放列表 |
| **歌词** | `/api/lyrics/search` | GET | ❌ | 多源歌词搜索 |
| **用户** | `/api/users` | GET | ✅ | 在线用户列表 |
| | `/api/users/kick` | POST | ✅ | 踢出用户 |
| **维护** | `/api/cleanup` | POST | ✅ | 手动清理 |
| **WebSocket** | `/ws` | WS | ❌ | 实时双向通信 |

👉 **完整 API 参考**：[API.md](./API.md)

---

## 🚀 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 启动服务

```bash
python server.py
```

服务默认运行在 `http://0.0.0.0:8765`。

### 访问

| 页面 | 地址 |
|------|------|
| 🎧 听众播放页 | `http://localhost:8765/player` |
| 🎛️ DJ 控制台 | `http://localhost:8765/admin` |

### 配置

**Admin 密码**：修改 `server.py` 中的 `ADMIN_PASSWORD_HASH`：

```python
ADMIN_PASSWORD_HASH = _hash_pwd("your_password")
```

**本地音乐目录**：修改 `server.py` 中的 `LOCAL_MUSIC_DIR`：

```python
LOCAL_MUSIC_DIR = Path("/path/to/your/music")
```

---

## 📁 项目结构

```
music-radio/
├── server.py              # FastAPI 后端（所有 API + WebSocket，单文件）
├── requirements.txt       # Python 依赖
├── API.md                 # 完整 API 参考文档
├── DEPLOY_GUIDE.md        # 部署运维指南
├── .gitignore
├── static/
│   ├── player.html        # 听众播放页（零框架原生 JS）
│   └── admin.html         # DJ 控制台（零框架原生 JS）
├── screenshots/
│   ├── player.png         # 听众页截图
│   └── admin.png          # 控制台截图
└── uploads/               # 运行时生成
    ├── music/             # 上传的音频文件
    └── covers/            # 自动提取的封面图
```

---

## 🌐 部署

### Nginx 反向代理配置

```nginx
# http 块中添加（WebSocket 支持）
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 443 ssl;
    server_name fm.example.com;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        client_max_body_size 100m;
    }
}
```

### Systemd 服务（可选）

```ini
[Unit]
Description=Music Radio Station
After=network.target

[Service]
Type=simple
User=www
WorkingDirectory=/path/to/music-radio
ExecStart=/path/to/venv/bin/python server.py
Restart=always

[Install]
WantedBy=multi-user.target
```

### 部署注意事项

| 项目 | 说明 |
|------|------|
| **Python 环境** | 必须使用虚拟环境，系统 Python 可能受限 |
| **文件上传大小** | Nginx 需设置 `client_max_body_size 100m` |
| **WebSocket** | 必须配置 `map $http_upgrade`，否则 WS 连接失败 |
| **换行符** | Windows 上传文件后需修复 CRLF → LF |
| **依赖** | `pip install "uvicorn[standard]"` 确保 WebSocket 完整支持 |

---

## 🛠️ 技术栈

| 层级 | 技术 |
|------|------|
| **后端** | Python 3.10+ · FastAPI · WebSocket · Uvicorn |
| **元数据** | mutagen（封面/歌词/标签提取，支持 MP3/M4A/FLAC/OGG/WMA） |
| **前端** | 原生 HTML/CSS/JS（零框架依赖，单文件 SPA） |
| **通信** | WebSocket 实时双向通信 + HTTP REST API |
| **音频** | HTTP Range 流式传输（边下边播 + seek） |

---

## 📄 License

MIT License
