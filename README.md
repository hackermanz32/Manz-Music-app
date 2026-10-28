# Manz Music Player (Windows 11)

A self-hosted local music player with a YouTube Music-style interface, lossless-quality
badges, cover art, queue and Up Next, plus an Apple Music link downloader.

This folder is the Windows 11 package. It contains everything needed to run the app;
the first launch sets up its own private Python environment.

---

## Project home and updates

The newest version of this app — interface (UI), fixes and new features — is always
published on GitHub:

> **https://github.com/YOUR-USERNAME/manz-music-player**
> _(replace this line with your own repository link)_

Whenever I change something on this PC, I test it here first and then push it, so the GitHub
copy is always the latest version:

```bat
git add .
git commit -m "short description of the change"
git push
```

`static/` holds the UI (HTML/CSS/JS) — most interface changes happen there.

Music folders, `.venv`, `__pycache__` and your library index stay local and are **not**
pushed to GitHub.

---

## Quick start

1. Copy this whole `manz_music app` folder to the Windows PC, for example:
   `C:\Users\<you>\Apps\manz_music app`
2. Double-click **`launch-windows.bat`**.
   - If Python 3.10+ is missing, the launcher tries to install Python 3.12 with winget.
   - It creates a local `.venv` and installs the required packages (internet needed once).
   - The server starts and opens **http://127.0.0.1:8642** in your browser.
3. In the app, click **+ Add music folder** and choose the folder that contains your music.
   The folder picker is a native Windows dialog. If it does not appear, type the full path
   into the prompt, for example `C:\Users\<you>\Music`.

Keep the launcher window open while you use the app. Closing it stops the server.

> First launch can take 1-3 minutes while packages download. Later launches are quick.

**Want to use it from your phone as well?** Start it with **`launch-windows-lan.bat`**
instead (or use the desktop shortcut below). That is the same app, but it also accepts
connections from other devices on your Wi-Fi — your browser still opens on this PC.

---

## Optional desktop shortcut

Double-click **`create-desktop-shortcut.bat`** once to put a **Manz Music Player** shortcut on
your Desktop (uses `icon.ico`).

The shortcut starts **LAN mode**, so a single click serves both this PC and your phone or
other devices on the same Wi-Fi. The app still opens on this PC and the console shows the
address to use on the phone.

The **first** time you use it, Windows asks for firewall permission once (choose **Yes**).
After that, one click = server + browser, no extra steps.

---

## Use it from your phone or another PC (LAN)

1. Double-click **`launch-windows-lan.bat`** (same setup, but listens on the local network).
   The Desktop shortcut does the same thing, so normally you only need that one click.
2. The launcher adds the firewall rule itself on first use — approve the Windows
   administrator prompt. If you skip it, double-click **`allow-lan-firewall.bat`** once and
   approve the prompt.
3. Find this PC's IPv4 address in Command Prompt:

   ```bat
   ipconfig
   ```

   Look for `IPv4 Address` under your Wi-Fi/Ethernet adapter, e.g. `192.168.1.20`.
4. On the phone or other PC (same Wi-Fi/router), open:

   ```text
   http://192.168.1.20:8642
   ```

The PC running the server must stay on. The app has no login, so only use LAN mode on a
trusted home network.

If port 8642 is already in use, the app uses the next free port (8643-8666). The console
prints the actual address; the firewall script allows that whole range.

---

## Where your data lives

