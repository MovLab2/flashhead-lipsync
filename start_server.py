"""
Start the FlashHead server standalone (from Sapphire's plugin, unmodified)
and wait until it's ready on http://127.0.0.1:5017.

Usage:
    python start_server.py
"""
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("start_server")

SERVER_URL = "http://127.0.0.1:5017"
SAPPHIRE_ROOT = Path("C:/Users/mosas.ASUS-GAMING/sapphire")
PLUGIN_DIR = SAPPHIRE_ROOT / "user" / "plugins" / "flashhead"
ENV_PYTHON = Path(
    "C:/Users/mosas.ASUS-GAMING/miniconda3/envs/sapphire-plugin-flashhead/python.exe"
)


def health():
    try:
        with urllib.request.urlopen(SERVER_URL + "/health", timeout=5) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def main():
    # Already ready?
    h = health()
    if h and h.get("status") == "ready":
        log.info("FlashHead server already ready at %s", SERVER_URL)
        return 0

    server_py = PLUGIN_DIR / "server.py"
    if not server_py.exists():
        log.error("server.py not found: %s", server_py)
        return 1

    log.info("Starting FlashHead server from %s", PLUGIN_DIR)
    env = os.environ.copy()
    env["SAPPHIRE_ROOT"] = str(SAPPHIRE_ROOT)
    env["SAPPHIRE_SERVICE_PORT"] = "5017"
    env["PYTHONUTF8"] = "1"

    # Stream server output to a log file so we can watch progress
    log_file = Path("C:/AvatarProject/lip_sync_service/output/flashhead_server.log")
    log_file.parent.mkdir(parents=True, exist_ok=True)
    lf = open(log_file, "w", encoding="utf-8", buffering=1)

    proc = subprocess.Popen(
        [str(ENV_PYTHON), str(server_py)],
        cwd=str(PLUGIN_DIR),
        env=env,
        stdout=lf,
        stderr=subprocess.STDOUT,
    )
    log.info("FlashHead server PID %d started. Log: %s", proc.pid, log_file)

    start = time.monotonic()
    while time.monotonic() - start < 600:  # 10 min max
        if proc.poll() is not None:
            lf.close()
            log.error("FlashHead server exited early (code %d)", proc.returncode)
            return 1
        h = health()
        if h:
            status = h.get("status", "?")
            progress = h.get("progress")
            if status == "ready":
                log.info("FlashHead server READY: %s", h)
                lf.close()
                return 0
            if status == "error":
                log.error("FlashHead server error: %s", h.get("error"))
                lf.close()
                return 1
            pg = ""
            if progress:
                pg = " %.1f/%.1f GB" % (
                    progress.get("done", 0) / 1e9,
                    progress.get("total", 1) / 1e9,
                )
            log.info("Server status: %s%s", status, pg)
        else:
            log.info("Server starting...")
        time.sleep(5)

    log.error("Timed out waiting for server to become ready")
    lf.close()
    return 1


if __name__ == "__main__":
    sys.exit(main())
