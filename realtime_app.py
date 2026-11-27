"""
FlashHead Realtime Lip-Sync - GUI Application

Built on the Sapphire FlashHead plugin by Chris (ddxfish):
    https://github.com/ddxfish/sapphire-flashhead
That plugin owns the server, the streaming protocol, the memory presets and the
model fetching. This app only talks to its HTTP server and never modifies it.
SoulX-FlashHead itself is by Soul-AILab (Apache-2.0).

Workflow:
  1. Pick audio file (left)
  2. Pick avatar PNG (right)  -> preview shows
  3. CONNECT   -> attaches to FlashHead server + loads the avatar (idle)
  4. START     -> streams audio to the server and shows the talking avatar live
                  in this window, with the audio playing in sync.
"""

import os
import sys
import time
import tempfile
import threading
import collections
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox

SERVER_URL = "http://127.0.0.1:5017"
FPS = 25
VIEW_W, VIEW_H = 440, 580
HEAD_SIZE = 512                      # what the server renders (full preset)

# The head box is remembered per avatar in this csv, so the crop is always the
# exact same one the video used (never a fresh guess).
BOX_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "head_boxes.csv")

def _root_for(server_py):
    """The SAPPHIRE_ROOT the server expects for this server.py.

    The plugin works both ways (see its own flashhead-server.bat):
      - inside a Sapphire install: <root>\\user\\plugins\\flashhead\\server.py
        -> root is that Sapphire folder, models go to <root>\\user\\models\\flashhead
      - standalone clone: <folder>\\server.py
        -> root is that folder itself, models go to <folder>\\user\\models\\flashhead
    Sapphire itself is never required."""
    plugin = os.path.dirname(os.path.abspath(server_py))
    parent = os.path.dirname(plugin)
    if (os.path.basename(parent).lower() == "plugins"
            and os.path.basename(os.path.dirname(parent)).lower() == "user"):
        return os.path.dirname(os.path.dirname(parent))   # ...\user\plugins\flashhead
    return plugin                                         # standalone clone


def _resolve(path):
    """Turn a folder into (root, server.py) when it holds the FlashHead plugin.

    Accepts the plugin folder, the folder it was cloned into, or a Sapphire
    root. Returns None when there is no server there."""
    if not path:
        return None
    path = os.path.abspath(os.path.expanduser(str(path).strip().strip('"')))
    if not os.path.isdir(path):
        return None
    for sub in ("", "flashhead", "sapphire-flashhead",
                os.path.join("user", "plugins", "flashhead")):
        folder = os.path.join(path, sub) if sub else path
        server_py = os.path.join(folder, "server.py")
        if os.path.isfile(server_py) and os.path.isfile(
                os.path.join(folder, "plugin.json")):
            return _root_for(server_py), server_py
    return None


def _candidates():
    """Every place the FlashHead plugin is likely to be, best first."""
    here = os.path.dirname(os.path.abspath(__file__))

    # 1. a plain text file beside the app wins over everything
    for name in ("flashhead_root.txt", "sapphire_root.txt"):
        try:
            with open(os.path.join(here, name), encoding="utf-8") as f:
                for line in f:
                    line = line.strip().strip('"')
                    if line and not line.startswith("#"):
                        yield line
        except OSError:
            pass

    # 2. the environment variable the server itself reads
    for var in ("SAPPHIRE_ROOT", "FLASHHEAD_ROOT"):
        if os.environ.get(var):
            yield os.environ[var]

    # 3. beside or inside this app (a clone here is the easiest setup)
    for name in ("sapphire-flashhead", "flashhead", "sapphire"):
        yield os.path.join(here, name)
    parent = os.path.dirname(here)
    for name in ("sapphire-flashhead", "flashhead", "sapphire"):
        yield os.path.join(parent, name)

    # 4. the usual install spots
    home = os.path.expanduser("~")
    names = ("sapphire-flashhead", "flashhead", "sapphire", "Sapphire")
    for name in names:
        yield os.path.join(home, name)
        yield os.path.join(home, "Documents", name)
        yield os.path.join(home, "Desktop", name)
    for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("APPDATA"),
                 os.environ.get("ProgramFiles"), "C:\\", "D:\\"):
        if base:
            for name in names:
                yield os.path.join(base, name)

    # 5. a folder on another fixed drive
    for drive in "CDEF":
        for name in ("sapphire-flashhead", "flashhead", "sapphire"):
            yield drive + ":\\" + name