| What | Location |
| --- | --- |
| Library index and settings | `%LOCALAPPDATA%\ManzMusicPlayer\` |
| Cover thumbnail cache | `%LOCALAPPDATA%\ManzMusicPlayer\thumb-cache\` |
| Default download folder | `%USERPROFILE%\Music\Apple Music` |

`%LOCALAPPDATA%` is normally `C:\Users\<you>\AppData\Local`.

The library index stores full file paths. If you move music to another drive/folder,
open the app, remove the old folder from the sidebar, and add the new one.

### Reset the app

1. Close the app window.
2. Delete `%LOCALAPPDATA%\ManzMusicPlayer`.

This removes the index, settings and thumbnail cache. It does **not** delete any music
files or downloads.

---

## What is included

| File | Purpose |
| --- | --- |
| `launch-windows.bat` | Setup and launch on localhost only |
| `launch-windows-lan.bat` | Setup and launch for this PC **and** your phone/other PCs |
| `allow-lan-firewall.bat` | Adds the Windows Firewall rule for LAN mode |
| `create-desktop-shortcut.bat` | Creates a Desktop shortcut that launches LAN mode |
| `server.py` | HTTP server and library scanner |
| `downloader.py` | Apple Music link resolver / download queue |
| `metadata.py` | Audio metadata, cover art and quality detection |
| `static/` | The web interface (HTML, CSS, JavaScript) |
| `requirements.txt` | Python packages installed on first launch |
| `icon.ico`, `icon.png` | App icons |

No `.venv`, library database, cache, or test files are included. A fresh Windows install
starts with an empty library.

---

## Features

- Local playback of FLAC, WAV, MP3, M4A/AAC, OGG/Opus, AIFF, WavPack and TTA.
- Range-based seeking, queue, shuffle, volume, media keys and a full-screen Now Playing view.
- Search and sorting by title, album, quality and duration.
- Lossless / hi-res / lossy quality badges, embedded cover art thumbnails.
- Sidebar libraries per folder, drag-free folder management and rescans.
- Apple Music song/album/playlist link parsing with a background download queue.
- Responsive YouTube Music-style layout for phone and desktop browsers.

### About downloads

The downloader resolves Apple Music page metadata, then fetches matching audio with
`yt-dlp`, converts/tags it with the bundled FFmpeg, and embeds the Apple artwork. It is
not Apple's official lossless stream and quality depends on the source. Only download
content you have permission to keep.

FFmpeg is provided automatically by the `imageio-ffmpeg` package - no separate FFmpeg
install is required.

---

## Troubleshooting

**Python is not found / winget fails**
Install Python 3.10 or newer from <https://www.python.org/downloads/windows/> and tick
**Add python.exe to PATH** during setup. Then run `launch-windows.bat` again.

**Windows protected your PC / SmartScreen**
The `.bat` files are plain local scripts, not signed installers. If Windows warns, choose
**More info -> Run anyway**. If you downloaded the folder as a ZIP, you can also right-click
the ZIP -> Properties -> **Unblock** before extracting.

**Package installation failed**
Check the internet connection and run `launch-windows.bat` again. If it still fails, delete
the `.venv` folder inside the app folder and retry.

**No folder dialog appears**
Type the full folder path in the prompt instead, e.g. `C:\Users\<you>\Music`.
The native picker opens on the PC that runs the server, not on a remote phone.

**Port 8642 is busy**
The server automatically tries 8643-8666 and prints the address it used. Open that address.
For LAN mode, re-run `allow-lan-firewall.bat` if you restricted the rule.

**Phone cannot connect**
Use the exact address the console prints (e.g. `http://192.168.0.2:8642`), not `127.0.0.1`.
Both devices must be on the same Wi-Fi. If it still fails, Windows may treat that network as
**Public**: open Settings -> Network & Internet -> Wi-Fi -> your network and set it to
**Private**, then launch again (or run `allow-lan-firewall.bat`).

**The app opens but there is no sound**
Start playback with the play button first (browsers block autoplay). Check the volume
slider and the Windows output device.

**Moving the app to another PC**
Copy the app folder, but do **not** copy `.venv` - delete it if present. The launcher
rebuilds it for that PC. Music paths in the library index are absolute, so re-add your
music folders on the new PC.

**Covers look blurry or are missing**
Make sure Pillow installed successfully (`Pillow` is in `requirements.txt`). Re-run the
launcher after fixing the install. Tracks without embedded art show a music-note tile.

---

## Security and privacy

- The app is a local web server. Localhost mode is only reachable from this PC.
- LAN mode has no password or user accounts. Anyone on that network can browse and play
  the library and use the downloader while it runs.
- Do not expose port 8642 directly to the internet or run LAN mode on public Wi-Fi.
