import hashlib
import os

from mutagen import File as MutagenFile

AUDIO_EXTENSIONS = {
    ".flac", ".wav", ".mp3", ".m4a", ".m4b", ".mp4", ".aac",
    ".ogg", ".oga", ".opus", ".aiff", ".aif", ".wv", ".tta",
}

LOSSLESS_CODECS = {"FLAC", "WAV", "PCM", "AIFF", "ALAC", "WavPack", "TTA", "Monkey's Audio"}

PLAYABLE_EXTENSIONS = {".flac", ".wav", ".mp3", ".m4a", ".m4b", ".mp4", ".aac", ".ogg", ".oga", ".opus"}

MODULE_CODECS = {
    "flac": "FLAC",
    "mp3": "MP3",
    "mp4": "AAC",
    "oggvorbis": "Vorbis",
    "oggopus": "Opus",
    "oggtheora": "Theora",
    "wave": "WAV",
    "aiff": "AIFF",
    "wavpack": "WavPack",
    "tta": "TTA",
    "monkeysaudio": "Monkey's Audio",
    "aac": "AAC",
}


def track_id(path):
    return hashlib.sha1(path.encode("utf-8", "replace")).hexdigest()[:16]


def _first(value):
    if isinstance(value, (list, tuple)):
        return value[0] if value else ""
    return value if value is not None else ""


def _clean(value):
    return str(_first(value)).strip()


def _year(value):
    raw = _clean(value)
    digits = "".join(ch for ch in raw[:4] if ch.isdigit())
    return digits if len(digits) == 4 else ""


def _number(value):
    raw = _clean(value)
    head = raw.split("/")[0].strip()
    return head if head.isdigit() else ""


def _codec_for(audio, ext):
    module = type(audio).__module__.rsplit(".", 1)[-1]
    if module == "mp4":
        info_codec = str(getattr(audio.info, "codec", "") or "")
        if "alac" in info_codec.lower():
            return "ALAC"
        return "AAC"
    return MODULE_CODECS.get(module, ext.lstrip(".").upper())


def parse_track(path, stat=None):
    ext = os.path.splitext(path)[1].lower()
    name = os.path.basename(path)
    stem = os.path.splitext(name)[0]
    if stat is None:
        stat = os.stat(path)

    title, artist = stem, ""
    if " - " in stem:
        left, right = stem.split(" - ", 1)
        if left.strip() and right.strip():
            artist, title = left.strip(), right.strip()

    track = {
        "id": track_id(path),
        "path": path,
        "file": name,
        "ext": ext.lstrip("."),
        "size": stat.st_size,
        "mtime": int(stat.st_mtime),
        "title": title,
        "artist": artist,
        "album": "",
        "albumArtist": "",
        "genre": "",
        "year": "",
        "track": "",
        "disc": "",
        "duration": 0.0,
        "codec": ext.lstrip(".").upper(),
        "sampleRate": 0,
        "bitsPerSample": 0,
        "bitrate": 0,
        "channels": 0,
        "lossless": ext in (".flac", ".wav"),
        "playable": ext in PLAYABLE_EXTENSIONS,
        "hasCover": False,
    }

    audio = None
    try:
        audio = MutagenFile(path)
    except Exception:
        audio = None

    if audio is not None:
        info = getattr(audio, "info", None)
        if info is not None:
            track["duration"] = round(float(getattr(info, "length", 0) or 0), 2)
            track["sampleRate"] = int(getattr(info, "sample_rate", 0) or 0)
            track["bitsPerSample"] = int(getattr(info, "bits_per_sample", 0) or 0)
            track["bitrate"] = int(getattr(info, "bitrate", 0) or 0)
            track["channels"] = int(getattr(info, "channels", 0) or 0)
        track["codec"] = _codec_for(audio, ext)

    if track["bitrate"] <= 0 and track["duration"] > 0:
        track["bitrate"] = int(track["size"] * 8 / track["duration"])

    track["lossless"] = track["codec"] in LOSSLESS_CODECS or (
        track["codec"] == ext.lstrip(".").upper() and ext in (".flac", ".wav", ".aiff", ".aif")
    )
    track["playable"] = ext in PLAYABLE_EXTENSIONS and track["codec"] != "ALAC"

    try:
        tagged = MutagenFile(path, easy=True)
        tags = getattr(tagged, "tags", None) if tagged is not None else None
        if tags:
            if _clean(tags.get("title")):
                track["title"] = _clean(tags.get("title"))
            if _clean(tags.get("artist")):
                track["artist"] = _clean(tags.get("artist"))
            track["album"] = _clean(tags.get("album"))
            track["albumArtist"] = _clean(tags.get("albumartist")) or track["artist"]
            track["genre"] = _clean(tags.get("genre"))
            track["year"] = _year(tags.get("date") or tags.get("year"))
            track["track"] = _number(tags.get("tracknumber"))
            track["disc"] = _number(tags.get("discnumber"))
            track["composer"] = _clean(tags.get("composer"))
    except Exception:
        pass

    if not track["albumArtist"]:
        track["albumArtist"] = track["artist"]

    channels_str = "Stereo (2.0)" if track["channels"] == 2 else ("Mono (1.0)" if track["channels"] == 1 else f"{track['channels']}ch")
    sample_rate_str = f"{track['sampleRate'] / 1000:.1f} kHz" if track["sampleRate"] else ""
    bit_depth_str = f"{track['bitsPerSample']}-bit" if track["bitsPerSample"] else ""
    bitrate_str = f"{round(track['bitrate'] / 1000)} kbps" if track["bitrate"] else ""
    quality_type = "LOSSLESS HI-FI" if track["lossless"] else "LOSSY"
    specs = [s for s in [bit_depth_str, sample_rate_str, bitrate_str, channels_str] if s]
    track["fileType"] = f"{track['codec']} Audio (.{track['ext']})"
    track["qualitySummary"] = f"{track['codec']} · {quality_type} · {' / '.join(specs)}"

    try:
        track["hasCover"] = _probe_cover(audio)
    except Exception:
        track["hasCover"] = False

    return track