def _find_server():
    """(root, server.py) of the first candidate that really holds the plugin."""
    for path in _candidates():
        found = _resolve(path)
        if found:
            return found
    return None, None


# Auto-detected at import; CONNECT re-checks, so installing later still works.
SERVER_ROOT, SERVER_PY = _find_server()
SAPPHIRE_ROOT = SERVER_ROOT          # the name the server reads from its env


def _server_py(root=None):
    """Path to the plugin's server.py, or None when the plugin is not installed."""
    if root:
        found = _resolve(root)
        return found[1] if found else None
    return SERVER_PY or _find_server()[1]


def _parse_packet(buf):
    """Read one complete packet from buf without consuming partial data.
    Packet: >I header_len | JSON header | audio | JPEG frames...
    Returns (header_dict, [jpeg_bytes]) or None.
    Always leaves the write position at the end, so callers can keep appending."""
    import json
    data = buf.getvalue()
    if len(data) < 4:
        buf.seek(0, 2)
        return None
    hlen = int.from_bytes(data[:4], "big")
    if hlen <= 0 or len(data) < 4 + hlen:
        buf.seek(0, 2)
        return None
    try:
        head = json.loads(data[4:4 + hlen].decode())
    except Exception:
        buf.seek(0, 2)
        return None
    audio_len = head.get("audio", 0)
    frame_lens = head.get("frames", [])
    need = 4 + hlen + audio_len + sum(frame_lens)
    if len(data) < need:
        buf.seek(0, 2)
        return None
    off = 4 + hlen + audio_len
    jpegs = []
    for fl in frame_lens:
        jpegs.append(data[off:off + fl])
        off += fl
    buf.seek(0)
    buf.truncate()
    buf.write(data[need:])
    buf.seek(0, 2)
    return head, jpegs


