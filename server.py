#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Music Radio Station - Backend Server
FastAPI + WebSocket 实时通信
Linux 兼容版本
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uuid
import shutil
import time
import asyncio
import hashlib
import json
import secrets
import mimetypes
import os
import struct
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from datetime import datetime, timedelta
import logging

app = FastAPI(title="Music Radio Station")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("music-radio")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ Directories ============
BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads" / "music"
COVER_DIR = BASE_DIR / "uploads" / "covers"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
COVER_DIR.mkdir(parents=True, exist_ok=True)

# 本地音乐目录（只读浏览，不删除此目录下任何内容）
LOCAL_MUSIC_DIR = Path("/data/music")  # ⚠️ 请修改为你的本地音乐目录

app.mount("/uploads", StaticFiles(directory=BASE_DIR / "uploads"), name="uploads")

# ============ Audio Streaming ============
@app.get("/stream/{track_id}")
async def stream_audio(track_id: str, request: Request):
    """音频流式传输端点，支持Range请求实现边下边播"""
    # 查找曲目
    track = next((t for t in state.playlist if t["id"] == track_id), None)
    if not track:
        raise HTTPException(404, "曲目不存在")
    
    # 获取文件路径
    if track.get("source_type") == "url":
        # 如果是URL添加的曲目，重定向到原始URL
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=track["url"])
    
    if track.get("source_type") == "local":
        # 本地音乐文件，重定向到本地流式传输端点
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=f"/api/local-music/stream/{track.get('local_path', '')}")
    
    file_path = BASE_DIR / "uploads" / "music" / track["filename"]
    if not file_path.exists():
        raise HTTPException(404, "音频文件不存在")
    
    # 获取文件大小和MIME类型
    file_size = file_path.stat().st_size
    mime_type, _ = mimetypes.guess_type(str(file_path))
    if not mime_type:
        mime_type = "audio/mpeg"  # 默认MP3
    
    # 检查Range请求
    range_header = request.headers.get("range")
    
    if not range_header:
        # 如果没有Range请求，返回整个文件
        return FileResponse(
            file_path,
            media_type=mime_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
                "Content-Type": mime_type,
                "Cache-Control": "public, max-age=3600"
            }
        )
    
    # 解析Range头
    try:
        range_type, range_value = range_header.split("=")
        if range_type.strip() != "bytes":
            raise ValueError("Invalid range type")
        
        start_str, end_str = range_value.split("-")
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1
        
        # 验证范围
        if start < 0 or start >= file_size or end >= file_size or start > end:
            raise ValueError("Invalid range")
        
        chunk_size = end - start + 1
        
        # 读取文件块
        async def file_stream():
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = chunk_size
                while remaining > 0:
                    chunk = f.read(min(8192, remaining))
                    if not chunk:
                        break
                    yield chunk
                    remaining -= len(chunk)
        
        # 返回部分内容响应
        return StreamingResponse(
            file_stream(),
            status_code=206,  # Partial Content
            media_type=mime_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(chunk_size),
                "Accept-Ranges": "bytes",
                "Cache-Control": "public, max-age=3600"
            }
        )
    
    except Exception as e:
        log.error(f"Range request error: {e}")
        # 如果Range请求解析失败，返回整个文件
        return FileResponse(
            file_path,
            media_type=mime_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
                "Content-Type": mime_type,
                "Cache-Control": "public, max-age=3600"
            }
        )


# ============ Auth ============
AUTH_FILE = BASE_DIR / "auth.json"
SESSIONS: Dict[str, float] = {}
SESSION_TTL = 86400