def _probe_cover(audio):
    if audio is None:
        return False
    pictures = getattr(audio, "pictures", None)
    if pictures:
        return any(pic.data and len(pic.data) >= 64 for pic in pictures)
    tags = getattr(audio, "tags", None)
    if not tags:
        return False
    try:
        keys = list(tags.keys())
    except Exception:
        return False
    for key in keys:
        if str(key).startswith("APIC"):
            data = getattr(tags[key], "data", None) or b""
            if len(data) >= 64:
                return True
    try:
        cover = tags.get("covr")
    except Exception:
        cover = None
    if cover:
        try:
            return len(bytes(cover[0])) >= 64
        except Exception:
            return False
    return False


def extract_cover(path):
    try:
        audio = MutagenFile(path)
    except Exception:
        return None
    if audio is None:
        return None

    pictures = getattr(audio, "pictures", None)
    if pictures:
        for pic in pictures:
            if pic.data and len(pic.data) >= 64:
                return sanitize_mime(getattr(pic, "mime", ""), pic.data), pic.data

    tags = getattr(audio, "tags", None)
    if tags:
        try:
            from mutagen.mp4 import MP4Cover

            cover = tags.get("covr")
            if cover:
                image = cover[0]
                data = bytes(image)
                if len(data) >= 64:
                    fmt = getattr(image, "imageformat", None)
                    mime = "image/png" if fmt == MP4Cover.FORMAT_PNG else "image/jpeg"
                    return mime, data
        except Exception:
            pass

        raw = tags.get("metadata_block_picture")
        if raw:
            try:
                import base64

                from mutagen.flac import Picture

                pic = Picture(base64.b64decode(_first(raw)))
                return sanitize_mime(getattr(pic, "mime", ""), pic.data), pic.data
            except Exception:
                pass

        try:
            for key in tags.keys():
                if str(key).startswith("APIC"):
                    frame = tags[key]
                    data = frame.data or b""
                    if len(data) >= 64:
                        return sanitize_mime(getattr(frame, "mime", ""), data), data
        except Exception:
            pass
    return None


def sanitize_mime(mime, data):
    mime = (mime or "").strip().lower()
    if mime.startswith("image/"):
        return mime
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"RIFF":
        return "image/webp"
    return "image/jpeg"
