# 🎧 Music Radio Station

[![中文](https://img.shields.io/badge/语言-中文-blue)](./README.md) [![English](https://img.shields.io/badge/Language-English-lightgrey)](./README_en.md)

> Self-hosted live music radio station — FastAPI + WebSocket, with DJ console & listener sync

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green?logo=fastapi)
![WebSocket](https://img.shields.io/badge/WebSocket-Realtime-orange)
[![Demo](https://img.shields.io/badge/Demo-fm.yuhanghome.icu-brightgreen?style=flat)](https://fm.yuhanghome.icu/)

---

## ✨ Features

- 🎵 **Three track sources** — File upload / URL import / Local music directory browsing
- 📡 **WebSocket real-time sync** — Listeners auto-follow DJ playback, zero-delay switching
- 🔄 **Server-driven loop playback** — Auto-advance when a song ends, keeps playing even if DJ closes the browser
- 📊 **Stream & seek** — HTTP Range request streaming, instant seek support
- 🎤 **Multi-source lyrics** — LRCLIB / NetEase Cloud Music, synced LRC support
- 🖼️ **Auto cover extraction** — MP3/M4A/FLAC/OGG/WMA embedded cover art
- 🗑️ **Scheduled cleanup** — Daily at 00:00, auto-cleans uploaded cache (skips if playing)
- 🎛️ **DJ Console** — Playback control, drag-to-reorder playlist, listener management, kick users
- 💬 **Live chat** — Real-time interaction between listeners and DJ
- 📱 **Mobile-friendly** — Responsive layout, touch-optimized
- 🌙 **Apple Music Night theme** — Dark glassmorphism UI

## 📸 Screenshots

| Listener Player | DJ Console |
|:---:|:---:|
| ![Player](screenshots/player.png) | ![Admin](screenshots/admin.png) |

> 🎧 **Live Demo**: [https://fm.yuhanghome.icu/](https://fm.yuhanghome.icu/)

---

## 🏗️ Architecture

### Overview

```
┌─────────────┐     WebSocket      ┌──────────────────────────────┐
│  🎧 Player   │◄──────────────────►│                              │
│  (Listener)  │                    │     🖥️ server.py             │
├─────────────┤     WebSocket      │  ┌────────────────────────┐  │
│  🎛️ Admin   │◄──────────────────►│  │   RadioState (memory)  │  │
│  (DJ Console)│                    │  │  - playlist            │  │
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
                                   │  │  Runs every second:    │  │
                                   │  │  → Auto-advance on end │  │
                                   │  │  → Broadcast position  │  │
                                   │  │  → Auto-start if idle  │  │
                                   │  └────────────────────────┘  │
                                   └──────────────────────────────┘
```

### Core Principles

1. **Server-driven playback**: All playback state lives in `RadioState` — no client dependency. DJ closes the browser, music keeps playing
2. **WebSocket broadcast sync**: State changes immediately `broadcast()` to all connected clients — listeners follow with zero delay
3. **Unified track abstraction**: Upload, URL, and local directory sources are all abstracted as `track` objects. `/stream/{id}` auto-routes based on `source_type`

---

## 🧠 API Implementation Principles

### 1. Playback State Management — RadioState

All playback state is centralized in a single in-memory object — no database needed:

```python
class RadioState:
    playlist: List[dict]        # Ordered playlist
    current_index: int          # Current track index
    is_playing: bool            # Is currently playing
    play_start_time: float      # time.time() when playback started
    play_position: float        # Offset in seconds at start
    auto_loop: bool             # Auto-loop mode
    admin_paused: bool          # DJ manually paused flag
```

**Position calculation**: No client reporting needed — the server calculates it:

```python
def get_position(self, track_duration=0) -> float:
    if self.is_playing:
        elapsed = time.time() - self.play_start_time
        pos = self.play_position + elapsed
        if track_duration > 0 and pos > track_duration:
            return track_duration  # Clamp overflow
        return pos
    return self.play_position
```

**admin_paused flag**: Distinguishes between "never started" and "DJ manually paused" — when a song ends naturally, `admin_paused=False`, allowing auto_loop to resume; when DJ hits pause, `admin_paused=True`, preventing auto_loop from auto-resuming.

### 2. Auto-Loop Playback — tick_position()

A background coroutine running every second — the heartbeat of the system:

```
Every second:
├── Playing + song ended (position >= duration - 0.5s)
│   ├── auto_loop=True  → Advance to next track (loop), broadcast now_playing
│   └── auto_loop=False → Stop playback, broadcast now_playing(is_playing=false)
├── Playing + not ended
│   └── Broadcast position_update (sync listener progress bars)
└── Not playing + auto_loop=True + admin_paused=False + has tracks
    └── Auto-start playback (covers "added songs but didn't press play" etc.)
```

Switches 0.5s before the end to minimize silence gaps.

### 3. Audio Streaming — Range Requests

`/stream/{track_id}` auto-routes based on `source_type`:

| source_type | Handling |
|-------------|----------|
| `upload` | Read from `uploads/music/`, supports Range requests |
| `url` | 302 redirect to original URL (browser loads remote resource directly) |
| `local` | 302 redirect to `/api/local-music/stream/{path}` |

**Range request implementation** (upload type):

```
1. Parse Range header: "bytes=0-1048575"
2. Validate range: start >= 0, end < file_size
3. Return 206 Partial Content + Content-Range header
4. Use async generator file_stream() for chunked reading
```

This enables browsers to stream while downloading — seeking only requires a new Range request.

### 4. File Upload & Metadata Extraction

Upload flow:

```
POST /api/upload/music (multipart/form-data)
│
├── 1. Generate UUID as track_id
├── 2. Save file to uploads/music/{track_id}.mp3
├── 3. extract_metadata() auto-extracts:
│   ├── Title/Artist/Album (mutagen ID3/MP4/Vorbis/FLAC/ASF)
│   ├── Cover art → saved to uploads/covers/{track_id}.jpg
│   ├── Duration (mutagen.info.length)
│   └── Embedded lyrics (USLT/SYLT/lyrics tag)
├── 4. Build track object, add to state.playlist
└── 5. Broadcast playlist_update
```

**Cover extraction** supports 5 audio formats:

| Format | Library | Cover Field |
|--------|---------|-------------|
| MP3 | mutagen.id3 | APIC frame |
| M4A/AAC | mutagen.mp4 | covr tag (0x0d=JPEG, 0x0e=PNG) |
| FLAC | mutagen.flac | FLAC.pictures[0] |
| OGG/Opus | mutagen.oggvorbis | metadata_block_picture (Base64-encoded Vorbis Comment) |
| WMA | mutagen.asf | WM/Picture |

### 5. WebSocket Real-Time Communication — WSManager

```python
class WSManager:
    clients: Dict[str, ClientInfo]   # uid → WebSocket connection info

    async def broadcast(msg)         # Broadcast to all clients
    async def send_to(uid, msg)      # Send to specific user
```

**Connection lifecycle**:

```
Client connects WS /ws
│
├── Assign uid, create ClientInfo
├── Send init message (uid, playlist, now_playing, user_count, auto_loop)
├── Broadcast user_count update
│
├── [Runtime] Receive client messages:
│   ├── set_username → Update username
│   ├── chat → Broadcast chat message
│   ├── report_duration → Report listening duration
│   └── admin_auth → Token authentication
│
├── [Runtime] Server pushes:
│   ├── position_update (every second)
│   ├── now_playing (track change)
│   ├── playlist_update (list change)
│   ├── seek (DJ seek sync)
│   └── user_count (count change)
│
└── Disconnect → Remove client, broadcast user_count
```

### 6. Lyrics Search — Multi-Source Strategy

`GET /api/lyrics/search?title=&artist=&source=` supports three sources:

| Source | Search Strategy | Best For |
|--------|----------------|----------|
| `lrclib` | Exact search first `?track_name=&artist_name=`, fall back to fuzzy `?q=` on 404 | Default source, English/Japanese lyrics |
| `lrclib-alt` | Fuzzy search, sort by match score, return 2nd result (different version) | Alternative lyrics for the same song |
| `netease` | NetEase Cloud Music search API → first result → lyrics API | Better Chinese lyrics coverage |

Prefers `syncedLyrics` (synced LRC format), falls back to `plainLyrics`.

### 7. Local Music Browsing — Security Design

`/api/local-music/browse` only returns relative paths — never exposes server absolute paths:

```
Request: GET /api/local-music/browse?path=Album1
                         ↓
_safe_local_path("Album1")
├── Resolve: LOCAL_MUSIC_DIR / "Album1" → absolute path
├── Security check: resolve() must start with LOCAL_MUSIC_DIR (prevent path traversal)
└── Return relative path: "Album1/song.mp3" (no /data/music prefix)
```

**Path traversal protection**: `_safe_local_path()` resolves symlinks via `resolve()`, then verifies the target path is under `LOCAL_MUSIC_DIR`.

### 8. Scheduled Cleanup

A background coroutine running daily at 00:00:

```
daily_cleanup():
│
├── Calculate seconds until next 00:00
├── Sleep and wait
├── Check: currently playing? → Skip, retry tomorrow
├── Clean uploads/music/ files not referenced by any playlist track
├── Clean orphaned covers in uploads/covers/
└── Only delete source_type="upload" tracks (preserve local and url)
```

---

## 📖 API Usage

### Authentication

The DJ console requires password authentication. Passwords are transmitted as **SHA-256 hashes** (never plaintext):

```bash
# 1. Compute SHA-256 hash of your password
echo -n "your_password" | sha256sum
# Output: a1b2c3d4...

# 2. Authenticate with the hash
curl -X POST http://localhost:8765/api/admin/auth \
  -H "Content-Type: application/json" \
  -d '{"password": "a1b2c3d4..."}'

# Returns: {"status": "ok", "token": "xxx"}
```

For authenticated endpoints, pass the token as a URL parameter:
```bash
curl http://localhost:8765/api/users?token=xxx
```

### Playback Control

```bash
# Play
curl -X POST http://localhost:8765/api/playback/play?token=xxx

# Pause
curl -X POST http://localhost:8765/api/playback/pause?token=xxx

# Next track
curl -X POST http://localhost:8765/api/playback/next?token=xxx

# Seek to 60 seconds
curl -X POST http://localhost:8765/api/playback/seek?token=xxx \
  -H "Content-Type: application/json" \
  -d '{"position": 60}'

# Play 3rd track (0-indexed)
curl -X POST http://localhost:8765/api/playback/play-index?token=xxx \
  -H "Content-Type: application/json" \
  -d '{"index": 2}'

# Toggle auto-loop
curl -X POST http://localhost:8765/api/playback/auto-loop?token=xxx \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

### Playlist Management

```bash
# Get playlist
curl http://localhost:8765/api/playlist

# Add track by URL
curl -X POST http://localhost:8765/api/playlist/add?token=xxx \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/song.mp3", "title": "My Song"}'

# Delete track
curl -X DELETE http://localhost:8765/api/playlist/{track_id}?token=xxx

# Reorder (pass new ID order)
curl -X PUT http://localhost:8765/api/playlist/reorder?token=xxx \
  -H "Content-Type: application/json" \
  -d '{"track_ids": ["id3", "id1", "id2"]}'

# Update track info
curl -X PUT http://localhost:8765/api/playlist/track/{track_id}?token=xxx \
  -H "Content-Type: application/json" \
  -d '{"title": "New Title", "artist": "New Artist"}'
```

### File Upload

```bash
# Upload music files (supports multiple)
curl -X POST http://localhost:8765/api/upload/music?token=xxx \
  -F "files=@song1.mp3" \
  -F "files=@song2.flac"

# Upload cover art
curl -X POST http://localhost:8765/api/upload/cover/{track_id}?token=xxx \
  -F "file=@cover.jpg"
```

Auto-extracts on upload: title, artist, album, duration, cover art, embedded lyrics.

### Audio Streaming

```bash
# Full download
curl http://localhost:8765/stream/{track_id} -o song.mp3

# Range request (resume from 1MB)
curl -H "Range: bytes=1048576-" http://localhost:8765/stream/{track_id} \
  -o song_partial.mp3
```

### Local Music

```bash
# Browse root directory
curl http://localhost:8765/api/local-music/browse

# Browse subdirectory
curl "http://localhost:8765/api/local-music/browse?path=Album1"

# Add local music to playlist
curl -X POST http://localhost:8765/api/local-music/add?token=xxx \
  -H "Content-Type: application/json" \
  -d '{"path": "Album1/song.mp3"}'
```

### Lyrics Search

```bash
# LRCLIB search (default)
curl "http://localhost:8765/api/lyrics/search?title=Bohemian+Rhapsody&artist=Queen"

# NetEase search
curl "http://localhost:8765/api/lyrics/search?title=晴天&artist=周杰伦&source=netease"

# LRCLIB alternate version
curl "http://localhost:8765/api/lyrics/search?title=Yesterday&source=lrclib-alt"
```

### User Management

```bash
# View online users
curl http://localhost:8765/api/users?token=xxx

# Kick user
curl -X POST http://localhost:8765/api/users/kick?token=xxx \
  -H "Content-Type: application/json" \
  -d '{"uid": "user_xxx"}'
```

### WebSocket Connection

```javascript
// Connect
const ws = new WebSocket('ws://localhost:8765/ws');

// Receive messages
ws.onmessage = (e) => {
  const data = JSON.parse(e.data);
  switch(data.type) {
    case 'init':           // { uid, playlist, now_playing, user_count, auto_loop }
    case 'now_playing':    // { track, position, is_playing }
    case 'position_update':// { position } — pushed every second
    case 'playlist_update':// { playlist }
    case 'seek':           // { position } — DJ seek sync
    case 'chat':           // { username, message }
    case 'user_count':     // { count }
    case 'kicked':         // Kicked from room
  }
};

// Set username
ws.send(JSON.stringify({ type: 'set_username', username: 'Listener' }));

// Send chat message
ws.send(JSON.stringify({ type: 'chat', message: 'Great song!' }));

// Report listening duration
ws.send(JSON.stringify({ type: 'report_duration', duration: 120 }));
```

---

## 📡 API Endpoints

| Category | Endpoint | Method | Auth | Description |
|----------|----------|--------|:----:|-------------|
| **Auth** | `/api/admin/auth` | POST | ❌ | Admin password auth |
| | `/api/admin/verify` | GET | ❌ | Verify token validity |
| | `/api/login` | POST | ❌ | Set username |
| | `/api/logout` | POST | ❌ | Clear username |
| | `/api/check` | GET | ❌ | Check login status |
| **Playback** | `/api/playback/play` | POST | ✅ | Resume playback |
| | `/api/playback/pause` | POST | ✅ | Pause |
| | `/api/playback/next` | POST | ✅ | Next track |
| | `/api/playback/prev` | POST | ✅ | Previous track |
| | `/api/playback/seek` | POST | ✅ | Seek to position |
| | `/api/playback/play-index` | POST | ✅ | Play specific track |
| | `/api/playback/auto-loop` | POST | ✅ | Toggle auto-loop |
| | `/api/status` | GET | ❌ | Current playback status |
| **Playlist** | `/api/playlist` | GET | ❌ | Get playlist |
| | `/api/playlist/list` | POST | ❌ | Batch get tracks |
| | `/api/playlist/add` | POST | ✅ | Add track by URL |
| | `/api/playlist/reorder` | PUT | ✅ | Reorder tracks |
| | `/api/playlist/{id}` | DELETE | ✅ | Delete track |
| | `/api/playlist/track/{id}` | PUT | ✅ | Update track info |
| **Upload** | `/api/upload/music` | POST | ✅ | Upload audio file |
| | `/api/upload/cover/{id}` | POST | ✅ | Upload cover art |
| **Stream** | `/stream/{id}` | GET | ❌ | Stream audio (Range) |
| **Local Music** | `/api/local-music/browse` | GET | ❌ | Browse directories |
| | `/api/local-music/stream/{path}` | GET | ❌ | Stream local file |
| | `/api/local-music/add` | POST | ✅ | Add to playlist |
| **Lyrics** | `/api/lyrics/search` | GET | ❌ | Multi-source lyrics |
| **Users** | `/api/users` | GET | ✅ | Online user list |
| | `/api/users/kick` | POST | ✅ | Kick user |
| **Maintenance** | `/api/cleanup` | POST | ✅ | Manual cleanup |
| **WebSocket** | `/ws` | WS | ❌ | Real-time bidirectional |

👉 **Full API Reference**: [API.md](./API.md)

---

## 🚀 Quick Start

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Start Server

```bash
python server.py
```

Server runs at `http://0.0.0.0:8765` by default.

### Access

| Page | URL |
|------|-----|
| 🎧 Listener Player | `http://localhost:8765/player` |
| 🎛️ DJ Console | `http://localhost:8765/admin` |

### Configuration

**Admin password**: Modify `ADMIN_PASSWORD_HASH` in `server.py`:

```python
ADMIN_PASSWORD_HASH = _hash_pwd("your_password")
```

**Local music directory**: Modify `LOCAL_MUSIC_DIR` in `server.py`:

```python
LOCAL_MUSIC_DIR = Path("/path/to/your/music")
```

---

## 📁 Project Structure

```
music-radio/
├── server.py              # FastAPI backend (all APIs + WebSocket, single file)
├── requirements.txt       # Python dependencies
├── API.md                 # Full API reference
├── DEPLOY_GUIDE.md        # Deployment guide
├── .gitignore
├── static/
│   ├── player.html        # Listener player (zero-framework vanilla JS)
│   └── admin.html         # DJ console (zero-framework vanilla JS)
├── screenshots/
│   ├── player.png         # Listener page screenshot
│   └── admin.png          # DJ console screenshot
└── uploads/               # Generated at runtime
    ├── music/             # Uploaded audio files
    └── covers/            # Extracted cover art
```

---

## 🌐 Deployment

### Nginx Reverse Proxy

```nginx
# Add in http block (WebSocket support)
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

### Systemd Service (Optional)

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

### Deployment Notes

| Item | Note |
|------|------|
| **Python env** | Must use a virtualenv; system Python may be restricted |
| **Upload size** | Nginx requires `client_max_body_size 100m` |
| **WebSocket** | Must configure `map $http_upgrade`, otherwise WS connections fail |
| **Line endings** | Fix CRLF → LF after uploading files from Windows |
| **Dependencies** | `pip install "uvicorn[standard]"` for full WebSocket support |

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.10+ · FastAPI · WebSocket · Uvicorn |
| **Metadata** | mutagen (cover/lyrics/tag extraction for MP3/M4A/FLAC/OGG/WMA) |
| **Frontend** | Vanilla HTML/CSS/JS (zero dependencies, single-file SPA) |
| **Communication** | WebSocket real-time bidirectional + HTTP REST API |
| **Audio** | HTTP Range streaming (stream-while-downloading + seek) |

---

## 📄 License

MIT License