class App:
    def __init__(self, root):
        self.root = root
        root.title("FlashHead Realtime Lip-Sync")
        root.geometry("800x930")
        root.minsize(760, 800)
        root.configure(bg="#1e1e1e")

        self.audio_path = ""
        self.avatar_path = ""
        self.client = None
        self.connected = False
        self.running = False
        self.stop_flag = threading.Event()

        self.frames = collections.deque()
        self.t0 = None
        self.audio_started = False
        self.shown = 0
        self.total = 0
        self.dropped = 0
        self.stream_ended = False
        self._photo = None
        self._head_box = None
        self._base_frame = None
        self._audio_16k = None
        self._wav_bytes = None
        self._stream = None
        self._t_audio0 = 0.0
        self._play_audio = None
        self._audio_seconds = 0.0
        self.use_audio_clock = False
        self._tmp_wav = None
        self._player = None

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # "." stops the stream, like you asked
        self.root.bind("<period>", lambda e: self.stop_stream())
        self.root.bind("<KP_Decimal>", lambda e: self.stop_stream())
        self.root.after(20, self._ui_tick)

    # ------------------------------------------------------------------ UI --
    def _build_ui(self):
        tk.Label(self.root, text="FlashHead Realtime Lip-Sync",
                 font=("Segoe UI", 16, "bold"), bg="#1e1e1e", fg="white").pack(pady=(12, 6))

        # ---- file pickers -------------------------------------------------
        top = tk.Frame(self.root, bg="#1e1e1e")
        top.pack(fill="x", padx=14, pady=4)

        left = tk.Frame(top, bg="#1e1e1e")
        left.pack(side="left", expand=True, fill="x", padx=(0, 8))
        tk.Label(left, text="1. AUDIO FILE", font=("Segoe UI", 9, "bold"),
                 bg="#1e1e1e", fg="#9e9e9e").pack(anchor="w")
        self.audio_var = tk.StringVar()
        tk.Entry(left, textvariable=self.audio_var, width=34,
                 font=("Segoe UI", 9)).pack(fill="x", pady=2)
        tk.Button(left, text="Browse Audio", command=self.browse_audio,
                  bg="#455a64", fg="white", font=("Segoe UI", 9, "bold"),
                  relief="flat", cursor="hand2").pack(fill="x")

        right = tk.Frame(top, bg="#1e1e1e")
        right.pack(side="left", expand=True, fill="x", padx=(8, 0))
        tk.Label(right, text="2. AVATAR IMAGE", font=("Segoe UI", 9, "bold"),
                 bg="#1e1e1e", fg="#9e9e9e").pack(anchor="w")
        self.avatar_var = tk.StringVar()
        tk.Entry(right, textvariable=self.avatar_var, width=34,
                 font=("Segoe UI", 9)).pack(fill="x", pady=2)
        tk.Button(right, text="Browse Avatar", command=self.browse_avatar,
                  bg="#455a64", fg="white", font=("Segoe UI", 9, "bold"),
                  relief="flat", cursor="hand2").pack(fill="x")

        # ---- buttons ------------------------------------------------------
        bar = tk.Frame(self.root, bg="#1e1e1e")
        bar.pack(pady=10)

        self.connect_btn = tk.Button(
            bar, text="CONNECT", command=self.connect_server,
            font=("Segoe UI", 11, "bold"), bg="#2196F3", fg="white",
            activebackground="#1976D2", activeforeground="white",
            relief="flat", width=14, height=2, cursor="hand2")
        self.connect_btn.pack(side="left", padx=6)

        self.start_btn = tk.Button(
            bar, text="START STREAM", command=self.start_stream,
            font=("Segoe UI", 12, "bold"), bg="#4CAF50", fg="white",
            activebackground="#388E3C", activeforeground="white",
            relief="flat", width=18, height=2, cursor="hand2", state="disabled")
        self.start_btn.pack(side="left", padx=6)

        self.stop_btn = tk.Button(
            bar, text="STOP", command=self.stop_stream,
            font=("Segoe UI", 11, "bold"), bg="#f44336", fg="white",
            activebackground="#c62828", activeforeground="white",
            relief="flat", width=12, height=2, cursor="hand2", state="disabled")
        self.stop_btn.pack(side="left", padx=6)

        for b in (self.connect_btn, self.start_btn, self.stop_btn):
            b.config(disabledforeground="#e0e0e0")

        tk.Label(bar, text="press  .  to stop", bg="#1e1e1e", fg="#777777",
                 font=("Segoe UI", 9)).pack(side="left", padx=10)

        # audio output + sync nudge
        out_row = tk.Frame(self.root, bg="#1e1e1e")
        out_row.pack(pady=(0, 4))
        tk.Label(out_row, text="Audio out:", bg="#1e1e1e", fg="#9e9e9e",
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))
        self._devices = self._list_output_devices()
        labels = ["Auto (speakers)"] + [lab for _, lab in self._devices]
        self.device_var = tk.StringVar(value="Auto (speakers)")
        menu = tk.OptionMenu(out_row, self.device_var, *labels)
        menu.config(bg="#37474f", fg="white", activebackground="#455a64",
                    activeforeground="white", font=("Segoe UI", 9),
                    relief="flat", highlightthickness=0, width=30)
        menu["menu"].config(bg="#263238", fg="white", font=("Segoe UI", 9))
        menu.pack(side="left", padx=(0, 14))

        tk.Label(out_row, text="Sync ms:", bg="#1e1e1e", fg="#9e9e9e",
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 4))
        self.sync_var = tk.IntVar(value=-100)   # measured: lips ~120 ms late
        tk.Spinbox(out_row, from_=-500, to=500, increment=20, width=6,
                   textvariable=self.sync_var, font=("Segoe UI", 9),
                   bg="#37474f", fg="white", buttonbackground="#455a64",
                   relief="flat").pack(side="left")

        # ---- status (anchored to the bottom: never clipped) ----------------
        self.progress = tk.Label(self.root, text="", font=("Segoe UI", 9),
                                 bg="#1e1e1e", fg="#777777")
        self.progress.pack(side="bottom", pady=(0, 8))
        self.status = tk.Label(self.root, text="Select audio + avatar, then CONNECT",
                               font=("Segoe UI", 10), bg="#1e1e1e", fg="#bbbbbb")
        self.status.pack(side="bottom", pady=(0, 4))

        # ---- live view ----------------------------------------------------
        holder = tk.Frame(self.root, bg="black",
                          highlightthickness=1, highlightbackground="#333333")
        holder.pack(pady=8, padx=10, fill="both", expand=True)
        self.view = tk.Label(holder, text="Avatar preview / live stream",
                             bg="black", fg="#777777", font=("Segoe UI", 11))
        self.view.pack(fill="both", expand=True)

    # ------------------------------------------------------------ helpers --
    def _set_status(self, text, color="#bbbbbb"):
        self.root.after(0, lambda: self.status.config(text=text, fg=color))

    def _show_image(self, img_bgr, composite=False):
        """Display a BGR numpy image in the view label (main thread).

        With composite=True the 512x512 head render is pasted back into the
        full avatar at the remembered head box - the exact look the video had.
        """
        import cv2
        from PIL import Image, ImageTk

        if composite and self._base_frame is not None and self._head_box is not None:
            try:
                from compositor import composite_head
                img_bgr = composite_head(self._base_frame, img_bgr, self._head_box)
            except Exception as e:
                print("composite failed:", e, flush=True)

        h, w = img_bgr.shape[:2]
        vw = self.view.winfo_width()
        vh = self.view.winfo_height()
        if vw < 50 or vh < 50:                 # not laid out yet
            vw, vh = VIEW_W, VIEW_H
        scale = min(vw / w, vh / h)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        img = cv2.resize(img_bgr, (nw, nh), interpolation=cv2.INTER_AREA)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        self._photo = ImageTk.PhotoImage(Image.fromarray(img))
        self.view.config(image=self._photo, text="")

    def _detect_box(self, img):
        """Chest-to-above-head box, the same crop the video used."""
        try:
            import cv2
            from face_detector import FaceDetector
            cascade = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            det = FaceDetector(cascade)
            box = det.detect_head_box(img)
            print("head box detected:", box, flush=True)
            return box
        except Exception as e:
            print("head box detection failed:", e, flush=True)
            return None

    # ---- remembered head boxes (csv, same idea as the video pipeline) -----
    def _load_box_from_csv(self, avatar_path):
        import csv
        key = os.path.basename(avatar_path).lower()
        try:
            with open(BOX_CSV, newline="") as f:
                for row in csv.DictReader(f):
                    if (row.get("image") or "").lower() == key:
                        return (int(row["x"]), int(row["y"]),
                                int(row["w"]), int(row["h"]))
        except FileNotFoundError:
            pass
        except Exception as e:
            print("box csv read failed:", e, flush=True)
        return None

    def _save_box_to_csv(self, avatar_path, box):
        import csv
        key = os.path.basename(avatar_path).lower()
        rows = []
        try:
            with open(BOX_CSV, newline="") as f:
                rows = [r for r in csv.DictReader(f)
                        if (r.get("image") or "").lower() != key]
        except Exception:
            rows = []
        rows.append({"image": key, "x": box[0], "y": box[1],
                     "w": box[2], "h": box[3]})
        try:
            with open(BOX_CSV, "w", newline="") as f:
                wr = csv.DictWriter(f, fieldnames=["image", "x", "y", "w", "h"])
                wr.writeheader()
                wr.writerows(rows)
        except Exception as e:
            print("box csv write failed:", e, flush=True)

    def _prepare_face(self, avatar_path):
        """Crop the head box and send THAT to the server (never the whole
        portrait - the server squashes it to 512x512 and the face warps)."""
        import cv2
        base = cv2.imread(avatar_path)
        if base is None:
            raise RuntimeError("Cannot read avatar image: %s" % avatar_path)

        ih, iw = base.shape[:2]
        box = self._load_box_from_csv(avatar_path)
        if box is None:
            box = self._detect_box(base)
            if box:
                self._save_box_to_csv(avatar_path, box)
        if not box:
            box = (0, 0, iw, ih)

        x, y, w, h = box
        x = max(0, min(int(x), iw - 8))
        y = max(0, min(int(y), ih - 8))
        w = max(8, min(int(w), iw - x))
        h = max(8, min(int(h), ih - y))
        box = (x, y, w, h)

        crop = base[y:y + h, x:x + w]
        crop = cv2.resize(crop, (HEAD_SIZE, HEAD_SIZE), interpolation=cv2.INTER_AREA)

        fd, ref = tempfile.mkstemp(suffix=".png", prefix="fh_face_")
        os.close(fd)
        cv2.imwrite(ref, crop)

        self._base_frame = base
        self._head_box = box
        print("head box:", box, "-> %dx%d face reference" % (HEAD_SIZE, HEAD_SIZE),
              flush=True)
        return ref

    def _show_preview(self, path):
        try:
            import cv2
            img = cv2.imread(path)
            if img is None:
                return
            self._show_image(img)
        except Exception as e:
            print("preview error:", e)

    # ------------------------------------------------------------- pickers --
    def browse_audio(self):
        path = filedialog.askopenfilename(
            title="Select audio file",
            filetypes=[("Audio", "*.wav *.mp3 *.ogg *.flac *.m4a"), ("All files", "*.*")])
        if path:
            self.audio_path = path
            self.audio_var.set(path)
            self._set_status("Audio selected: %s" % os.path.basename(path))

    def browse_avatar(self):
        path = filedialog.askopenfilename(
            title="Select avatar image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp"), ("All files", "*.*")])
        if path:
            self.avatar_path = path
            self.avatar_var.set(path)
            self._show_preview(path)
            self._set_status("Avatar selected: %s" % os.path.basename(path))

    # ------------------------------------------------------------- connect --
    def _health_once(self):
        import json
        import urllib.request
        try:
            with urllib.request.urlopen(SERVER_URL + "/health", timeout=3) as r:
                return json.loads(r.read().decode())
        except Exception:
            return None

    def _server_is_up(self, client=None):
        h = self._health_once()
        return bool(h and h.get("status"))

    def _start_server(self, client=None):
        """Launch the FlashHead server ourselves if it is not running."""
        import subprocess
        global SERVER_ROOT, SERVER_PY, SAPPHIRE_ROOT
        found = _resolve(SERVER_ROOT) if SERVER_ROOT else None
        if not found:
            found = _find_server()
        root, server_py = found if found and found[1] else (None, None)
        if not server_py:
            raise RuntimeError(
                "FlashHead server not found.\n\n"
                "This app needs only the FlashHead plugin - Sapphire itself is optional.\n\n"
                "  git clone https://github.com/ddxfish/sapphire-flashhead\n"
                "  then run flashhead-server.bat once, in an Anaconda Prompt\n\n"
                "Put that clone next to this app, or point the app at it: create a file\n"
                "named sapphire_root.txt beside realtime_app.py containing the folder,\n"
                "e.g.\n  C:\\Users\\you\\sapphire-flashhead\n\n"
                "or set the SAPPHIRE_ROOT environment variable to the same folder.")
        SERVER_ROOT = SAPPHIRE_ROOT = root
        SERVER_PY = server_py
        server_dir = os.path.dirname(server_py)

        self._set_status("Starting FlashHead server... model load takes 1-2 minutes",
                         "#ffb300")
        print("FlashHead server:", server_py, flush=True)
        print("data folder     :", root, flush=True)
        env = dict(os.environ)
        env["SAPPHIRE_ROOT"] = root
        env["SAPPHIRE_SERVICE_PORT"] = "5017"
        env["PYTHONUTF8"] = "1"
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        self._server_proc = subprocess.Popen(
            [sys.executable, "server.py"], cwd=server_dir, env=env,
            creationflags=flags)

        deadline = time.monotonic() + 420
        last = None
        while True:
            if time.monotonic() > deadline:
                raise RuntimeError(
                    "server did not become ready in 7 minutes.\n\n"
                    "Its window has the details. If it was downloading the models,\n"
                    "just press CONNECT again once the download finishes.")
            if self.stop_flag.is_set():
                raise RuntimeError("cancelled")
            h = self._health_once()
            st = (h or {}).get("status")
            if st != last:
                msg = "Server: %s" % st if st else "Waiting for server to answer..."
                if h and h.get("error"):
                    msg += " - %s" % h["error"]
                self._set_status(msg, "#ffb300")
                last = st
            if st == "ready":
                return
            if st == "error":
                raise RuntimeError(h.get("error") or "server reported an error")
            pr = (h or {}).get("progress") or {}
            if pr.get("done"):
                # first run: the models are coming down from Hugging Face
                deadline = max(deadline, time.monotonic() + 900)
            time.sleep(2)

    def connect_server(self):
        if not self.avatar_path:
            messagebox.showerror("Missing avatar", "Pick an avatar image first.")
            return
        self.connect_btn.config(state="disabled")
        self._set_status("Connecting to FlashHead server...", "#ffb300")

        def work():
            try:
                from flashhead_inference import FlashHeadClient
                client = FlashHeadClient(server_url=SERVER_URL, idle="loop")

                if not self._server_is_up(client):
                    self._start_server(client)

                client.wait_for_ready(timeout=120)
                h = client.health() or {}
                gpu = h.get("gpu", {}) if isinstance(h.get("gpu"), dict) else {}
                preset = gpu.get("preset", h.get("preset", "?"))
                speed = gpu.get("speed", h.get("speed", "?"))
                client.set_face(self._prepare_face(self.avatar_path))
                self.client = client
                self.connected = True
                self.root.after(0, lambda: self.start_btn.config(state="normal"))
                self.root.after(0, lambda: self.stop_btn.config(state="normal"))
                self._set_status(
                    "Connected  |  %s preset  |  %sx realtime  |  avatar loaded - ready to stream"
                    % (preset, speed), "#4CAF50")
                print("Connected: preset=%s speed=%s" % (preset, speed))
            except Exception as e:
                self.connected = False
                self.root.after(0, lambda: self.connect_btn.config(state="normal"))
                self._set_status("Connection failed: %s" % e, "#f44336")
                self.root.after(0, lambda: messagebox.showerror(
                    "Connection failed",
                    "%s\n\nIs the FlashHead server running on port 5017?" % e))

        threading.Thread(target=work, daemon=True).start()

    # -------------------------------------------------------------- stream --
    def start_stream(self):
        if self.running:
            return
        if not self.audio_path:
            messagebox.showerror("Missing audio", "Pick an audio file first.")
            return
        if not self.connected or self.client is None:
            messagebox.showerror("Not connected", "Click CONNECT first.")
            return

        self.running = True
        self.stop_flag.clear()
        self.frames.clear()
        self.t0 = None
        self.audio_started = False
        self.shown = 0
        self.total = 0
        self.dropped = 0
        self.stream_ended = False
        self._stream = None
        self.use_audio_clock = False
        self.start_btn.config(state="disabled")
        self.connect_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.progress.config(text="Preparing audio...")
        self._set_status("Streaming - avatar is talking live", "#4CAF50")

        threading.Thread(target=self._stream_worker, daemon=True).start()

    def _stream_worker(self):
        tmp = None
        try:
            import io
            import socket
            import numpy as np
            import soundfile as sf
            import resampy

            audio, sr = sf.read(self.audio_path, always_2d=False)
            if getattr(audio, "ndim", 1) > 1:
                audio = audio.mean(axis=1)
            audio = np.asarray(audio, dtype=np.float32)
            if sr != 16000:
                audio = resampy.resample(audio, sr, 16000)
                sr = 16000

            fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="fh_rt_")
            os.close(fd)
            sf.write(tmp, audio, 16000, subtype="PCM_16")
            self._tmp_wav = tmp
            self._audio_16k = audio
            self._wav_bytes = None
            duration = len(audio) / 16000.0
            self.total = int(round(duration * FPS))
            self.root.after(0, lambda: self.progress.config(
                text="Audio %.1fs -> %d frames. Waiting for first frame..." % (duration, self.total)))

            # open the server's frame stream
            sock = socket.create_connection(("127.0.0.1", 5017), timeout=15)
            sock.sendall(b"GET /stream?audio=1 HTTP/1.1\r\n"
                         b"Host: 127.0.0.1:5017\r\nConnection: close\r\n\r\n")
            sock.settimeout(1.0)
            raw = b""
            while b"\r\n\r\n" not in raw:
                d = sock.recv(4096)
                if not d:
                    raise RuntimeError("stream closed while reading headers")
                raw += d
            _http_head, rest = raw.split(b"\r\n\r\n", 1)
            buf = io.BytesIO()
            buf.write(rest)

            # wait for our viewer to register
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and not self.stop_flag.is_set():
                h = self._health_once() or {}
                if h.get("viewers", 0) > 0:
                    break
                time.sleep(0.25)

            if self.stop_flag.is_set():
                return
            self.client.speak(tmp)

            idx = 0
            started = False
            last_speech = time.monotonic()
            while not self.stop_flag.is_set():
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf.seek(0, 2)
                buf.write(chunk)
                while True:
                    pkt = _parse_packet(buf)
                    if pkt is None:
                        break
                    head, jpegs = pkt
                    if head.get("kind") != "speech":
                        continue          # idle filler - ignore, it is not our audio
                    started = True
                    last_speech = time.monotonic()
                    for jpg in jpegs:
                        if self.stop_flag.is_set():
                            break
                        self.frames.append((idx, jpg))
                        idx += 1
                if started and idx >= self.total:
                    break
                if started and time.monotonic() - last_speech > 8:
                    break

            print("stream ended, frames received:", idx)
            try:
                sock.close()
            except Exception:
                pass
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._set_status("Stream error: %s" % e, "#f44336")
        finally:
            self.stream_ended = True
            # let the frames already queued play out before we clean up
            while self.frames and not self.stop_flag.is_set():
                time.sleep(0.05)
            if not self.stop_flag.is_set():
                self.root.after(0, self._finish)

    def _list_output_devices(self):
        """Real (non-virtual) output devices for the picker."""
        out = []
        try:
            import sounddevice as sd
            apis = sd.query_hostapis()
            for i, d in enumerate(sd.query_devices()):
                if d["max_output_channels"] < 1:
                    continue
                low = d["name"].lower()
                if any(b in low for b in ("cable", "vb-audio", "virtual",
                                          "sound mapper", "primary sound driver",
                                          "point")):
                    continue
                api = apis[d["hostapi"]]["name"]
                out.append((i, "%d: %s [%s]" % (i, d["name"], api)))
        except Exception as e:
            print("device list failed:", e, flush=True)
        return out

    def _pick_output_device(self):
        """The real speakers, not a virtual cable (the machine's default is
        VB-Audio CABLE Input, which nobody hears)."""
        try:
            import sounddevice as sd
        except Exception:
            return None
        choice = getattr(self, "device_var", None)
        if choice is not None:
            val = choice.get()
            for idx, lab in getattr(self, "_devices", []):
                if lab == val:
                    return idx
        override = os.environ.get("FH_AUDIO_DEVICE")
        if override:
            try:
                return int(override)
            except ValueError:
                pass
        try:
            apis = sd.query_hostapis()
            best = None
            for i, d in enumerate(sd.query_devices()):
                if d["max_output_channels"] < 1:
                    continue
                low = d["name"].lower()
                if any(b in low for b in ("cable", "vb-audio", "virtual",
                                          "sound mapper", "primary sound driver",
                                          "point")):
                    continue
                api = apis[d["hostapi"]]["name"].lower()
                score = 0
                if "wasapi" in api:
                    score += 3
                if d["max_output_channels"] >= 2:
                    score += 1
                if any(k in low for k in ("speaker", "headphone", "realtek",
                                          "nvidia", "monitor", "display")):
                    score += 2
                if best is None or score > best[0]:
                    best = (score, i, d["name"])
            if best:
                print("audio device:", best[2], flush=True)
                return best[1]
        except Exception as e:
            print("device pick failed:", e, flush=True)
        return None

    def _start_audio(self):
        """Start audio playback. Returns True when the video can be clocked by
        the audio device itself (sample-accurate lips)."""
        try:
            import sounddevice as sd
            import resampy

            dev = self._pick_output_device()
            try:
                info = sd.query_devices(dev) if dev is not None else sd.query_devices(kind="output")
            except Exception:
                info = {"default_samplerate": 48000, "name": "default"}
            out_sr = int(info.get("default_samplerate") or 48000)
            audio = self._audio_16k
            play = audio if out_sr == 16000 else resampy.resample(audio, 16000, out_sr)
            self._play_audio = play

            stream = sd.OutputStream(device=dev, samplerate=out_sr, channels=1,
                                     dtype="float32", blocksize=2048, latency="low")
            stream.start()
            self._stream = stream
            self._t_audio0 = stream.time
            self._audio_seconds = len(play) / float(out_sr)
            self._player = "sounddevice"
            threading.Thread(target=self._feed_audio, daemon=True).start()
            return True
        except Exception as e:
            print("sounddevice playback failed:", e, flush=True)
            self._stream = None

        try:                                   # fallback: whole file through Windows
            import winsound
            winsound.PlaySound(self._tmp_wav,
                               winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            self._player = "winsound"
            return False
        except Exception as e:
            print("winsound playback failed:", e, flush=True)
        try:
            import subprocess
            self._player = subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", self._tmp_wav])
            return False
        except Exception as e:
            print("ffplay failed:", e, flush=True)
        return False

    def _feed_audio(self):
        """Push the audio into the device; write() blocks, pacing it in real time."""
        import numpy as np
        a = getattr(self, "_play_audio", None)
        if a is None:
            return
        block = 2048
        try:
            for i in range(0, len(a), block):
                if self.stop_flag.is_set() or self._stream is None:
                    break
                chunk = np.ascontiguousarray(a[i:i + block], dtype=np.float32).reshape(-1, 1)
                self._stream.write(chunk)
        except Exception as e:
            print("audio feed stopped:", e, flush=True)

    def _stop_audio(self):
        st, self._stream = getattr(self, "_stream", None), None
        if st is not None:
            try:
                st.stop()
            except Exception:
                pass
            try:
                st.close()
            except Exception:
                pass
        try:
            import winsound
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass
        p = self._player
        if hasattr(p, "terminate"):
            try:
                p.terminate()
            except Exception:
                pass
        self._player = None

    def _ui_tick(self):
        """Show frames locked to the audio device's own playback clock, so the
        lips can never drift from the voice. Falls back to a wall clock."""
        try:
            if self.frames and not self.stop_flag.is_set():
                now = time.monotonic()

                if not self.audio_started:
                    need = int(FPS * 0.4)      # ~0.4s of frames buffered first
                    if len(self.frames) >= need or self.stream_ended:
                        self.use_audio_clock = self._start_audio()
                        self.audio_started = True
                        self.t0 = time.monotonic()
                        print("audio engine: %s  (audio clock: %s)" %
                              (self._player, self.use_audio_clock), flush=True)
                    else:
                        return

                pos = None
                if self.use_audio_clock and self._stream is not None:
                    try:
                        pos = (self._stream.time - self._t_audio0) - self._stream.latency
                        if pos > 3600 or pos < -1:
                            pos = None          # nonsense from the device: use the wall clock
                    except Exception:
                        pos = None
                if pos is None:
                    pos = now - self.t0
                pos = max(0.0, pos)

                # sync nudge: positive ms makes the lips wait for the voice
                try:
                    nudge = self.sync_var.get() / 1000.0
                except Exception:
                    nudge = 0.0
                target = int(max(0.0, pos - nudge) * FPS)
                # anything the voice has already passed is dropped, never played fast
                while self.frames and self.frames[0][0] < target:
                    self.frames.popleft()
                    self.dropped += 1

                if self.frames and self.frames[0][0] <= target:
                    idx, jpg = self.frames.popleft()
                    if idx + 1 > self.total:
                        self.total = idx + 1
                    import numpy as np
                    import cv2
                    img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
                    if img is not None:
                        self._show_image(img, composite=True)
                        self.shown += 1
                        self.progress.config(
                            text="Frame %d / %d   audio %+.2fs%s" % (
                                self.shown, self.total, pos - idx / float(FPS),
                                ("   dropped %d" % self.dropped) if self.dropped else ""))
        except Exception as e:
            print("ui tick error:", e)
        finally:
            if self.root.winfo_exists():
                self.root.after(10, self._ui_tick)

    # ---------------------------------------------------------------- stop --
    def stop_stream(self):
        if not self.running and not self.audio_started:
            return
        self.stop_flag.set()
        self.frames.clear()
        self._stop_audio()
        self._set_status("Stopped.", "#ffb300")
        self._cleanup_run()

    def _finish(self):
        self._set_status("Finished - %d frames shown. Click START STREAM to replay." % self.shown,
                         "#4CAF50")
        self.progress.config(text="Finished - %d frames" % self.shown)
        self._cleanup_run()

    def _cleanup_run(self):
        self.running = False
        self._stop_audio()
        def restore():
            if not self.root.winfo_exists():
                return
            self.start_btn.config(state="normal")
            self.connect_btn.config(state="normal")
            self.stop_btn.config(state="normal")
        self.root.after(0, restore)
        if self._tmp_wav and os.path.exists(self._tmp_wav):
            try:
                os.remove(self._tmp_wav)
            except Exception:
                pass
            self._tmp_wav = None

    def _on_close(self):
        self.stop_flag.set()
        self._stop_audio()
        try:
            self.root.destroy()
        except Exception:
            pass


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