def _hash_pwd(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()

def _load_auth() -> dict:
    if AUTH_FILE.exists():
        return json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    default = {"username": "admin", "password_hash": _hash_pwd("admin")}
    AUTH_FILE.write_text(json.dumps(default, ensure_ascii=False), encoding="utf-8")
    return default

def _save_auth(data: dict):
    AUTH_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

def _clean_sessions():
    now = time.time()
    expired = [t for t, exp in SESSIONS.items() if exp < now]
    for t in expired:
        del SESSIONS[t]

def _create_token() -> str:
    _clean_sessions()
    token = secrets.token_hex(32)
    SESSIONS[token] = time.time() + SESSION_TTL
    return token

def _verify_token(token: str) -> bool:
    if not token:
        return False
    _clean_sessions()
    return token in SESSIONS

def _get_token(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get("token")

async def _auth_middleware(request: Request, call_next):
    return await call_next(request)

app.middleware("http")(_auth_middleware)


# ============ Auth API ============
@app.post("/api/auth/login")
async def login(body: dict):
    auth = _load_auth()
    if body.get("username") != auth["username"] or _hash_pwd(body.get("password", "")) != auth["password_hash"]:
        raise HTTPException(401, "用户名或密码错误")
    token = _create_token()
    from fastapi.responses import JSONResponse
    resp = JSONResponse({"token": token, "username": auth["username"]})
    resp.set_cookie("token", token, httponly=True, max_age=SESSION_TTL, samesite="lax")
    return resp


@app.post("/api/auth/logout")
async def logout(request: Request):
    token = _get_token(request)
    if token and token in SESSIONS:
        del SESSIONS[token]
    from fastapi.responses import JSONResponse
    resp = JSONResponse({"message": "已退出"})
    resp.delete_cookie("token")
    return resp


@app.get("/api/auth/check")
async def auth_check(request: Request):
    token = _get_token(request)
    if _verify_token(token):
        return {"authenticated": True, "username": _load_auth()["username"]}
    return {"authenticated": False}


# Admin 专用密码认证（固定密码，SHA-256 哈希传输）
ADMIN_PASSWORD_HASH = _hash_pwd("changeme")  # ⚠️ 请修改为你的密码

@app.post("/api/admin/auth")
async def admin_auth(body: dict):
    """Admin 控制台密码认证，客户端发送 SHA-256(password) 的哈希值"""
    client_hash = body.get("password_hash", "")
    if client_hash == ADMIN_PASSWORD_HASH:
        token = _create_token()
        from fastapi.responses import JSONResponse
        resp = JSONResponse({"success": True, "token": token})
        resp.set_cookie("admin_token", token, httponly=False, max_age=SESSION_TTL, samesite="lax")
        return resp
    raise HTTPException(401, "密码错误")


@app.get("/api/admin/verify")
async def admin_verify(request: Request):
    """验证 admin token 是否有效"""
    token = request.query_params.get("token", "") or request.headers.get("Authorization", "").replace("Bearer ", "")
    if _verify_token(token):
        return {"valid": True}
    return {"valid": False}


# ============ State ============
class RadioState:
    def __init__(self):
        self.playlist: List[dict] = []
        self.current_index: int = -1
        self.is_playing: bool = False
        self.play_start_time: float = 0.0
        self.play_position: float = 0.0
        self.current_track_id: str = ""
        # 自动循环播放模式：歌曲播完自动下一首，主播关闭页面也不停
        self.auto_loop: bool = True
        # 无 duration 信息的曲目最大播放秒数（600秒兜底，等待 report_duration 上报真实时长）
        self.max_play_duration: float = 600.0
        # 主播主动暂停标志：区分"从未开始"和"主动暂停"
        # True = 主播点了暂停，auto_loop 不应自动恢复
        # False = 从未操作/歌曲自然结束，auto_loop 可以自动开始
        self.admin_paused: bool = False

    def get_position(self, track_duration: float = 0) -> float:
        if self.is_playing:
            elapsed = time.time() - self.play_start_time
            pos = self.play_position + elapsed
            if track_duration > 0 and pos > track_duration:
                return track_duration
            return pos
        return self.play_position

    def get_current_track(self) -> Optional[dict]:
        if 0 <= self.current_index < len(self.playlist):
            return self.playlist[self.current_index]
        return None


state = RadioState()


# ============ WebSocket ============
class ClientInfo:
    def __init__(self, ws: WebSocket, uid: str, username: str = "匿名", client_ip: str = ""):
        self.ws = ws
        self.uid = uid
        self.username = username
        self.client_ip = client_ip
        self.connected_at = time.time()
        self.is_admin = False


class WSManager:
    def __init__(self):
        self.clients: Dict[str, ClientInfo] = {}
        self.banned_uids: set = set()

    async def connect(self, ws: WebSocket, client_ip: str = "") -> ClientInfo:
        await ws.accept()
        uid = str(uuid.uuid4())[:8]
        client = ClientInfo(ws, uid, client_ip=client_ip)
        self.clients[uid] = client
        return client

    def disconnect_by_ws(self, ws: WebSocket):
        to_remove = [c for c in self.clients.values() if c.ws is ws]
        for c in to_remove:
            del self.clients[c.uid]
        return len(to_remove) > 0

    async def kick(self, uid: str, reason: str = ""):
        if uid in self.clients:
            try:
                await self.clients[uid].ws.send_json({
                    "type": "kicked",
                    "reason": reason or "你已被主播移出直播间",
                })
                await self.clients[uid].ws.close(code=4003, reason=reason or "kicked")
            except Exception:
                pass
            del self.clients[uid]

    def update_username(self, uid: str, username: str):
        if uid in self.clients:
            self.clients[uid].username = username

    def get_user_list(self) -> list:
        return [
            {
                "uid": c.uid,
                "username": c.username,
                "ip": c.client_ip,
                "connected_at": c.connected_at,
                "duration": int(time.time() - c.connected_at),
            }
            for c in self.clients.values()
        ]

    async def broadcast(self, msg: dict, exclude_uid: str = None):
        dead = []
        for uid, c in self.clients.items():
            if exclude_uid and uid == exclude_uid:
                continue
            try:
                await c.ws.send_json(msg)
            except Exception:
                dead.append(uid)
        for uid in dead:
            self.disconnect_by_ws(self.clients[uid].ws)

    async def broadcast_all(self, msg: dict):
        return await self.broadcast(msg)

    @property
    def count(self):
        return len(self.clients)


ws = WSManager()


async def tick_position():
    """每秒检查播放状态，自动切换下一首并广播位置更新。
    
    核心逻辑：
    - 歌曲播放完毕 → 自动下一首（循环）
    - duration=0 的曲目 → max_play_duration 兜底自动切歌
    - 播放列表有曲目但未在播放且 auto_loop=True → 自动开始播放
    - 主播关闭页面也不影响，服务端持续驱动播放
    """
    while True:
        await asyncio.sleep(1)
        track = state.get_current_track()

        if state.is_playing and track:
            dur = track.get("duration", 0) or 0
            # duration=0 的曲目，使用 max_play_duration 作为兜底时长
            effective_dur = dur if dur > 0 else state.max_play_duration
            current_pos = state.get_position(effective_dur)

            # 检查歌曲是否播放完毕（提前0.5秒切歌，减少空窗期）
            if effective_dur > 0 and current_pos >= effective_dur - 0.5:
                # 歌曲自然结束，清除暂停标志
                state.admin_paused = False
                if state.auto_loop and state.playlist:
                    # 自动播放下一首（循环）
                    state.current_index = (state.current_index + 1) % len(state.playlist)
                    state.play_position = 0
                    state.play_start_time = time.time()
                    state.current_track_id = state.playlist[state.current_index]["id"] if state.current_index >= 0 else ""
                    cur = state.get_current_track()
                    await ws.broadcast({
                        "type": "now_playing",
                        "track": cur,
                        "position": 0,
                        "is_playing": True,
                    })
                    log.info(f"[AutoLoop] Next track: {cur.get('title', 'Unknown')} (index={state.current_index})")
                else:
                    # 不循环，停止播放
                    state.is_playing = False
                    state.play_position = 0
                    await ws.broadcast({
                        "type": "now_playing",
                        "track": None,
                        "position": 0,
                        "is_playing": False,
                    })
                    log.info("[AutoLoop] Playback ended (auto_loop off or playlist empty)")
            else:
                # 正常广播位置更新
                real_pos = state.get_position(dur if dur > 0 else 0)
                await ws.broadcast({
                    "type": "position_update",
                    "track_id": track["id"],
                    "position": real_pos,
                    "is_playing": True,
                })

        elif state.auto_loop and not state.is_playing and not state.admin_paused and state.playlist:
            # 播放列表有曲目但未在播放，且主播未主动暂停 → 自动开始播放
            # 场景：主播添加了歌但没按播放 / 服务重启后恢复 / 歌曲自然结束后
            if state.current_index < 0 or state.current_index >= len(state.playlist):
                state.current_index = 0
            state.is_playing = True
            state.play_position = 0
            state.play_start_time = time.time()
            cur = state.get_current_track()
            if cur:
                state.current_track_id = cur["id"]
            await ws.broadcast({
                "type": "now_playing",
                "track": cur,
                "position": 0,
                "is_playing": True,
            })
            log.info(f"[AutoLoop] Auto-start playback: {cur.get('title', 'Unknown') if cur else 'None'} (index={state.current_index})")


# ============ Daily Cleanup Task ============
async def daily_cleanup():
    """每天 00:00:00 自动清理上传的音乐缓存文件。
    如果当前正在播放，则跳过本次清理，避免中断直播。
    """
    log.info("Daily cleanup task started, waiting for midnight...")
    while True:
        now = datetime.now()
        # 计算距离下一个 00:00:00 的秒数
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        wait_seconds = (tomorrow - now).total_seconds()
        log.info(f"Next cleanup at {tomorrow.strftime('%Y-%m-%d %H:%M:%S')}, waiting {int(wait_seconds)}s")
        await asyncio.sleep(wait_seconds)

        # 检查是否正在播放
        if state.is_playing:
            log.warning("Skip cleanup: admin is currently playing. Will retry next midnight.")
            continue

        log.info("Cleanup triggered: no active playback, proceeding...")
        removed_music = 0
        removed_covers = 0
        removed_size = 0

        # 1. 收集非上传曲目的封面文件名（这些不应被删除）
        preserved_covers = set()
        for t in state.playlist:
            if t.get("source_type") != "upload" and t.get("cover"):
                cover_name = t["cover"].split("/")[-1]
                preserved_covers.add(cover_name)

        # 2. 删除上传的音乐文件（UPLOAD_DIR 只有上传的缓存）
        for f in UPLOAD_DIR.iterdir():
            if f.is_file():
                removed_size += f.stat().st_size
                f.unlink()
                removed_music += 1

        # 3. 删除上传的封面文件，但保留本地/URL曲目的封面
        for f in COVER_DIR.iterdir():
            if f.is_file() and f.name not in preserved_covers:
                removed_size += f.stat().st_size
                f.unlink()
                removed_covers += 1

        # 4. 只从播放列表中移除上传的曲目，保留本地音乐和URL曲目
        kept_tracks = [t for t in state.playlist if t.get("source_type") != "upload"]
        removed_track_count = len(state.playlist) - len(kept_tracks)
        state.playlist = kept_tracks

        if kept_tracks:
            # 还有保留的曲目，调整索引继续播放
            if state.current_index >= len(kept_tracks):
                state.current_index = 0
            state.admin_paused = False
        else:
            state.current_index = -1
            state.is_playing = False
            state.play_position = 0
            state.play_start_time = 0
            state.current_track_id = ""
            state.admin_paused = False

        # 5. 广播通知
        await ws.broadcast({
            "type": "playlist_update",
            "playlist": state.playlist,
        })
        if not kept_tracks:
            await ws.broadcast({
                "type": "now_playing",
                "track": None,
                "position": 0,
                "is_playing": False,
            })
        # 发送清理通知消息到聊天
        kept_info = f"，保留 {len(kept_tracks)} 首本地/URL曲目" if kept_tracks else ""
        await ws.broadcast({
            "type": "chat",
            "id": str(uuid.uuid4())[:8],
            "username": "系统",
            "message": f"每日清理完成：删除 {removed_music} 个上传缓存、{removed_covers} 个封面、{removed_track_count} 首上传曲目，释放 {removed_size / 1024 / 1024:.1f} MB{kept_info}",
            "role": "admin",
            "timestamp": datetime.now().strftime("%H:%M"),
        })

        log.info(f"Cleanup done: removed {removed_music} uploads, {removed_covers} covers, {removed_track_count} upload tracks, freed {removed_size / 1024 / 1024:.1f} MB, kept {len(kept_tracks)} tracks")


@app.on_event("startup")
async def _startup():
    asyncio.create_task(tick_position())
    asyncio.create_task(daily_cleanup())


# ============ Upload API ============
AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac", ".mp4", ".webm", ".opus", ".wma", ".ape", ".alac"}


def extract_metadata(file_path: Path, track_id: str):
    """从音频文件中提取封面、元数据（标题、艺术家）和歌词"""
    result = {"cover": None, "title": None, "artist": None, "album": None, "duration": 0, "lyrics": None}
    ext = file_path.suffix.lower()

    try:
        import mutagen
        audio = mutagen.File(str(file_path), easy=True)
        if audio is None:
            return result

        # 提取标题和艺术家
        if audio.get("title"):
            result["title"] = audio["title"][0]
        if audio.get("artist"):
            result["artist"] = audio["artist"][0]
        if audio.get("album"):
            result["album"] = audio["album"][0]

        # 提取时长
        if hasattr(audio, 'info') and audio.info:
            result["duration"] = getattr(audio.info, 'length', 0) or 0

        # 提取封面 - 需要用非 easy 模式重新加载
        del audio  # 释放文件句柄

        if ext in (".mp3",):
            from mutagen.id3 import ID3
            try:
                tags = ID3(str(file_path))
                for tag in tags.values():
                    if tag.FrameID == "APIC":
                        cover_data = tag.data
                        # 判断图片格式
                        mime = getattr(tag, 'mime', 'image/jpeg')
                        cover_ext = ".jpg" if "jpeg" in mime or "jpg" in mime else ".png"
                        cover_name = f"{track_id}{cover_ext}"
                        with open(COVER_DIR / cover_name, "wb") as cf:
                            cf.write(cover_data)
                        result["cover"] = f"/uploads/covers/{cover_name}"
                        break
            except Exception:
                pass

        elif ext in (".m4a", ".mp4", ".aac", ".alac"):
            from mutagen.mp4 import MP4
            try:
                mp4 = MP4(str(file_path))
                if "covr" in mp4:
                    cover_data = mp4["covr"][0]
                    # M4A covr 格式: 0x00=implicit, 0x0d=jpeg, 0x0e=png
                    img_format = cover_data[:4] if len(cover_data) > 4 else b""
                    if img_format.startswith(b'\x89PNG') or (len(cover_data) > 0 and cover_data[0] == 0x0e):
                        cover_ext = ".png"
                    else:
                        cover_ext = ".jpg"
                    cover_name = f"{track_id}{cover_ext}"
                    with open(COVER_DIR / cover_name, "wb") as cf:
                        cf.write(cover_data)
                    result["cover"] = f"/uploads/covers/{cover_name}"
            except Exception:
                pass

        elif ext in (".flac",):
            from mutagen.flac import FLAC
            try:
                flac = FLAC(str(file_path))
                if flac.pictures:
                    pic = flac.pictures[0]
                    mime = pic.mime or "image/jpeg"
                    cover_ext = ".jpg" if "jpeg" in mime or "jpg" in mime else ".png"
                    cover_name = f"{track_id}{cover_ext}"
                    with open(COVER_DIR / cover_name, "wb") as cf:
                        cf.write(pic.data)
                    result["cover"] = f"/uploads/covers/{cover_name}"
            except Exception:
                pass

        elif ext in (".ogg", ".opus"):
            from mutagen.oggvorbis import OggVorbis
            from mutagen.oggopus import OggOpus
            try:
                ogg_cls = OggOpus if ext == ".opus" else OggVorbis
                ogg = ogg_cls(str(file_path))
                if "metadata_block_picture" in ogg:
                    import base64
                    for b64 in ogg["metadata_block_picture"]:
                        try:
                            pic_data = base64.b64decode(b64)
                            # Vorbis Comment 格式解析
                            offset = 0
                            pic_type = struct.unpack(">I", pic_data[offset:offset+4])[0]; offset += 4
                            mime_len = struct.unpack(">I", pic_data[offset:offset+4])[0]; offset += 4
                            mime = pic_data[offset:offset+mime_len].decode(); offset += mime_len
                            desc_len = struct.unpack(">I", pic_data[offset:offset+4])[0]; offset += 4
                            offset += desc_len  # skip description
                            width = struct.unpack(">I", pic_data[offset:offset+4])[0]; offset += 4
                            height = struct.unpack(">I", pic_data[offset:offset+4])[0]; offset += 4
                            offset += 8  # skip color depth + index
                            img_len = struct.unpack(">I", pic_data[offset:offset+4])[0]; offset += 4
                            img_data = pic_data[offset:offset+img_len]
                            cover_ext = ".jpg" if "jpeg" in mime or "jpg" in mime else ".png"
                            cover_name = f"{track_id}{cover_ext}"
                            with open(COVER_DIR / cover_name, "wb") as cf:
                                cf.write(img_data)
                            result["cover"] = f"/uploads/covers/{cover_name}"
                            break
                        except Exception:
                            continue
            except Exception:
                pass

        elif ext in (".wma",):
            from mutagen.asf import ASF
            try:
                asf = ASF(str(file_path))
                if "WM/Picture" in asf:
                    pic = asf["WM/Picture"][0]
                    cover_data = pic.value
                    # WMA 图片数据格式：可能带 BMP 头或直接是 JPEG
                    if cover_data[:2] == b'\xff\xd8':
                        cover_ext = ".jpg"
                    elif cover_data[:4] == b'\x89PNG':
                        cover_ext = ".png"
                    else:
                        cover_ext = ".jpg"
                    cover_name = f"{track_id}{cover_ext}"
                    with open(COVER_DIR / cover_name, "wb") as cf:
                        cf.write(cover_data)
                    result["cover"] = f"/uploads/covers/{cover_name}"
            except Exception:
                pass

        # ===== 歌词提取 =====
        # audio 已在封面提取时 del 释放，歌词提取重新加载文件
        try:
            if ext in (".mp3",):
                from mutagen.id3 import ID3, USLT, SYLT
                tags = ID3(str(file_path))
                # 1. 优先 USLT（未同步歌词，可能含 LRC/SRT/VTT 等格式）
                for frame in tags.values():
                    if frame.FrameID == "USLT":
                        lyrics_text = frame.text if hasattr(frame, 'text') else ''
                        if not lyrics_text and hasattr(frame, 'desc'):
                            lyrics_text = str(frame)
                        if lyrics_text:
                            result["lyrics"] = lyrics_text
                            break
                # 2. SYLT（同步歌词，ID3 内置时间戳）转 LRC 格式
                if not result["lyrics"]:
                    for frame in tags.values():
                        if frame.FrameID == "SYLT":
                            try:
                                lrc_lines = []
                                for item in frame:
                                    # SYLT item: (text, time_ms)
                                    if isinstance(item, tuple) and len(item) == 2:
                                        text, time_ms = item
                                        total_s = time_ms / 1000.0
                                        m = int(total_s // 60)
                                        s = total_s % 60
                                        lrc_lines.append(f"[{m:02d}:{s:06.3f}]{text}")
                                if lrc_lines:
                                    result["lyrics"] = "\n".join(lrc_lines)
                                    break
                            except Exception:
                                continue
            elif ext in (".m4a", ".mp4", ".aac", ".alac"):
                from mutagen.mp4 import MP4
                mp4 = MP4(str(file_path))
                if "lyrics" in mp4:
                    result["lyrics"] = mp4["lyrics"][0]
            elif ext in (".flac",):
                from mutagen.flac import FLAC
                flac = FLAC(str(file_path))
                if flac.get("lyrics"):
                    result["lyrics"] = flac["lyrics"][0]
            elif ext in (".ogg", ".opus"):
                from mutagen.oggvorbis import OggVorbis
                from mutagen.oggopus import OggOpus
                ogg_cls = OggOpus if ext == ".opus" else OggVorbis
                ogg = ogg_cls(str(file_path))
                if ogg.get("lyrics"):
                    result["lyrics"] = ogg["lyrics"][0]
            elif ext in (".wma",):
                from mutagen.asf import ASF
                asf = ASF(str(file_path))
                if "WM/Lyrics" in asf:
                    result["lyrics"] = str(asf["WM/Lyrics"][0])
        except Exception as e:
            log.debug(f"Lyrics extraction skipped for {file_path}: {e}")

    except ImportError:
        log.warning("mutagen not installed, skipping metadata extraction")
    except Exception as e:
        log.warning(f"Metadata extraction failed for {file_path}: {e}")

    return result

@app.post("/api/upload/music")
async def upload_music(files: List[UploadFile] = File(...)):
    tracks = []
    for f in files:
        ct = (f.content_type or "")
        ext = Path(f.filename).suffix.lower() if f.filename else ""
        # Accept by MIME type OR file extension
        is_audio = ct.startswith("audio/") or ct.startswith("video/") or ext in AUDIO_EXTS
        if not is_audio:
            continue
        tid = str(uuid.uuid4())[:8]
        ext = Path(f.filename).suffix
        fname = f"{tid}{ext}"
        save_path = UPLOAD_DIR / fname
        with open(save_path, "wb") as out:
            shutil.copyfileobj(f.file, out)

        # 自动提取封面和元数据
        meta = extract_metadata(save_path, tid)

        track = {
            "id": tid,
            "title": meta.get("title") or Path(f.filename).stem,
            "artist": meta.get("artist") or "未知艺术家",
            "album": meta.get("album") or "",
            "filename": fname,
            "url": f"/stream/{tid}",
            "cover": meta.get("cover"),
            "duration": meta.get("duration", 0),
            "lyrics": meta.get("lyrics") or None,
            "source_type": "upload",
        }
        tracks.append(track)
        state.playlist.append(track)
        if meta.get("cover"):
            log.info(f"Extracted cover for {tid}: {meta['cover']}")
        if meta.get("title") and meta["title"] != Path(f.filename).stem:
            log.info(f"Extracted title for {tid}: {meta['title']}")

    await ws.broadcast({"type": "playlist_update", "playlist": state.playlist})
    return {"tracks": tracks}


@app.post("/api/upload/cover/{track_id}")
async def upload_cover(track_id: str, file: UploadFile = File(...)):
    track = next((t for t in state.playlist if t["id"] == track_id), None)
    if not track:
        raise HTTPException(404, "曲目不存在")
    ext = Path(file.filename).suffix if file.filename else ".jpg"
    cname = f"{track_id}{ext}"
    with open(COVER_DIR / cname, "wb") as out:
        shutil.copyfileobj(file.file, out)
    track["cover"] = f"/uploads/covers/{cname}"

    cur = state.get_current_track()
    if cur and cur["id"] == track_id:
        await ws.broadcast({
            "type": "now_playing",
            "track": cur,
            "position": state.get_position(),
            "is_playing": state.is_playing,
        })
    await ws.broadcast({"type": "playlist_update", "playlist": state.playlist})
    return {"cover": track["cover"]}


# ============ Playlist API ============
@app.get("/api/playlist")
async def get_playlist():
    return {"playlist": state.playlist, "current_index": state.current_index}


@app.post("/api/playlist/list")
async def get_playlist_list():
    return {"tracks": state.playlist}


@app.post("/api/playlist/add")
async def add_track_by_url(body: dict):
    url = body.get("url", "").strip()
    if not url:
        raise HTTPException(400, "URL 不能为空")

    tid = str(uuid.uuid4())[:8]
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        name = (parsed.path or "").split("/")[-1] or "Unknown"
        name = Path(name).stem or "Unknown"
    except Exception:
        name = "Unknown"
    track = {
        "id": tid,
        "title": name,
        "artist": "URL 添加",
        "album": "",
        "filename": "",
        "url": url,
        "cover": None,
        "duration": 0,
        "lyrics": None,
        "source_type": "url",  # 标记为URL来源
    }
    state.playlist.append(track)
    await ws.broadcast({"type": "playlist_update", "playlist": state.playlist})
    return {"success": True, "tracks": state.playlist}


@app.put("/api/playlist/reorder")
async def reorder_playlist(body: dict):
    ids = body.get("track_ids", [])
    ordered = []
    for tid in ids:
        t = next((x for x in state.playlist if x["id"] == tid), None)
        if t:
            ordered.append(t)
    for t in state.playlist:
        if t["id"] not in ids:
            ordered.append(t)
    cur = state.get_current_track()
    state.playlist = ordered
    if cur:
        state.current_index = next(
            (i for i, t in enumerate(ordered) if t["id"] == cur["id"]), -1
        )
    await ws.broadcast({"type": "playlist_update", "playlist": state.playlist})
    return {"playlist": state.playlist}


@app.delete("/api/playlist/{track_id}")
async def delete_track(track_id: str):
    track = next((t for t in state.playlist if t["id"] == track_id), None)
    if not track:
        raise HTTPException(404, "不存在")
    idx = state.playlist.index(track)
    state.playlist.remove(track)
    if track.get("filename"):
        mf = UPLOAD_DIR / track["filename"]
        if mf.exists():
            mf.unlink()
    if track.get("cover"):
        cf = BASE_DIR / track["cover"].lstrip("/")
        if cf.exists():
            cf.unlink()
    if state.current_index > idx:
        state.current_index -= 1
    elif state.current_index == idx:
        # 删除的是当前播放的曲目
        if state.playlist:
            # 播放列表还有歌，保持当前索引（指向下一首）
            state.current_index = min(state.current_index, len(state.playlist) - 1)
            if state.auto_loop:
                # 自动循环模式：不停止播放，立即开始新曲目
                state.admin_paused = False
                state.play_position = 0
                state.play_start_time = time.time()
                cur = state.get_current_track()
                if cur:
                    state.current_track_id = cur["id"]
            else:
                state.is_playing = False
                state.play_position = 0
        else:
            # 播放列表空了
            state.current_index = -1
            state.is_playing = False
            state.play_position = 0
    await ws.broadcast({"type": "playlist_update", "playlist": state.playlist})
    cur = state.get_current_track()
    await ws.broadcast({
        "type": "now_playing",
        "track": cur,
        "position": state.get_position(),
        "is_playing": state.is_playing,
    })
    return {"success": True, "tracks": state.playlist}


@app.put("/api/playlist/track/{track_id}")
async def update_track(track_id: str, body: dict):
    track = next((t for t in state.playlist if t["id"] == track_id), None)
    if not track:
        raise HTTPException(404)
    for k in ("title", "artist"):
        if k in body:
            track[k] = body[k]
    if "duration" in body and body["duration"] > 0:
        track["duration"] = body["duration"]
    await ws.broadcast({"type": "playlist_update", "playlist": state.playlist})
    return {"track": track}


# ============ Playback API ============
@app.post("/api/playback/play")
async def do_play():
    state.admin_paused = False  # 主播主动恢复播放
    if state.current_index < 0 and state.playlist:
        state.current_index = 0
        state.play_position = 0
    if state.current_index >= 0:
        state.is_playing = True
        state.play_start_time = time.time()
        cur = state.get_current_track()
        if cur:
            state.current_track_id = cur["id"]
        await ws.broadcast({
            "type": "now_playing",
            "track": cur,
            "position": state.play_position,
            "is_playing": True,
        })
    return {"is_playing": state.is_playing}


@app.post("/api/playback/pause")
async def do_pause():
    if state.is_playing:
        state.play_position = state.get_position()
        state.is_playing = False
        state.admin_paused = True  # 主播主动暂停，auto_loop 不自动恢复
        cur = state.get_current_track()
        await ws.broadcast({
            "type": "now_playing",
            "track": cur,
            "position": state.play_position,
            "is_playing": False,
        })
    return {"is_playing": False, "position": state.play_position}


@app.post("/api/playback/next")
async def do_next():
    state.admin_paused = False  # 主播主动切歌
    if not state.playlist:
        return {}
    state.current_index = (state.current_index + 1) % len(state.playlist)
    state.play_position = 0
    state.is_playing = True
    state.play_start_time = time.time()
    cur = state.get_current_track()
    if cur:
        state.current_track_id = cur["id"]
    await ws.broadcast({
        "type": "now_playing",
        "track": cur,
        "position": 0,
        "is_playing": True,
    })
    return {"track": cur}


@app.post("/api/playback/prev")
async def do_prev():
    state.admin_paused = False  # 主播主动切歌
    if not state.playlist:
        return {}
    state.current_index = (state.current_index - 1) % len(state.playlist)
    state.play_position = 0
    state.is_playing = True
    state.play_start_time = time.time()
    cur = state.get_current_track()
    if cur:
        state.current_track_id = cur["id"]
    await ws.broadcast({
        "type": "now_playing",
        "track": cur,
        "position": 0,
        "is_playing": True,
    })
    return {"track": cur}


@app.post("/api/playback/seek")
async def do_seek(body: dict):
    pos = body.get("position", 0)
    state.play_position = max(0, pos)
    if state.is_playing:
        state.play_start_time = time.time()
    await ws.broadcast({
        "type": "seek",
        "position": state.play_position,
        "is_playing": state.is_playing,
    })
    return {"position": state.play_position}


@app.post("/api/playback/play-index")
async def do_play_index(body: dict):
    state.admin_paused = False  # 主播主动选歌
    idx = body.get("index", 0)
    pos = body.get("position", 0)
    if 0 <= idx < len(state.playlist):
        state.current_index = idx
        state.play_position = max(0, pos)
        state.is_playing = True
        state.play_start_time = time.time()
        cur = state.get_current_track()
        if cur:
            state.current_track_id = cur["id"]
        await ws.broadcast({
            "type": "now_playing",
            "track": cur,
            "position": state.play_position,
            "is_playing": True,
        })
        return {"track": cur}
    return {}


@app.get("/api/status")
async def get_status():
    return {
        "is_playing": state.is_playing,
        "current_index": state.current_index,
        "current_track": state.get_current_track(),
        "position": state.get_position(),
        "listeners": ws.count,
        "user_count": ws.count,
        "auto_loop": state.auto_loop,
    }


@app.post("/api/playback/auto-loop")
async def toggle_auto_loop(body: dict = None):
    """切换自动循环播放模式"""
    if body and "enabled" in body:
        state.auto_loop = bool(body["enabled"])
    else:
        state.auto_loop = not state.auto_loop
    # 开启 auto_loop 时清除暂停标志，让播放自动恢复
    if state.auto_loop:
        state.admin_paused = False
    log.info(f"[AutoLoop] auto_loop set to {state.auto_loop}")
    return {"auto_loop": state.auto_loop}


# ============ Lyrics Search API ============
import urllib.parse
import urllib.request
import json as _json

LYRICS_API_BASE = "https://lrclib.net/api"

# 歌词源列表（前端通过 source 参数切换）
LYRICS_SOURCES = ["lrclib", "lrclib-alt", "netease"]

@app.get("/api/lyrics/search")
async def search_lyrics(title: str = "", artist: str = "", source: str = "lrclib"):
    """搜索歌词（支持多源切换：lrclib / lrclib-alt / netease）"""
    if not title and not artist:
        return {"success": False, "error": "请提供歌曲名或歌手名"}

    if source == "lrclib":
        return await _search_lrclib(title, artist)
    elif source == "lrclib-alt":
        return await _search_lrclib_alt(title, artist)
    elif source == "netease":
        return await _search_netease(title, artist)
    else:
        # 未知源，回退默认
        return await _search_lrclib(title, artist)


async def _search_lrclib(title: str, artist: str):
    """LRCLIB 精确搜索 + 模糊搜索"""
    headers = {"User-Agent": "MusicRadio/1.0"}
    try:
        # 策略1: 精确搜索
        params = urllib.parse.urlencode({"track_name": title, "artist_name": artist})
        url = f"{LYRICS_API_BASE}/get?{params}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
                if data and (data.get("syncedLyrics") or data.get("plainLyrics")):
                    lyrics = data.get("syncedLyrics") or data.get("plainLyrics") or ""
                    return {"success": True, "lyrics": lyrics, "source": "lrclib-exact",
                            "track": data.get("trackName", ""), "artist": data.get("artistName", "")}
        except urllib.error.HTTPError as e:
            if e.code != 404:
                log.warning(f"LRCLIB exact search HTTP error: {e.code}")

        # 策略2: 模糊搜索，取最佳匹配
        query = f"{title} {artist}".strip()
        params = urllib.parse.urlencode({"q": query})
        url = f"{LYRICS_API_BASE}/search?{params}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            results = _json.loads(resp.read().decode("utf-8"))
            best = _lrclib_pick_best(results, title, artist)
            if best:
                lyrics = best.get("syncedLyrics") or best.get("plainLyrics") or ""
                return {"success": True, "lyrics": lyrics, "source": "lrclib-search",
                        "track": best.get("trackName", ""), "artist": best.get("artistName", "")}
        return {"success": False, "error": "未找到歌词"}
    except urllib.error.HTTPError as e:
        log.warning(f"LRCLIB API HTTP error: {e.code}")
        return {"success": False, "error": f"API返回错误 {e.code}"}
    except Exception as e:
        log.warning(f"LRCLIB API error: {e}")
        return {"success": False, "error": str(e)}


async def _search_lrclib_alt(title: str, artist: str):
    """LRCLIB 备选：模糊搜索取第2~N条结果（跳过最佳匹配）"""
    headers = {"User-Agent": "MusicRadio/1.0"}
    try:
        query = f"{title} {artist}".strip()
        params = urllib.parse.urlencode({"q": query})
        url = f"{LYRICS_API_BASE}/search?{params}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            results = _json.loads(resp.read().decode("utf-8"))
            if not results or not isinstance(results, list):
                return {"success": False, "error": "未找到歌词"}
            # 按匹配度排序
            scored = []
            for r in results:
                if not (r.get("syncedLyrics") or r.get("plainLyrics")):
                    continue
                score = 0
                r_title = (r.get("trackName") or "").lower()
                r_artist = (r.get("artistName") or "").lower()
                if title.lower() in r_title or r_title in title.lower():
                    score += 2
                if artist.lower() in r_artist or r_artist in artist.lower():
                    score += 2
                if r.get("syncedLyrics"):
                    score += 1
                scored.append({**r, "score": score})
            scored.sort(key=lambda x: x["score"], reverse=True)
            # 取第2个结果（跳过最佳匹配，给用户不同版本）
            if len(scored) >= 2:
                alt = scored[1]
                lyrics = alt.get("syncedLyrics") or alt.get("plainLyrics") or ""
                return {"success": True, "lyrics": lyrics, "source": "lrclib-alt",
                        "track": alt.get("trackName", ""), "artist": alt.get("artistName", "")}
            elif len(scored) >= 1:
                # 只有一个结果，返回它
                alt = scored[0]
                lyrics = alt.get("syncedLyrics") or alt.get("plainLyrics") or ""
                return {"success": True, "lyrics": lyrics, "source": "lrclib-alt",
                        "track": alt.get("trackName", ""), "artist": alt.get("artistName", "")}
            return {"success": False, "error": "未找到歌词"}
    except urllib.error.HTTPError as e:
        log.warning(f"LRCLIB-alt API HTTP error: {e.code}")
        return {"success": False, "error": f"API返回错误 {e.code}"}
    except Exception as e:
        log.warning(f"LRCLIB-alt API error: {e}")
        return {"success": False, "error": str(e)}


async def _search_netease(title: str, artist: str):
    """网易云歌词搜索（通过公开搜索接口代理）"""
    try:
        # 搜索歌曲
        query = f"{title} {artist}".strip()
        params = urllib.parse.urlencode({"s": query, "type": "1", "offset": "0", "limit": "5"})
        url = f"https://music.163.com/api/search/get/web?{params}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://music.163.com/",
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = _json.loads(resp.read().decode("utf-8"))

        if data.get("code") != 200 or not data.get("result", {}).get("songs"):
            return {"success": False, "error": "网易云未找到歌词"}

        songs = data["result"]["songs"]
        # 取第一个匹配的歌曲
        song = songs[0]
        song_id = song.get("id")
        if not song_id:
            return {"success": False, "error": "网易云未找到歌词"}

        # 获取歌词
        lrc_url = f"https://music.163.com/api/song/lyric?id={song_id}&lv=1&tv=-1"
        req = urllib.request.Request(lrc_url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            lrc_data = _json.loads(resp.read().decode("utf-8"))

        lrc_text = lrc_data.get("lrc", {}).get("lyric", "")
        if lrc_text and lrc_text.strip():
            return {"success": True, "lyrics": lrc_text, "source": "netease",
                    "track": song.get("name", ""), "artist": (song.get("artists") or [{}])[0].get("name", "")}

        return {"success": False, "error": "网易云未找到歌词"}
    except urllib.error.HTTPError as e:
        log.warning(f"Netease API HTTP error: {e.code}")
        return {"success": False, "error": f"API返回错误 {e.code}"}
    except Exception as e:
        log.warning(f"Netease API error: {e}")
        return {"success": False, "error": str(e)}


def _lrclib_pick_best(results, title: str, artist: str):
    """从 LRCLIB 搜索结果中选最佳匹配"""
    if not results or not isinstance(results, list):
        return None
    best = None
    for r in results:
        if not (r.get("syncedLyrics") or r.get("plainLyrics")):
            continue
        score = 0
        r_title = (r.get("trackName") or "").lower()
        r_artist = (r.get("artistName") or "").lower()
        if title.lower() in r_title or r_title in title.lower():
            score += 2
        if artist.lower() in r_artist or r_artist in artist.lower():
            score += 2
        if r.get("syncedLyrics"):
            score += 1
        if best is None or score > best["score"]:
            best = {**r, "score": score}
    return best


@app.post("/api/cleanup")
async def manual_cleanup():
    """手动触发清理，只删除上传缓存，保留本地音乐。如果正在播放则拒绝执行。"""
    if state.is_playing:
        return {"success": False, "reason": "正在播放，跳过清理"}
    removed_music = 0
    removed_covers = 0
    removed_size = 0

    # 收集非上传曲目的封面文件名（保留）
    preserved_covers = set()
    for t in state.playlist:
        if t.get("source_type") != "upload" and t.get("cover"):
            cover_name = t["cover"].split("/")[-1]
            preserved_covers.add(cover_name)

    # 删除上传的音乐文件
    for f in UPLOAD_DIR.iterdir():
        if f.is_file():
            removed_size += f.stat().st_size
            f.unlink()
            removed_music += 1

    # 删除上传的封面文件，保留本地/URL曲目的封面
    for f in COVER_DIR.iterdir():
        if f.is_file() and f.name not in preserved_covers:
            removed_size += f.stat().st_size
            f.unlink()
            removed_covers += 1

    # 只移除上传曲目，保留本地音乐和URL曲目
    kept_tracks = [t for t in state.playlist if t.get("source_type") != "upload"]
    removed_track_count = len(state.playlist) - len(kept_tracks)
    state.playlist = kept_tracks

    if kept_tracks:
        if state.current_index >= len(kept_tracks):
            state.current_index = 0
        state.admin_paused = False
    else:
        state.current_index = -1
        state.is_playing = False
        state.play_position = 0
        state.play_start_time = 0
        state.current_track_id = ""
        state.admin_paused = False

    await ws.broadcast({"type": "playlist_update", "playlist": state.playlist})
    if not kept_tracks:
        await ws.broadcast({"type": "now_playing", "track": None, "position": 0, "is_playing": False})
    await ws.broadcast({
        "type": "chat",
        "id": str(uuid.uuid4())[:8],
        "username": "系统",
        "message": f"清理完成：删除 {removed_music} 个上传缓存、{removed_covers} 个封面、{removed_track_count} 首上传曲目，释放 {removed_size / 1024 / 1024:.1f} MB" + (f"，保留 {len(kept_tracks)} 首本地曲目" if kept_tracks else ""),
        "role": "admin",
        "timestamp": datetime.now().strftime("%H:%M"),
    })
    log.info(f"Manual cleanup: removed {removed_music} uploads, {removed_covers} covers, {removed_track_count} upload tracks, freed {removed_size / 1024 / 1024:.1f} MB")
    return {"success": True, "removed_music": removed_music, "removed_covers": removed_covers, "removed_tracks": removed_track_count, "kept_tracks": len(kept_tracks), "freed_mb": round(removed_size / 1024 / 1024, 1)}


# ============ Local Music Browse API (read-only) ============
def _safe_local_path(rel_path: str) -> Path:
    """安全解析本地音乐路径，防止路径遍历攻击"""
    if not LOCAL_MUSIC_DIR.exists():
        raise HTTPException(503, "本地音乐目录未配置")
    target = (LOCAL_MUSIC_DIR / rel_path).resolve() if rel_path else LOCAL_MUSIC_DIR.resolve()
    base = LOCAL_MUSIC_DIR.resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(403, "无权访问此路径")
    return target


@app.get("/api/local-music/browse")
async def browse_local_music(path: str = ""):
    """浏览本地音乐文件目录（只读），返回子目录和音频文件列表"""
    target = _safe_local_path(path)
    if not target.exists() or not target.is_dir():
        raise HTTPException(404, "目录不存在")
    
    dirs = []
    files = []
    try:
        for item in sorted(target.iterdir()):
            try:
                if item.is_dir():
                    rel = str(item.relative_to(LOCAL_MUSIC_DIR))
                    # 计算目录下音频文件数量
                    audio_count = sum(1 for f in item.iterdir() if f.is_file() and f.suffix.lower() in AUDIO_EXTS)
                    dirs.append({"name": item.name, "path": rel, "count": audio_count})
                elif item.is_file() and item.suffix.lower() in AUDIO_EXTS:
                    rel = str(item.relative_to(LOCAL_MUSIC_DIR))
                    size = item.stat().st_size
                    files.append({"name": item.name, "path": rel, "size": size})
            except PermissionError:
                continue
    except PermissionError:
        raise HTTPException(403, "无权访问此目录")
    
    return {"dirs": dirs, "files": files, "current_path": path, "base_name": LOCAL_MUSIC_DIR.name}


@app.get("/api/local-music/stream/{file_path:path}")
async def stream_local_music(file_path: str, request: Request):
    """流式传输本地音乐文件（支持 Range 请求）"""
    full_path = _safe_local_path(file_path)
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(404, "文件不存在")
    
    file_size = full_path.stat().st_size
    mime_type, _ = mimetypes.guess_type(str(full_path))
    if not mime_type:
        mime_type = "audio/mpeg"
    
    range_header = request.headers.get("range")
    
    if not range_header:
        return FileResponse(
            full_path,
            media_type=mime_type,
            headers={"Accept-Ranges": "bytes", "Content-Length": str(file_size),
                     "Cache-Control": "public, max-age=3600"}
        )
    
    try:
        range_type, range_value = range_header.split("=")
        if range_type.strip() != "bytes":
            raise ValueError()
        start_str, end_str = range_value.split("-")
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else file_size - 1
        if start < 0 or start >= file_size or end >= file_size or start > end:
            raise ValueError()
        chunk_size = end - start + 1
        
        async def file_stream():
            with open(full_path, "rb") as f:
                f.seek(start)
                remaining = chunk_size
                while remaining > 0:
                    chunk = f.read(min(8192, remaining))
                    if not chunk: break
                    yield chunk
                    remaining -= len(chunk)
        
        return StreamingResponse(
            file_stream(), status_code=206, media_type=mime_type,
            headers={"Content-Range": f"bytes {start}-{end}/{file_size}",
                     "Content-Length": str(chunk_size), "Accept-Ranges": "bytes",
                     "Cache-Control": "public, max-age=3600"}
        )
    except Exception:
        return FileResponse(full_path, media_type=mime_type)


@app.post("/api/local-music/add")
async def add_local_music(body: dict):
    """将本地音乐文件添加到播放列表（不复制文件，只创建引用）"""
    rel_path = body.get("path", "").strip()
    if not rel_path:
        raise HTTPException(400, "路径不能为空")
    
    full_path = _safe_local_path(rel_path)
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(404, "文件不存在")
    
    tid = str(uuid.uuid4())[:8]
    # 提取元数据（封面保存到 COVER_DIR 供前端显示）
    meta = extract_metadata(full_path, tid)
    
    track = {
        "id": tid,
        "title": meta.get("title") or full_path.stem,
        "artist": meta.get("artist") or "本地音乐",
        "album": meta.get("album") or "",
        "filename": "",  # 本地文件不存此字段
        "url": f"/api/local-music/stream/{rel_path}",
        "cover": meta.get("cover"),
        "duration": meta.get("duration", 0),
        "lyrics": meta.get("lyrics") or None,
        "source_type": "local",
        "local_path": rel_path,
    }
    state.playlist.append(track)
    await ws.broadcast({"type": "playlist_update", "playlist": state.playlist})
    log.info(f"[LocalMusic] Added: {track['title']} ({rel_path})")
    return {"success": True, "track": track}


# ============ User Management API ============
@app.get("/api/users")
async def get_users():
    return {"users": ws.get_user_list()}


@app.post("/api/users/kick")
async def kick_user(body: dict):
    uid = body.get("uid", "")
    reason = body.get("reason", "")
    if uid in ws.clients:
        await ws.kick(uid, reason)
        await ws.broadcast({"type": "user_count", "count": ws.count})
        return {"message": f"已踢出用户"}
    raise HTTPException(404, "用户不在线")


# ============ WebSocket Endpoint ============
def get_real_ip(websocket: WebSocket) -> str:
    """从请求头中获取客户端真实IP（支持Nginx反向代理）"""
    # 优先从 X-Forwarded-For 获取（Nginx proxy_set_header）
    xff = websocket.headers.get("x-forwarded-for", "")
    if xff:
        # X-Forwarded-For: client, proxy1, proxy2 — 取第一个
        return xff.split(",")[0].strip()
    # 其次从 X-Real-IP 获取
    xri = websocket.headers.get("x-real-ip", "")
    if xri:
        return xri.strip()
    # 兜底用连接IP
    return websocket.client.host if websocket.client else ""

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    client_ip = get_real_ip(websocket)
    client = await ws.connect(websocket, client_ip)
    try:
        await websocket.send_json({
            "type": "init",
            "uid": client.uid,
            "playlist": state.playlist,
            "current_index": state.current_index,
            "is_playing": state.is_playing,
            "position": state.get_position(),
            "user_count": ws.count,
        })
        cur = state.get_current_track()
        if cur:
            await websocket.send_json({
                "type": "now_playing",
                "track": cur,
                "position": state.get_position(),
                "is_playing": state.is_playing,
            })
        await ws.broadcast({"type": "user_count", "count": ws.count})

        while True:
            data = await websocket.receive_json()

            if data.get("type") == "admin_auth":
                client.is_admin = True
                await websocket.send_json({"type": "admin_auth_ok"})
                continue

            if data["type"] == "chat":
                await ws.broadcast({
                    "type": "chat",
                    "id": str(uuid.uuid4())[:8],
                    "username": data.get("username", "匿名"),
                    "message": data["message"],
                    "role": data.get("role", "user"),
                    "timestamp": datetime.now().strftime("%H:%M"),
                })
            elif data["type"] == "report_duration":
                tid = data.get("track_id")
                dur = data.get("duration", 0)
                track = next((t for t in state.playlist if t["id"] == tid), None)
                if track and dur > 0:
                    track["duration"] = dur
                    await ws.broadcast({
                        "type": "playlist_update",
                        "playlist": state.playlist,
                    })
            elif data["type"] == "set_username":
                new_name = data.get("username", "").strip()[:20]
                if new_name:
                    ws.update_username(client.uid, new_name)
    except WebSocketDisconnect:
        pass
    finally:
        ws.disconnect_by_ws(websocket)
        await ws.broadcast({"type": "user_count", "count": ws.count})


# ============ Serve Frontend ============
@app.get("/player")
async def serve_player():
    return FileResponse(BASE_DIR / "static" / "player.html", headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"})


@app.get("/admin")
async def serve_admin():
    return FileResponse(BASE_DIR / "static" / "admin.html", headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"})


@app.get("/")
async def serve_index():
    return FileResponse(BASE_DIR / "static" / "player.html", headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"})


if __name__ == "__main__":
    import uvicorn
    print("Music Radio Station starting on http://localhost:8765")
    print("   Player: http://localhost:8765/player")
    print("   Admin:  http://localhost:8765/admin")
    uvicorn.run(app, host="0.0.0.0", port=8765)
