#!/usr/bin/env python3
import hashlib
import io
import json
import os
import re
import socket
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metadata as md
import downloader

HOST = "127.0.0.1"
DEFAULT_PORT = 8642
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


def _default_data_dir():
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / "ManzMusicPlayer"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "hifi-player"


DATA_DIR = _default_data_dir()
LIBRARY_FILE = DATA_DIR / "library.json"
CONFIG_FILE = DATA_DIR / "config.json"
THUMB_DIR = DATA_DIR / "thumb-cache"

MIME_TYPES = {
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".m4b": "audio/mp4",
    ".mp4": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".aiff": "audio/aiff",
    ".aif": "audio/aiff",
    ".wv": "audio/x-wavpack",
    ".tta": "audio/x-tta",
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}

CHUNK_SIZE = 256 * 1024
COVER_CACHE_BUDGET = 64 * 1024 * 1024
_library_lock = threading.Lock()
_cover_cache = {}
_cover_cache_order = []
_cover_cache_bytes = 0
_static_cache = {}


class Library:
    def __init__(self):
        self.folders = []
        self.tracks = []

    def load(self):
        if LIBRARY_FILE.exists():
            try:
                data = json.loads(LIBRARY_FILE.read_text(encoding="utf-8"))
                self.folders = list(data.get("folders", []))
                self.tracks = list(data.get("tracks", []))
            except Exception:
                self.folders, self.tracks = [], []

    def save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated": datetime.now(timezone.utc).isoformat(),
            "folders": self.folders,
            "tracks": self.tracks,
        }
        tmp = LIBRARY_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(LIBRARY_FILE)

    def snapshot(self):
        with _library_lock:
            tracks_before = len(self.tracks)
            folders_before = len(self.folders)
            self.tracks = [t for t in self.tracks if os.path.isfile(t.get("path", ""))]
            self.folders = [f for f in self.folders if os.path.isdir(f)]
            if len(self.tracks) != tracks_before or len(self.folders) != folders_before:
                self.save()
            return {"folders": list(self.folders), "tracks": list(self.tracks)}


LIBRARY = Library()
LIBRARY.load()


def load_config():
    default_cfg = {
        "download_dir": str(Path.home() / "Music" / "Apple Music")
    }
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            default_cfg.update(data)
        except Exception:
            pass
    return default_cfg


def save_config(cfg):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def on_track_downloaded(file_path, folder_path):
    try:
        parsed = md.parse_track(file_path)
    except Exception:
        return
    folder = os.path.realpath(folder_path)
    with _library_lock:
        existing_idx = next((i for i, t in enumerate(LIBRARY.tracks) if t["path"] == file_path), None)
        if existing_idx is not None:
            LIBRARY.tracks[existing_idx] = parsed
        else:
            LIBRARY.tracks.insert(0, parsed)
        if folder not in LIBRARY.folders:
            LIBRARY.folders.append(folder)
        LIBRARY.save()


CONFIG = load_config()
DOWNLOADER = downloader.DownloadManager(
    download_dir=CONFIG.get("download_dir"),
    on_track_downloaded=on_track_downloaded,
)


def _folder_prefix(folder):
    return folder if folder.endswith(os.sep) else folder + os.sep


def scan_folder(folder):
    folder = os.path.realpath(os.path.expanduser(folder))
    if not os.path.isdir(folder):
        prefix = _folder_prefix(folder)
        with _library_lock:
            was_registered = folder in LIBRARY.folders
            before = len(LIBRARY.tracks)
            LIBRARY.tracks = [t for t in LIBRARY.tracks if not (t["path"] == folder or t["path"].startswith(prefix))]
            LIBRARY.folders = [f for f in LIBRARY.folders if f != folder]
            removed = before - len(LIBRARY.tracks)
            if removed or was_registered:
                LIBRARY.save()
        return {
            "error": "Folder not found: " + folder + (" (removed from library)" if was_registered else ""),
            "removed": removed,
            "total": len(LIBRARY.tracks),
        }

    files = []
    for root, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(names):
            if name.startswith("."):
                continue
            if os.path.splitext(name)[1].lower() in md.AUDIO_EXTENSIONS:
                files.append(os.path.join(root, name))

    parsed, errors = [], 0
    for path in files:
        try:
            parsed.append(md.parse_track(path))
        except Exception:
            errors += 1

    prefix = _folder_prefix(folder)
    with _library_lock:
        keep = [t for t in LIBRARY.tracks if not (t["path"] == folder or t["path"].startswith(prefix))]
        LIBRARY.tracks = keep + parsed
        if folder not in LIBRARY.folders:
            LIBRARY.folders.append(folder)
        else:
            LIBRARY.folders = [folder if f == folder else f for f in LIBRARY.folders]
        LIBRARY.save()
        total = len(LIBRARY.tracks)

    return {"folder": folder, "scanned": len(parsed), "errors": errors, "total": total}


