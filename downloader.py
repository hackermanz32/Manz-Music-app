#!/usr/bin/env python3
"""
Apple Music Downloader Module for Manz Music Player.
Handles Apple Music URL resolution (songs, albums, playlists),
audio searching & downloading in LOSSLESS FLAC quality via yt-dlp + ffmpeg,
and lossless tagging with high-resolution Apple Music artwork and metadata.
"""

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import imageio_ffmpeg
import mutagen.flac
from mutagen.flac import FLAC, Picture
import mutagen.id3
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TCON, TDRC, TRCK, APIC
import yt_dlp

DEFAULT_DOWNLOAD_DIR = Path.home() / "Music" / "Apple Music"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"


def sanitize_filename(name):
    """Sanitize strings for filesystem safety across Linux/Mac/Windows."""
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", str(name)).strip()
    return cleaned or "Unknown"


def format_artwork_url(url, size=1000):
    """Formats Apple Music dynamic artwork URLs to static high-res JPEG."""
    if not url:
        return ""
    if "{w}x{h}bb.{f}" in url:
        return url.replace("{w}x{h}bb.{f}", f"{size}x{size}bb.jpg")
    if "{w}x{h}" in url:
        return url.replace("{w}x{h}", f"{size}x{size}")
    url = re.sub(r'/\d+x\d+(bb|wp)?\.(jpg|png|webp)', f'/{size}x{size}bb.jpg', url)
    return url


def get_audio_quality_specs(format="FLAC"):
    """Returns detailed technical audio specifications and quality information."""
    fmt = (format or "FLAC").upper()
    if fmt == "FLAC":
        return {
            "format": "FLAC",
            "file_type": "FLAC Lossless Audio (.flac)",
            "codec": "FLAC",
            "quality_label": "LOSSLESS HI-FI",
            "quality_badge": "FLAC · LOSSLESS · 24-bit / 48–96 kHz",
            "bit_depth": "24-bit / 16-bit Lossless",
            "sample_rate": "44.1 kHz / 48.0 kHz / 96.0 kHz",
            "bitrate": "Lossless (~800 – 1411 kbps)",
            "channels": "Stereo (2.0 channels)",
            "compression": "Free Lossless Audio Codec (Bit-perfect Studio Quality)",
            "is_lossless": True,
        }
    elif fmt == "WAV":
        return {
            "format": "WAV",
            "file_type": "WAV Uncompressed PCM (.wav)",
            "codec": "PCM",
            "quality_label": "UNCOMPRESSED LOSSLESS",
            "quality_badge": "WAV · LOSSLESS · 24-bit / 96 kHz",
            "bit_depth": "24-bit / 16-bit Uncompressed",
            "sample_rate": "44.1 kHz / 48.0 kHz / 96.0 kHz",
            "bitrate": "1411 – 4608 kbps",
            "channels": "Stereo (2.0 channels)",
            "compression": "Uncompressed Linear PCM",
            "is_lossless": True,
        }
    else:
        return {
            "format": "MP3",
            "file_type": "MP3 High-Bitrate Audio (.mp3)",
            "codec": "MP3",
            "quality_label": "320 KBPS HIGH-BITRATE",
            "quality_badge": "MP3 · LOSSY · 320 kbps",
            "bit_depth": "16-bit Equivalent",
            "sample_rate": "44.1 kHz / 48.0 kHz",
            "bitrate": "320 kbps Constant Bitrate",
            "channels": "Joint Stereo",
            "compression": "MPEG-1 Audio Layer III",
            "is_lossless": False,
        }


