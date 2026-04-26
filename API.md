# 🎧 Music Radio Station — API 文档

> 基于 FastAPI + WebSocket 的实时音乐电台系统完整 API 参考

---

## 目录

- [认证](#认证)
- [播放控制](#播放控制)
- [播放列表](#播放列表)
- [文件上传](#文件上传)
- [音频流式传输](#音频流式传输)
- [本地音乐](#本地音乐)
- [歌词搜索](#歌词搜索)
- [用户管理](#用户管理)
- [系统维护](#系统维护)
- [WebSocket 实时通信](#websocket-实时通信)
- [曲目数据结构](#曲目数据结构)
- [错误码](#错误码)
- [快速上手](#快速上手)

---

## 认证

### 通用登录

```
POST /api/login
```

设置当前用户的用户名，建立身份标识。

**请求体：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `username` | string | ✅ | 用户名（2-20 字符） |

**响应示例：**

```json
{
  "status": "ok",
  "username": "DJ小王"
}
```

### 登出

```
POST /api/logout
```

清除当前会话的用户名。

**响应：**

```json
{
  "status": "ok"
}
```

### 检查登录状态

```
GET /api/check
```

**响应：**

```json
{
  "logged_in": true,
  "username": "DJ小王"
}
```

### Admin 密码认证

```
POST /api/admin/auth
```

DJ 控制台需要密码认证才能操作。

**请求体：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `password` | string | ✅ | 密码的 SHA-256 哈希值（十六进制） |

> ⚠️ 密码**不以明文传输**，客户端需先计算 SHA-256 后发送哈希值。

**响应：**

```json
{
  "status": "ok",
  "token": "a1b2c3d4..."
}
```

### 验证 Admin Token

```
GET /api/admin/verify?token=xxx
```

**响应：**

```json
{
  "valid": true
}
```

---

## 播放控制

所有播放控制端点均需 Admin 认证（请求头携带 `Authorization: Bearer <token>`）。

### 播放

```
POST /api/playback/play
```

开始播放当前曲目。

**响应：**

```json
{
  "status": "ok",
  "now_playing": { ... }
}
```

### 暂停

```
POST /api/playback/pause
```

**响应：**

```json
{
  "status": "ok"
}
```

### 下一首

```
POST /api/playback/next
```

播放列表中的下一首曲目（循环播放）。

**响应：**

```json
{
  "status": "ok",
  "now_playing": { ... }
}
```

### 上一首

```
POST /api/playback/prev
```

返回播放列表中的上一首。

**响应：**

```json
{
  "status": "ok",
  "now_playing": { ... }
}
```

### 跳转进度

```
POST /api/playback/seek
```

跳转到指定播放位置。

**请求体：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `position` | float | ✅ | 目标位置（秒） |

**响应：**

```json
{
  "status": "ok"
}
```

### 播放指定曲目

```
POST /api/playback/play-index
```

播放播放列表中指定索引的曲目。

**请求体：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `index` | int | ✅ | 播放列表中的索引（从 0 开始） |
| `start_position` | float | ❌ | 起始播放位置（秒），默认 0 |

**响应：**

```json
{
  "status": "ok",
  "now_playing": { ... }
}
```

### 切换自动循环

```
POST /api/playback/auto-loop
```

开关自动循环播放模式。

**请求体：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `enabled` | bool | ✅ | 是否启用自动循环 |

**响应：**

```json
{
  "status": "ok",
  "auto_loop": true
}
```

### 播放状态

```
GET /api/status
```

获取当前播放状态（无需认证）。

**响应：**

```json
{
  "now_playing": {
    "track": { ... },
    "position": 45.2,
    "is_playing": true
  },
  "user_count": 5
}
```

---

## 播放列表

### 获取播放列表

```
GET /api/playlist
```

**响应：**

```json
{
  "playlist": [
    {
      "id": "abc123",
      "title": "Song Name",
      "artist": "Artist",
      "duration": 240,
      "source_type": "upload",
      ...
    }
  ]
}
```

### 批量获取播放列表

```
POST /api/playlist/list
```

**请求体：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `ids` | string[] | ✅ | 曲目 ID 列表 |

### 添加曲目

```
POST /api/playlist/add
```

通过 URL 添加曲目到播放列表。

**请求体：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `url` | string | ✅ | 音频文件 URL |
| `title` | string | ❌ | 标题（自动提取） |
| `artist` | string | ❌ | 艺术家（自动提取） |

**响应：**

```json
{
  "status": "ok",
  "track_id": "xyz789"
}
```

### 重新排序

```
PUT /api/playlist/reorder
```

**请求体：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `track_ids` | string[] | ✅ | 按新顺序排列的曲目 ID 列表 |

**响应：**

```json
{
  "status": "ok"
}
```

### 删除曲目

```
DELETE /api/playlist/{track_id}
```

从播放列表中移除指定曲目。

**响应：**

```json
{
  "status": "ok"
}
```

### 更新曲目信息

```
PUT /api/playlist/track/{track_id}
```

**请求体：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `title` | string | ❌ | 新标题 |
| `artist` | string | ❌ | 新艺术家 |

**响应：**

```json
{
  "status": "ok"
}
```

---

## 文件上传

### 上传音乐文件

```
POST /api/upload/music
```

**请求：** `multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | File | ✅ | 音频文件（mp3/flac/wav/ogg/aac/m4a） |

> 文件大小限制：100MB

**响应：**

```json
{
  "status": "ok",
  "track_id": "abc123",
  "title": "Song Name",
  "artist": "Artist",
  "duration": 240
}
```

上传成功后自动提取元数据（标题、艺术家、封面）。

### 上传封面

```
POST /api/upload/cover/{track_id}
```

**请求：** `multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | File | ✅ | 图片文件（jpg/png/webp） |

**响应：**

```json
{
  "status": "ok"
}
```

---

## 音频流式传输

### 获取音频流

```
GET /stream/{track_id}
```

支持 HTTP Range 请求，实现边下边播。

**请求头：**

| Header | 说明 |
|--------|------|
| `Range: bytes=0-` | 请求部分内容（可选） |

**响应：**

| 条件 | 状态码 | Content-Type | 说明 |
|------|--------|-------------|------|
| 完整请求 | 200 | `audio/mpeg` 等 | 返回完整文件 |
| Range 请求 | 206 | `audio/mpeg` 等 | 返回指定范围数据 |
| 文件不存在 | 404 | — | 曲目未找到 |

**响应头：**

```
Content-Length: 5242880
Content-Range: bytes 0-5242879/5242880
Accept-Ranges: bytes
```

---

## 本地音乐

浏览和添加服务器本地目录中的音乐文件（如 Navidrome 音乐库）。

### 浏览目录

```
GET /api/local-music/browse?path=/path/to/dir
```

**查询参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | string | ❌ | 浏览的目录路径（默认根目录） |

**响应：**

```json
{
  "current_path": "/data/music",
  "directories": ["Album1", "Album2"],
  "files": [
    {
      "name": "song.mp3",
      "path": "/data/music/song.mp3",
      "size": 5242880
    }
  ]
}
```

### 流式播放本地文件

```
GET /api/local-music/stream/{file_path:path}
```

支持 Range 请求，参数为服务器上的文件路径。

### 添加本地音乐到播放列表

```
POST /api/local-music/add
```

**请求体：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path` | string | ✅ | 服务器上的文件路径 |
| `title` | string | ❌ | 标题 |
| `artist` | string | ❌ | 艺术家 |

**响应：**

```json
{
  "status": "ok",
  "track_id": "local_xyz"
}
```

---

## 歌词搜索

### 搜索歌词

```
GET /api/lyrics/search?title=Song&artist=Artist&source=lrclib
```

**查询参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `title` | string | ✅ | 歌曲标题 |
| `artist` | string | ❌ | 艺术家 |
| `source` | string | ❌ | 歌词源：`lrclib` / `lrclib-alt` / `netease`（默认 lrclib） |

**歌词源说明：**

| 源 | 特点 |
|----|------|
| `lrclib` | 开源歌词库，支持同步歌词 |
| `lrclib-alt` | LRCLIB 备用搜索接口 |
| `netease` | 网易云音乐歌词，中文歌词覆盖更广 |

**响应：**

```json
{
  "lyrics": "[00:00.00]第一句歌词\n[00:05.20]第二句歌词\n...",
  "synced": true,
  "source": "lrclib"
}
```

---

## 用户管理

### 获取在线用户列表

```
GET /api/users
```

需要 Admin 认证。

**响应：**

```json
{
  "users": [
    {
      "uid": "abc123",
      "username": "听众小明",
      "ip": "192.168.1.100",
      "duration": 300,
      "connected_at": "2026-04-26T10:00:00"
    }
  ],
  "count": 1
}
```

### 踢出用户

```
POST /api/users/kick
```

需要 Admin 认证。

**请求体：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `uid` | string | ✅ | 要踢出的用户 UID |

**响应：**

```json
{
  "status": "ok"
}
```

被踢出的用户会收到 WebSocket `kicked` 消息并自动断开连接。

---

## 系统维护

### 手动触发清理

```
POST /api/cleanup
```

需要 Admin 认证。清理上传的临时文件（仅删除 `upload` 类型的曲目，保留 `local` 和 `url` 类型）。

**响应：**

```json
{
  "status": "ok",
  "cleaned": 3
}
```

### 自动清理

系统每天凌晨 00:00 自动执行清理，正在播放的曲目会被跳过。

---

## WebSocket 实时通信

### 连接

```
WS /ws
```

连接后服务器立即发送 `init` 消息，包含当前状态。

### 客户端 → 服务器

| 消息类型 | 字段 | 说明 |
|----------|------|------|
| `set_username` | `username` | 设置用户名 |
| `chat` | `message` | 发送聊天消息 |
| `report_duration` | `duration` | 上报收听时长（秒） |
| `admin_auth` | `token` | Admin 认证 |

**示例：**

```javascript
ws.send(JSON.stringify({
  type: "set_username",
  username: "听众小明"
}));
```

### 服务器 → 客户端

| 消息类型 | 字段 | 说明 |
|----------|------|------|
| `init` | `uid`, `playlist`, `now_playing`, `user_count`, `auto_loop` | 初始化数据 |
| `now_playing` | `track`, `position`, `is_playing` | 播放状态变更 |
| `position_update` | `position` | 播放进度更新（每秒推送） |
| `seek` | `position` | DJ 跳转进度同步 |
| `playlist_update` | `playlist` | 播放列表变更 |
| `chat` | `username`, `message`, `uid` | 聊天消息 |
| `user_count` | `count` | 在线人数变更 |
| `kicked` | — | 被踢出通知 |

**init 消息示例：**

```json
{
  "type": "init",
  "uid": "user_abc123",
  "playlist": [...],
  "now_playing": {
    "track": { "id": "xyz", "title": "Song", "artist": "Artist" },
    "position": 45.2,
    "is_playing": true
  },
  "user_count": 5,
  "auto_loop": true
}
```

### 连接流程示例

```
客户端                              服务器
  |                                    |
  |---- WS Connect /ws --------------->|
  |<--- init (uid, playlist, ...) -----|
  |                                    |
  |---- set_username ----------------->|
  |                                    |
  |<--- position_update (每秒) --------|
  |<--- now_playing (曲目变更) --------|
  |<--- playlist_update (列表变更) ----|
  |                                    |
  |---- chat ------------------------->|
  |<--- chat --------------------------|
  |                                    |
```

---

## 曲目数据结构

每首曲目（Track）包含以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 唯一标识 |
| `title` | string | 歌曲标题 |
| `artist` | string | 艺术家 |
| `duration` | float | 时长（秒） |
| `source_type` | string | 来源类型：`upload` / `local` / `url` |
| `url` | string | 音频流地址（URL 类型时为原始链接） |
| `cover_url` | string | 封面图地址 |
| `filename` | string | 文件名（upload 类型） |
| `file_path` | string | 服务器路径（local 类型） |
| `added_at` | string | 添加时间（ISO 8601） |

### source_type 说明

| 类型 | 说明 | 清理策略 |
|------|------|----------|
| `upload` | 通过 API 上传的文件 | ⚠️ 可被定时清理 |
| `local` | 从本地目录添加 | ✅ 不会被清理 |
| `url` | 通过 URL 添加 | ✅ 不会被清理 |

---

## 错误码

| HTTP 状态码 | 说明 |
|-------------|------|
| 200 | 请求成功 |
| 400 | 请求参数错误 |
| 401 | 未认证 / Token 无效 |
| 403 | 无权限（非 Admin） |
| 404 | 资源未找到 |
| 413 | 文件过大（超过 100MB） |
| 500 | 服务器内部错误 |

---

## 快速上手

### 安装依赖

```bash
pip install -r requirements.txt
```

### 启动服务

```bash
python server.py
```

服务默认运行在 `http://0.0.0.0:8765`。

### Nginx 反代配置要点

```nginx
location / {
    proxy_pass http://127.0.0.1:8765;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    client_max_body_size 100m;
}
```

> ⚠️ 必须在 `http` 块中添加 `map` 指令以支持 WebSocket：

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    '' close;
}
```

---

*Music Radio Station © 2026*