def remove_folder(folder):
    folder = os.path.realpath(os.path.expanduser(folder))
    prefix = _folder_prefix(folder)
    with _library_lock:
        LIBRARY.tracks = [t for t in LIBRARY.tracks if not (t["path"] == folder or t["path"].startswith(prefix))]
        LIBRARY.folders = [f for f in LIBRARY.folders if f != folder]
        LIBRARY.save()
        total = len(LIBRARY.tracks)
    return {"folder": folder, "total": total}


def _pick_folder_windows():
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$d.Description = 'Choose music folder'; "
        "$d.ShowNewFolderButton = $true; "
        "if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { "
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "Write-Output $d.SelectedPath }"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-WindowStyle", "Hidden", "-Command", script],
            capture_output=True,
            timeout=180,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return False, None
    if result.returncode != 0:
        return False, None
    if not result.stdout:
        return True, None
    for encoding in ("utf-8-sig", "utf-8", "mbcs"):
        try:
            path = result.stdout.decode(encoding).strip()
        except (UnicodeDecodeError, LookupError):
            continue
        if path:
            return True, os.path.realpath(path)
    return True, None


def _pick_folder_tk():
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(title="Choose music folder", mustexist=True)
        root.destroy()
        return path or None
    except Exception:
        return None


def pick_folder():
    if os.name == "nt":
        ok, path = _pick_folder_windows()
        if not ok:
            path = _pick_folder_tk()
        return {"folder": os.path.realpath(path) if path else None}
    try:
        result = subprocess.run(
            ["zenity", "--file-selection", "--directory", "--title=Choose music folder"],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode == 0:
            path = result.stdout.strip()
            return {"folder": os.path.realpath(path) if path else None}
    except Exception:
        pass
    return {"folder": None}


def _shrink_cover(mime, data, size):
    try:
        from PIL import Image
    except ImportError:
        return mime, data
    try:
        image = Image.open(io.BytesIO(data))
        if image.width <= size and image.height <= size and mime == "image/jpeg":
            return mime, data
        image = image.convert("RGB")
        image.thumbnail((size, size), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=82)
        return "image/jpeg", buffer.getvalue()
    except Exception:
        return mime, data


def _thumb_key(path, size):
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        mtime = 0
    return hashlib.sha1(f"{path}|{mtime}|{size}".encode("utf-8")).hexdigest()


def _remember_cover(key, pair):
    global _cover_cache_bytes
    mime, data = pair
    if key in _cover_cache or len(data) > COVER_CACHE_BUDGET // 4:
        return
    _cover_cache[key] = pair
    _cover_cache_order.append(key)
    _cover_cache_bytes += len(data)
    while _cover_cache_bytes > COVER_CACHE_BUDGET and _cover_cache_order:
        old = _cover_cache_order.pop(0)
        old_pair = _cover_cache.pop(old, None)
        if old_pair:
            _cover_cache_bytes -= len(old_pair[1])


def get_cover(path, size=0):
    key = (path, size)
    cached = _cover_cache.get(key)
    if cached is not None:
        return cached
    thumb_file = None
    if size >= 32:
        thumb_file = THUMB_DIR / (_thumb_key(path, size) + ".img")
        if thumb_file.is_file():
            try:
                data = thumb_file.read_bytes()
                mime = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
                _remember_cover(key, (mime, data))
                return mime, data
            except OSError:
                pass
    result = md.extract_cover(path)
    if result is None:
        return None
    mime, data = result
    if size >= 32:
        mime, data = _shrink_cover(mime, data, size)
        if thumb_file is not None:
            try:
                THUMB_DIR.mkdir(parents=True, exist_ok=True)
                tmp = thumb_file.with_suffix(".tmp")
                tmp.write_bytes(data)
                tmp.replace(thumb_file)
            except OSError:
                pass
    _remember_cover(key, (mime, data))
    return mime, data


class Handler(BaseHTTPRequestHandler):
    server_version = "ManzMusicPlayer/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if fmt.startswith('"GET /api/cover') or fmt.startswith('"GET /api/library'):
            return
        if "/stream" not in self.path and "/static/" not in self.path:
            sys.stderr.write("  %s\n" % (fmt % args))

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status, message):
        self.send_json({"error": message}, status)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if route == "/api/library":
                return self.send_json(LIBRARY.snapshot())
            if route == "/api/pick-folder":
                return self.send_json(pick_folder())
            if route == "/api/download/status":
                return self.send_json(DOWNLOADER.get_status())
            if route == "/api/download/dir":
                return self.send_json({"dir": DOWNLOADER.get_download_dir()})
            if route == "/api/track-details":
                path = query.get("path", [""])[0]
                path = os.path.realpath(os.path.expanduser(path)) if path else ""
                if not path or not os.path.isfile(path):
                    return self.send_error_json(404, "Track file not found")
                if os.path.splitext(path)[1].lower() not in md.AUDIO_EXTENSIONS:
                    return self.send_error_json(400, "Not an audio file")
                return self.send_json(md.parse_track(path))
            if route == "/api/cover":
                path = query.get("path", [""])[0]
                size = int(query.get("size", ["0"])[0] or 0)
                size = max(0, min(size, 512))
                return self.serve_cover(path, size)
            if route == "/stream":
                path = query.get("path", [""])[0]
                return self.serve_stream(path)
            return self.serve_static(route)
        except BrokenPipeError:
            return
        except ConnectionResetError:
            return
        except Exception as exc:
            return self.send_error_json(500, str(exc))

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            return self.send_error_json(400, "Invalid JSON")

        try:
            if route == "/api/scan":
                folder = str(payload.get("folder", "")).strip()
                if not folder:
                    return self.send_error_json(400, "Missing folder")
                return self.send_json(scan_folder(folder))
            if route == "/api/remove-folder":
                folder = str(payload.get("folder", "")).strip()
                if not folder:
                    return self.send_error_json(400, "Missing folder")
                return self.send_json(remove_folder(folder))
            if route == "/api/download/inspect":
                url = str(payload.get("url", "")).strip()
                if not url:
                    return self.send_error_json(400, "Missing URL or search query")
                res = downloader.resolve_apple_music(url)
                if res.get("error"):
                    return self.send_error_json(400, res["error"])
                return self.send_json(res)
            if route == "/api/download/start":
                tracks = payload.get("tracks", [])
                if not tracks:
                    return self.send_error_json(400, "No tracks specified to download")
                folder = payload.get("folder")
                format = payload.get("format", "flac")
                task_ids = DOWNLOADER.enqueue(tracks, folder=folder, format=format)
                return self.send_json({"ok": True, "task_ids": task_ids})
            if route == "/api/download/cancel":
                task_id = str(payload.get("id", "")).strip()
                ok = DOWNLOADER.cancel(task_id)
                return self.send_json({"ok": ok})
            if route == "/api/download/clear-completed":
                DOWNLOADER.clear_completed()
                return self.send_json({"ok": True})
            if route == "/api/download/dir":
                new_dir = str(payload.get("dir", "")).strip()
                if not new_dir:
                    return self.send_error_json(400, "Missing directory path")
                updated = DOWNLOADER.set_download_dir(new_dir)
                CONFIG["download_dir"] = updated
                save_config(CONFIG)
                if os.path.isdir(updated):
                    with _library_lock:
                        if updated not in LIBRARY.folders:
                            LIBRARY.folders.append(updated)
                            LIBRARY.save()
                return self.send_json({"dir": updated})
            return self.send_error_json(404, "Unknown endpoint")
        except BrokenPipeError:
            return
        except Exception as exc:
            return self.send_error_json(500, str(exc))

    def do_HEAD(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/stream":
            query = urllib.parse.parse_qs(parsed.query)
            return self.serve_stream(query.get("path", [""])[0], head_only=True)
        self.send_error(404)

    def serve_cover(self, path, size=0):
        path = os.path.realpath(os.path.expanduser(path)) if path else ""
        if not path or not os.path.isfile(path):
            return self.send_error(404)
        cover = get_cover(path, size)
        if cover is None:
            return self.send_error(404)
        mime, data = cover
        etag = '"%s"' % _thumb_key(path, size)
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "public, max-age=604800")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=604800")
        self.send_header("ETag", etag)
        self.end_headers()
        self.wfile.write(data)

    def serve_stream(self, raw_path, head_only=False):
        path = os.path.realpath(os.path.expanduser(raw_path)) if raw_path else ""
        if not path or not os.path.isfile(path):
            return self.send_error(404)
        if os.path.splitext(path)[1].lower() not in md.AUDIO_EXTENSIONS:
            return self.send_error(403)

        size = os.path.getsize(path)
        ext = os.path.splitext(path)[1].lower()
        ctype = MIME_TYPES.get(ext, "application/octet-stream")

        start, end = 0, size - 1
        status = 200
        range_header = self.headers.get("Range")
        if range_header:
            match = re.match(r"bytes=(\d*)-(\d*)$", range_header.strip())
            if match:
                first, last = match.groups()
                valid = True
                if first:
                    start = int(first)
                    if last:
                        end = min(int(last), size - 1)
                        if int(last) < start:
                            valid = False
                elif last:
                    start = max(0, size - int(last))
                if valid:
                    if start >= size:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    status = 206
                else:
                    start, end = 0, size - 1

        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        if head_only:
            return
        try:
            with open(path, "rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            return

    def serve_static(self, route):
        rel = route.lstrip("/") or "index.html"
        if rel.startswith("static/"):
            rel = rel[len("static/"):]
        target = (STATIC_DIR / rel).resolve()
        if not target.is_relative_to(STATIC_DIR) or not target.is_file():
            return self.send_error(404)
        try:
            stat = target.stat()
        except OSError:
            return self.send_error(404)
        entry = _static_cache.get(str(target))
        if entry is None or entry[0] != stat.st_mtime_ns:
            data = target.read_bytes()
            etag = '"%x-%x"' % (int(stat.st_mtime_ns), len(data))
            entry = (stat.st_mtime_ns, data, etag)
            _static_cache[str(target)] = entry
        _, data, etag = entry
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return
        ctype = MIME_TYPES.get(target.suffix.lower(), "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("ETag", etag)
        self.end_headers()
        self.wfile.write(data)


def _lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            return probe.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return None


def main():
    port = DEFAULT_PORT
    host = HOST
    for index, arg in enumerate(sys.argv):
        if arg == "--port" and index + 1 < len(sys.argv):
            port = int(sys.argv[index + 1])
        if arg == "--host" and index + 1 < len(sys.argv):
            host = sys.argv[index + 1]

    LIBRARY.load()
    dl_dir = DOWNLOADER.get_download_dir()
    if os.path.isdir(dl_dir) and dl_dir not in LIBRARY.folders:
        with _library_lock:
            LIBRARY.folders.append(dl_dir)
            LIBRARY.save()

    server = None
    for candidate in range(port, port + 25):
        try:
            server = ThreadingHTTPServer((host, candidate), Handler)
            port = candidate
            break
        except OSError:
            continue
    if server is None:
        print("Could not bind to any port in range", port, "-", port + 24)
        sys.exit(1)

    lan_ip = _lan_ip() if host in ("0.0.0.0", "::") else None
    display_host = lan_ip or "127.0.0.1"
    url = f"http://{display_host}:{port}"
    print()
    print("  MANZ MUSIC PLAYER")
    print("  -----------------")
    print(f"  Local library : {len(LIBRARY.tracks)} tracks in {len(LIBRARY.folders)} folder(s)")
    print(f"  Data file     : {LIBRARY_FILE}")
    print(f"  Open in browser: {url}")
    if lan_ip:
        print()
        print(f"  Phones/other PCs on the same Wi-Fi: http://{lan_ip}:{port}")
        print("  Anyone on your network can open this while the server runs.")
        print("  Only do this on a trusted home network.")
    print()
    print("  Ctrl+C to stop.")
    print()

    if "--no-browser" not in sys.argv:
        local_url = f"http://127.0.0.1:{port}"
        threading.Timer(0.9, lambda: webbrowser.open(local_url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")


if __name__ == "__main__":
    main()