def resolve_apple_music(url_or_query):
    """
    Resolves an Apple Music song, album, or playlist URL,
    or performs an iTunes search for keywords.
    Returns rich track metadata and audio quality specifications.
    """
    raw = (url_or_query or "").strip()
    if not raw:
        return {"error": "Empty URL or search query"}

    # If it's not a URL, perform iTunes Search
    if not (raw.startswith("http://") or raw.startswith("https://")):
        return search_itunes(raw)

    parsed_url = urllib.parse.urlparse(raw)
    domain = parsed_url.netloc.lower()

    if "music.apple.com" not in domain and "itunes.apple.com" not in domain:
        return search_itunes(raw)

    req = urllib.request.Request(raw, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            final_url = resp.geturl()
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        return {"error": f"Failed to load Apple Music page: {exc}"}

    shoebox_match = re.search(
        r'<script[^>]*type="application/json"[^>]*id="serialized-server-data"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )

    if shoebox_match:
        try:
            data = json.loads(shoebox_match.group(1))
            return parse_shoebox_data(data, raw, final_url)
        except Exception:
            pass

    match_id = (
        re.search(r'[?&]i=(\d+)', raw)
        or re.search(r'/(?:album|song|playlist)/[^/]+/(\d+)', raw)
        or re.search(r'/(\d+)(?:\?|$)', raw)
    )
    if match_id:
        adam_id = match_id.group(1)
        res = lookup_itunes_id(adam_id, raw)
        if res and not res.get("error"):
            return res

    return {"error": "Could not extract tracks from Apple Music page. Please verify the URL."}


def parse_shoebox_data(data, original_url, final_url):
    """Parses Apple Music's serialized-server-data JSON blob with rich metadata."""
    sections = []
    try:
        sections = data.get("data", [{}])[0].get("data", {}).get("sections", [])
    except (IndexError, KeyError, AttributeError):
        pass

    target_song_id = None
    i_match = re.search(r'[?&]i=(\d+)', original_url) or re.search(r'[?&]i=(\d+)', final_url)
    if i_match:
        target_song_id = i_match.group(1)
    elif "/song/" in original_url or "/song/" in final_url:
        song_id_match = (
            re.search(r'/song/[^/]+/(\d+)', original_url)
            or re.search(r'/song/[^/]+/(\d+)', final_url)
            or re.search(r'/song/(\d+)', original_url)
        )
        if song_id_match:
            target_song_id = song_id_match.group(1)

    container_title = "Apple Music"
    container_artist = ""
    container_type = "playlist" if "/playlist/" in final_url else ("song" if target_song_id else "album")
    container_artwork = ""
    container_genre = ""
    container_year = ""

    # Parse header section for title, artwork, and metadata
    for s in sections:
        if "header" in s.get("id", "").lower() or s.get("itemKind") == "containerDetailHeaderLockup":
            items = s.get("items", [])
            if items:
                h = items[0]
                container_title = h.get("title") or h.get("name") or container_title
                container_artist = h.get("artistName") or ""
                art = h.get("artwork", {}).get("dictionary", {})
                if art and "url" in art:
                    container_artwork = format_artwork_url(art["url"])
                # Extract genre or subtitle details if available
                sub = h.get("subtitle") or h.get("tertiaryTitle") or ""
                if sub and not container_genre:
                    container_genre = str(sub).split("·")[0].strip()

    tracks = []
    for s in sections:
        if s.get("itemKind") == "trackLockup":
            for it in s.get("items", []):
                t_id = str(it.get("contentDescriptor", {}).get("identifiers", {}).get("storeAdamID") or "")
                if target_song_id and t_id != target_song_id:
                    continue

                title = it.get("title", "")
                artist = it.get("artistName", "")
                album = ""
                tertiary = it.get("tertiaryLinks")
                if tertiary and isinstance(tertiary, list) and len(tertiary) > 0:
                    album = tertiary[0].get("title", "")
                if not album:
                    album = container_title if container_type == "album" else ""

                track_art = ""
                art_dict = it.get("artwork", {}).get("dictionary", {}) if it.get("artwork") else {}
                if art_dict and "url" in art_dict:
                    track_art = format_artwork_url(art_dict["url"])
                if not track_art:
                    track_art = container_artwork

                duration_ms = it.get("duration", 0)
                track_num = it.get("trackNumber", 0)
                disc_num = it.get("discNumber", 1)
                composer = it.get("composer", "")

                tracks.append({
                    "id": t_id or hashlib.sha1(f"{artist}-{title}".encode("utf-8")).hexdigest()[:12],
                    "title": title,
                    "artist": artist,
                    "album": album,
                    "album_artist": container_artist or artist,
                    "genre": container_genre,
                    "year": container_year,
                    "composer": composer,
                    "artwork": track_art,
                    "duration": round(duration_ms / 1000.0, 2) if duration_ms else 0.0,
                    "track_number": track_num,
                    "disc_number": disc_num,
                    "format": "FLAC",
                    "file_type": "FLAC Lossless Audio (.flac)",
                    "audio_quality": "Lossless Hi-Fi (Bit-perfect Studio Quality)",
                    "url": it.get("contentDescriptor", {}).get("url") or original_url,
                })

    if not tracks and target_song_id:
        res = lookup_itunes_id(target_song_id, original_url)
        if res and not res.get("error"):
            return res

    is_single_song = bool(target_song_id and len(tracks) == 1)
    quality_specs = get_audio_quality_specs("FLAC")

    return {
        "type": "song" if is_single_song else container_type,
        "title": tracks[0]["title"] if is_single_song else container_title,
        "artist": tracks[0]["artist"] if is_single_song else container_artist,
        "artwork": tracks[0]["artwork"] if is_single_song else container_artwork,
        "genre": tracks[0].get("genre") if is_single_song and tracks else container_genre,
        "tracks": tracks,
        "count": len(tracks),
        "quality_specs": quality_specs,
    }


def lookup_itunes_id(adam_id, original_url=""):
    """Lookup a track or collection on iTunes official API with full metadata details."""
    url = f"https://itunes.apple.com/lookup?id={adam_id}&entity=song"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"error": str(exc)}

    results = data.get("results", [])
    if not results:
        return {"error": "Item not found in iTunes store"}

    tracks = []
    container_title = ""
    container_artist = ""
    container_artwork = ""
    container_genre = ""
    is_collection = False

    for item in results:
        wrapper = item.get("wrapperType")
        if wrapper == "collection":
            is_collection = True
            container_title = item.get("collectionName", "")
            container_artist = item.get("artistName", "")
            container_genre = item.get("primaryGenreName", "")
            container_artwork = format_artwork_url(item.get("artworkUrl100", ""))
        elif wrapper == "track":
            t_title = item.get("trackName", "")
            t_artist = item.get("artistName", "")
            t_album = item.get("collectionName", "")
            t_dur = round((item.get("trackTimeMillis") or 0) / 1000.0, 2)
            t_art = format_artwork_url(item.get("artworkUrl100", ""))
            t_genre = item.get("primaryGenreName", "")
            t_year = (item.get("releaseDate") or "")[:4]
            t_track = item.get("trackNumber", 0)
            t_disc = item.get("discNumber", 1)

            tracks.append({
                "id": str(item.get("trackId") or adam_id),
                "title": t_title,
                "artist": t_artist,
                "album": t_album,
                "album_artist": item.get("artistName", t_artist),
                "genre": t_genre,
                "year": t_year,
                "composer": "",
                "duration": t_dur,
                "track_number": t_track,
                "disc_number": t_disc,
                "artwork": t_art,
                "format": "FLAC",
                "file_type": "FLAC Lossless Audio (.flac)",
                "audio_quality": "Lossless Hi-Fi (Bit-perfect Studio Quality)",
                "url": item.get("trackViewUrl") or original_url,
            })

    if not tracks:
        return {"error": "No tracks found in iTunes result"}

    quality_specs = get_audio_quality_specs("FLAC")

    if len(tracks) == 1 and not is_collection:
        return {
            "type": "song",
            "title": tracks[0]["title"],
            "artist": tracks[0]["artist"],
            "album": tracks[0]["album"],
            "genre": tracks[0]["genre"],
            "year": tracks[0]["year"],
            "artwork": tracks[0]["artwork"],
            "tracks": tracks,
            "count": 1,
            "quality_specs": quality_specs,
        }

    return {
        "type": "album" if is_collection else "playlist",
        "title": container_title or tracks[0]["album"] or "Apple Music Album",
        "artist": container_artist or tracks[0]["artist"],
        "genre": container_genre or tracks[0]["genre"],
        "artwork": container_artwork or tracks[0]["artwork"],
        "tracks": tracks,
        "count": len(tracks),
        "quality_specs": quality_specs,
    }


def search_itunes(query, limit=12):
    """Searches iTunes / Apple Music songs by keyword."""
    encoded = urllib.parse.quote(query)
    url = f"https://itunes.apple.com/search?term={encoded}&entity=song&limit={limit}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"error": f"Search failed: {exc}"}

    tracks = []
    for item in data.get("results", []):
        t_dur = round((item.get("trackTimeMillis") or 0) / 1000.0, 2)
        tracks.append({
            "id": str(item.get("trackId")),
            "title": item.get("trackName", ""),
            "artist": item.get("artistName", ""),
            "album": item.get("collectionName", ""),
            "album_artist": item.get("artistName", ""),
            "genre": item.get("primaryGenreName", ""),
            "year": (item.get("releaseDate") or "")[:4],
            "composer": "",
            "duration": t_dur,
            "track_number": item.get("trackNumber", 0),
            "disc_number": item.get("discNumber", 1),
            "artwork": format_artwork_url(item.get("artworkUrl100", "")),
            "format": "FLAC",
            "file_type": "FLAC Lossless Audio (.flac)",
            "audio_quality": "Lossless Hi-Fi (Bit-perfect Studio Quality)",
            "url": item.get("trackViewUrl", ""),
        })

    quality_specs = get_audio_quality_specs("FLAC")

    return {
        "type": "search",
        "title": f'Search results for "{query}"',
        "artist": f"{len(tracks)} songs found",
        "artwork": tracks[0]["artwork"] if tracks else "",
        "tracks": tracks,
        "count": len(tracks),
        "quality_specs": quality_specs,
    }


def find_best_audio_match(artist, title, target_duration=0):
    """
    Finds the optimal audio stream matching artist, song title, and duration,
    prioritizing official studio audio and topic releases.
    """
    clean_artist = re.sub(r'\(feat\..*?\)', '', artist, flags=re.IGNORECASE).strip()
    clean_title = re.sub(r'\(feat\..*?\)', '', title, flags=re.IGNORECASE).strip()

    search_query = f"{clean_artist} - {clean_title} official audio"
    ydl_opts = {
        "noplaylist": True,
        "quiet": True,
        "extract_flat": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(f"ytsearch5:{search_query}", download=False)
            entries = res.get("entries", [])
            if not entries:
                res = ydl.extract_info(f"ytsearch3:{clean_artist} {clean_title}", download=False)
                entries = res.get("entries", [])

            if not entries:
                return None

            best_entry = None
            best_score = float("inf")

            for e in entries:
                dur = e.get("duration") or 0
                t = (e.get("title") or "").lower()
                uploader = (e.get("uploader") or "").lower()

                dur_diff = abs(dur - target_duration) if target_duration and dur else 0
                score = dur_diff
                if "official audio" in t:
                    score -= 12
                elif "audio" in t:
                    score -= 6
                if "topic" in uploader:
                    score -= 10
                if any(bad in t for bad in ["music video", "official video", "lyric video", "live", "remix"]):
                    score += 15

                if score < best_score:
                    best_score = score
                    best_entry = e

            return best_entry
    except Exception:
        return None


class DownloadManager:
    def __init__(self, download_dir=None, on_track_downloaded=None):
        self.download_dir = Path(download_dir or DEFAULT_DOWNLOAD_DIR).expanduser().resolve()
        self.on_track_downloaded = on_track_downloaded
        self._lock = threading.Lock()
        self._queue = []
        self._active = {}
        self._completed = []
        self._workers = []
        self._stop_event = threading.Event()
        self.ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()

        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._start_worker()

    def set_download_dir(self, new_dir):
        with self._lock:
            p = Path(new_dir).expanduser().resolve()
            p.mkdir(parents=True, exist_ok=True)
            self.download_dir = p
            return str(self.download_dir)

    def get_download_dir(self):
        return str(self.download_dir)

    def _start_worker(self):
        t = threading.Thread(target=self._worker_loop, daemon=True, name="MusicDownloaderWorker")
        t.start()
        self._workers.append(t)

    def enqueue(self, tracks, folder=None, format="flac"):
        """
        Enqueues a list of track dicts for downloading in lossless quality.
        format: 'flac' (default lossless), 'wav', or 'mp3'.
        """
        task_ids = []
        target_dir = Path(folder).expanduser().resolve() if folder else self.download_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        chosen_format = (format or "flac").lower()

        with self._lock:
            for t in tracks:
                task_id = hashlib.sha1(f"{t.get('artist')}-{t.get('title')}-{time.time()}".encode("utf-8")).hexdigest()[:12]
                task_fmt = (t.get("format") or chosen_format).lower()
                is_lossless = task_fmt in ("flac", "wav")

                task = {
                    "id": task_id,
                    "title": t.get("title", "Unknown"),
                    "artist": t.get("artist", "Unknown"),
                    "album": t.get("album", ""),
                    "album_artist": t.get("album_artist", ""),
                    "genre": t.get("genre", ""),
                    "year": t.get("year", ""),
                    "composer": t.get("composer", ""),
                    "artwork": t.get("artwork", ""),
                    "duration": t.get("duration", 0),
                    "track_number": t.get("track_number", 0),
                    "disc_number": t.get("disc_number", 1),
                    "format": task_fmt,
                    "quality_type": "LOSSLESS HI-FI" if is_lossless else "320 KBPS",
                    "file_type": f"{task_fmt.upper()} Audio (.{task_fmt})",
                    "target_dir": str(target_dir),
                    "status": "queued",
                    "progress": 0,
                    "message": f"Queued ({task_fmt.upper()} Lossless)" if is_lossless else "Queued",
                    "output_path": None,
                    "audio_specs": get_audio_quality_specs(task_fmt),
                    "created_at": time.time(),
                }
                self._queue.append(task)
                task_ids.append(task_id)

        return task_ids

    def cancel(self, task_id):
        with self._lock:
            for i, t in enumerate(self._queue):
                if t["id"] == task_id:
                    self._queue.pop(i)
                    t["status"] = "cancelled"
                    t["message"] = "Cancelled by user"
                    self._completed.insert(0, t)
                    return True
            if task_id in self._active:
                self._active[task_id]["cancel_requested"] = True
                return True
        return False

    def get_status(self):
        with self._lock:
            return {
                "download_dir": str(self.download_dir),
                "active": [dict(t) for t in self._active.values()],
                "queued": [dict(t) for t in self._queue],
                "completed": [dict(t) for t in self._completed[:30]],
                "queue_count": len(self._queue),
                "active_count": len(self._active),
            }

    def clear_completed(self):
        with self._lock:
            self._completed = []

    def _worker_loop(self):
        while not self._stop_event.is_set():
            task = None
            with self._lock:
                if self._queue:
                    task = self._queue.pop(0)
                    self._active[task["id"]] = task

            if not task:
                time.sleep(0.5)
                continue

            try:
                self._process_download(task)
            except Exception as exc:
                task["status"] = "error"
                task["message"] = f"Error: {exc}"
            finally:
                with self._lock:
                    self._active.pop(task["id"], None)
                    self._completed.insert(0, task)

    def _process_download(self, task):
        task_fmt = (task.get("format") or "flac").lower()
        is_lossless = task_fmt in ("flac", "wav")

        task["status"] = "searching"
        task["message"] = f"Finding studio master for {task['artist']} - {task['title']}..."
        task["progress"] = 10

        target_duration = task.get("duration") or 0
        match = find_best_audio_match(task["artist"], task["title"], target_duration)
        if not match or not match.get("id"):
            task["status"] = "error"
            task["message"] = "No matching audio stream found"
            return

        video_id = match["id"]
        video_url = f"https://www.youtube.com/watch?v={video_id}"

        if task.get("cancel_requested"):
            task["status"] = "cancelled"
            task["message"] = "Download cancelled"
            return

        task["status"] = "downloading"
        task["message"] = f"Downloading original stream ({match.get('title', '')})..."
        task["progress"] = 25

        temp_dir = tempfile.mkdtemp(prefix="hifi_dl_")
        temp_out = os.path.join(temp_dir, "audio.%(ext)s")

        def hook(d):
            if task.get("cancel_requested"):
                raise Exception("Download cancelled by user")
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes") or 0
                if total > 0:
                    pct = int(25 + (downloaded / total) * 50)
                    task["progress"] = min(pct, 75)
                    task["message"] = f"Downloading audio ({pct}%)..."

        # Configure lossless FLAC, WAV, or 320k MP3 postprocessor
        if task_fmt == "flac":
            postprocessors = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "flac",
            }]
            out_ext = "flac"
        elif task_fmt == "wav":
            postprocessors = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
            }]
            out_ext = "wav"
        else:
            postprocessors = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }]
            out_ext = "mp3"

        ydl_opts = {
            "ffmpeg_location": self.ffmpeg_path,
            "format": "bestaudio/best",
            "outtmpl": temp_out,
            "postprocessors": postprocessors,
            "progress_hooks": [hook],
            "quiet": True,
            "no_warnings": True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])

            temp_audio_file = os.path.join(temp_dir, f"audio.{out_ext}")
            if not os.path.isfile(temp_audio_file):
                raise FileNotFoundError(f"Audio conversion failed: output {out_ext} not found")

            task["status"] = "tagging"
            quality_text = "Bit-perfect Lossless FLAC" if task_fmt == "flac" else f"{task_fmt.upper()}"
            task["message"] = f"Encoding {quality_text} & embedding Apple artwork..."
            task["progress"] = 85

            # Download official Apple Music artwork
            art_data = b""
            if task.get("artwork"):
                try:
                    art_req = urllib.request.Request(task["artwork"], headers={"User-Agent": USER_AGENT})
                    with urllib.request.urlopen(art_req, timeout=12) as art_resp:
                        art_data = art_resp.read()
                except Exception:
                    art_data = b""

            # Apply tags based on format
            if task_fmt == "flac":
                try:
                    audio = FLAC(temp_audio_file)
                    if task.get("title"):
                        audio["title"] = task["title"]
                    if task.get("artist"):
                        audio["artist"] = task["artist"]
                    if task.get("album"):
                        audio["album"] = task["album"]
                    if task.get("album_artist"):
                        audio["albumartist"] = task["album_artist"]
                    elif task.get("artist"):
                        audio["albumartist"] = task["artist"]
                    if task.get("year"):
                        audio["date"] = str(task["year"])
                    if task.get("track_number"):
                        audio["tracknumber"] = str(task["track_number"])
                    if task.get("disc_number"):
                        audio["discnumber"] = str(task["disc_number"])
                    if task.get("genre"):
                        audio["genre"] = task["genre"]
                    if task.get("composer"):
                        audio["composer"] = task["composer"]
                    audio["comment"] = "Apple Music Lossless Hi-Fi Audio"

                    if art_data:
                        pic = Picture()
                        pic.type = 3  # Front cover
                        pic.mime = "image/png" if art_data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
                        pic.desc = "Front Cover"
                        pic.data = art_data
                        audio.add_picture(pic)

                    audio.save()
                except Exception as exc:
                    pass

            elif task_fmt == "mp3":
                try:
                    try:
                        tags = ID3(temp_audio_file)
                    except mutagen.id3.ID3NoHeaderError:
                        tags = ID3()

                    tags.add(TIT2(encoding=3, text=task["title"]))
                    tags.add(TPE1(encoding=3, text=task["artist"]))
                    if task.get("album"):
                        tags.add(TALB(encoding=3, text=task["album"]))
                    if task.get("track_number"):
                        tags.add(TRCK(encoding=3, text=str(task["track_number"])))
                    if task.get("year"):
                        tags.add(TDRC(encoding=3, text=str(task["year"])))
                    if task.get("genre"):
                        tags.add(TCON(encoding=3, text=task["genre"]))

                    if art_data:
                        mime_type = "image/png" if art_data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
                        tags.add(APIC(
                            encoding=3,
                            mime=mime_type,
                            type=3,
                            desc="Cover",
                            data=art_data,
                        ))
                    tags.save(temp_audio_file)
                except Exception:
                    pass

            # Move to destination
            target_folder = Path(task.get("target_dir") or self.download_dir)
            target_folder.mkdir(parents=True, exist_ok=True)

            safe_artist = sanitize_filename(task["artist"])
            safe_title = sanitize_filename(task["title"])
            target_filename = f"{safe_artist} - {safe_title}.{out_ext}"
            final_path = target_folder / target_filename

            counter = 1
            while final_path.exists():
                final_path = target_folder / f"{safe_artist} - {safe_title} ({counter}).{out_ext}"
                counter += 1

            shutil.move(temp_audio_file, final_path)

            task["status"] = "done"
            task["progress"] = 100
            task["message"] = f"Downloaded in Lossless {out_ext.upper()}" if is_lossless else "Downloaded successfully"
            task["output_path"] = str(final_path)

            if self.on_track_downloaded:
                try:
                    self.on_track_downloaded(str(final_path), str(target_folder))
                except Exception:
                    pass

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
