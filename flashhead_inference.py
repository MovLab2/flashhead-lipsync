"""
FlashHead HTTP client — talks to Sapphire's existing FlashHead server.

KEEPS SAPPHIRE UNTOUCHED. We never modify the plugin; we only consume its
HTTP API (port 5017 by default). The server requires X-FlashHead: 1 on all
POST requests.

API used:
  GET  /health            — server status
  POST /face?idle=loop    — raw image bytes (Content-Type: image/*) sets avatar
  POST /speak?take=1      — raw audio bytes for lip-sync rendering
  GET  /stream?audio=0    — pull rendered JPEG frames back (packets:
                            >I header_length | JSON header | audio | JPEGs)
"""
import http.client
import io
import json
import logging
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

logger = logging.getLogger("flashhead_inference")

DEFAULT_SERVER = "http://127.0.0.1:5017"


class FlashHeadClient:
    def __init__(self, server_url=DEFAULT_SERVER, idle="loop"):
        self.server_url = server_url.rstrip("/")
        self.idle = idle
        self.face_set = False

    # -- helpers ---------------------------------------------------------- #
    def _post(self, path, data, content_type, timeout=60):
        """POST raw bytes with X-FlashHead: 1 and Connection: close."""
        url = f"{self.server_url}/{path}"
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": content_type,
                "X-FlashHead": "1",
                "Connection": "close",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            raise RuntimeError("POST /%s failed: HTTP %d %s" % (path, e.code, body[:200]))
        except urllib.error.URLError as e:
            raise RuntimeError("POST /%s failed: %s" % (path, e))

    def _get(self, path, timeout=5):
        url = f"{self.server_url}/{path}"
        req = urllib.request.Request(url, headers={"Connection": "close"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            raise RuntimeError("GET /%s failed: HTTP %d %s" % (path, e.code, body[:200]))
        except urllib.error.URLError as e:
            raise RuntimeError("GET /%s failed: %s" % (path, e))

    # -- server control --------------------------------------------------- #
    def health(self):
        try:
            return json.loads(self._get("health", timeout=5))
        except Exception as e:
            logger.warning("FlashHead server not reachable: %s", e)
        return None

    def wait_for_ready(self, timeout=120):
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            h = self.health()
            if h and h.get("status") == "ready":
                logger.info("FlashHead server ready")
                return True
            if h and h.get("status") == "error":
                raise RuntimeError("FlashHead server error: %s" % h.get("error"))
            time.sleep(2)
        raise TimeoutError("FlashHead server did not become ready within %ds" % timeout)

    # -- face ------------------------------------------------------------- #
    def set_face(self, image_path):
        """Upload the avatar face image as raw image bytes."""
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError("Face image not found: %s" % image_path)
        with open(image_path, "rb") as f:
            image_bytes = f.read()
        body = self._post("face?idle=%s" % self.idle, image_bytes, "image/png", timeout=30)
        logger.info("Face set on server: %s -> %s", image_path, body[:200])
        self.face_set = True

    # -- stream viewer (background) --------------------------------------- #
    class StreamCollector:
        def __init__(self, client, max_wait=300):
            self.client = client
            self.max_wait = max_wait
            self.frames = []      # list of jpeg bytes
            self.audio = b""
            self.error = None
            self.finished = False
            self._thread = None

        def start(self):
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

        def _run(self):
            try:
                from urllib.parse import urlparse
                parsed = urlparse(self.client.server_url)
                host = parsed.hostname or "127.0.0.1"
                port = parsed.port or 5017
                conn = http.client.HTTPConnection(host, port, timeout=self.max_wait)
                conn.request("GET", "/stream?audio=1", headers={"Connection": "close"})
                resp = conn.getresponse()
                buf = io.BytesIO()
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    buf.write(chunk)
                    while True:
                        pkt = self.client._try_extract_packet(buf)
                        if pkt is None:
                            break
                        jpegs, audio = pkt
                        self.frames.extend(jpegs)
                        if audio:
                            self.audio += audio
                resp.close()
                conn.close()
            except Exception as e:
                logger.error("Stream collector error: %s", e)
                self.error = e
            finally:
                self.finished = True

        def wait(self, timeout=None):
            if self._thread:
                self._thread.join(timeout=timeout)
            return self.frames, self.audio, self.error

    def start_stream(self):
        """Open /stream in background (registers viewer, starts render loop)."""
        collector = self.StreamCollector(self)
        collector.start()
        return collector

    @staticmethod
    def _try_extract_packet(buf):
        """Pull one complete packet from buffer.
        Packet format: >I header_length | JSON header | audio bytes | JPEG bytes...
        Returns (jpeg_bytes_list, audio_bytes) or None if incomplete.
        Does NOT modify buf unless a complete packet is extracted."""
        buf.seek(0, 2)
        total = buf.tell()
        buf.seek(0)
        if total < 4:
            return None
        all_data = buf.read()
        # Parse header length
        header_len = int.from_bytes(all_data[:4], "big")
        needed_header = 4 + header_len
        if len(all_data) < needed_header:
            return None  # Not enough data for header, buffer unchanged
        # Parse header JSON
        try:
            header = json.loads(all_data[4:needed_header].decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        audio_len = header.get("audio", 0)
        frame_lens = header.get("frames", [])
        needed = 4 + header_len + audio_len + sum(frame_lens)
        if len(all_data) < needed:
            return None  # Not enough data for full packet, buffer unchanged
        # Extract packet
        audio_bytes = all_data[needed_header:needed_header + audio_len] if audio_len else b""
        jpegs = []
        offset = needed_header + audio_len
        for fl in frame_lens:
            jpegs.append(all_data[offset:offset + fl])
            offset += fl
        # Keep remaining data in buffer
        rest = all_data[needed:]
        buf.seek(0)
        buf.truncate()
        buf.write(rest)
        return jpegs, audio_bytes

    # -- convenience: full audio -> frames -------------------------------- #
    def render_audio_to_frames(self, audio_path, output_dir=None, fps=25, callback=None):
        """Send audio to FlashHead server and collect frames.
        If output_dir is provided, writes frames to disk.
        Calls callback(frame_index, jpg_bytes) for each frame rendered."""
        output_dir = Path(output_dir) if output_dir else None
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)

        collector = self.start_stream()

        # Wait for viewer to register
        viewer_registered = False
        start_wait = time.monotonic()
        while time.monotonic() - start_wait < 15:
            h = self.health()
            if h and h.get("viewers", 0) > 0:
                viewer_registered = True
                break
            time.sleep(0.5)
        if not viewer_registered:
            logger.warning("Viewer did not register on /stream within 15s")

        time.sleep(1.0)

        # Send the audio
        self.speak(audio_path)

        # Wait for stream to collect all frames
        import soundfile as sf
        info = sf.info(str(audio_path))
        audio_duration = info.duration
        wait_time = min(audio_duration * 3.0 + 15.0, 300.0)
        logger.info("Waiting up to %.0fs for stream frames (audio %.1fs)...", wait_time, audio_duration)
        frames, audio, error = collector.wait(timeout=wait_time)

        if error:
            logger.warning("Stream ended with error: %s", error)

        logger.info("Collected %d frames from stream", len(frames))

        # Write frames
        written = 0
        for jpg in frames:
            if output_dir:
                (output_dir / ("lip_frame_%06d.png" % written)).write_bytes(jpg)
            if callback:
                callback(written, jpg)
            written += 1
        logger.info("Wrote %d frames", written)
        return output_dir, frames

    def speak(self, audio_path):
        """Send audio to the server for lip-sync rendering."""
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError("Audio not found: %s" % audio_path)
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()
        body = self._post("speak?take=1", audio_bytes, "application/octet-stream", timeout=60)
        logger.info("Audio sent to server: %s (%d bytes) -> %s",
                    audio_path, len(audio_bytes), body[:200])
        try:
            return json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return {}
