"""End-to-end test: build the real app, connect, stream, screenshot the live view."""
import os
import sys
import time
import tkinter as tk

sys.path.insert(0, r"C:\AvatarProject\lip_sync_service")
from realtime_app import App

AUDIO = r"C:\Users\mosas.ASUS-GAMING\Downloads\lauren-crazy.mp3"
AVATAR = r"C:\AvatarProject\avatar_grid\Jinx.png"
LOG = r"C:\AvatarProject\lip_sync_service\e2e_log.txt"
SHOT = r"C:\AvatarProject\lip_sync_service\live_shot.png"

log = open(LOG, "w", buffering=1)


def p(*a):
    print(*a, file=log, flush=True)


root = tk.Tk()
app = App(root)
app.audio_path = AUDIO
app.audio_var.set(AUDIO)
app.avatar_path = AVATAR
app.avatar_var.set(AVATAR)
app._show_preview(AVATAR)

state = {"connect_called": False, "start_called": False, "shot": False, "t_start": None}


def finish(msg):
    p(msg)
    try:
        app.stop_flag.set()
        app._stop_audio()
    except Exception:
        pass
    root.after(200, root.destroy)


def tick():
    try:
        if not state["connect_called"]:
            state["connect_called"] = True
            p("calling connect_server()")
            app.connect_server()
            state["t_connect"] = time.monotonic()

        if app.connected and not state["start_called"]:
            state["start_called"] = True
            p("connected -> calling start_stream()")
            app.start_stream()
            state["t_start"] = time.monotonic()

        if app.running and app.shown >= 30 and not state["shot"]:
            state["shot"] = True
            p("frames shown=%d total=%d audio_started=%s" %
              (app.shown, app.total, app.audio_started))
            root.lift()
            root.attributes("-topmost", True)
            root.update()
            time.sleep(0.2)
            from PIL import ImageGrab
            x, y = root.winfo_rootx(), root.winfo_rooty()
            w, h = root.winfo_width(), root.winfo_height()
            ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(SHOT)
            p("screenshot saved")
            root.after(1500, lambda: finish(
                "DONE shown=%d total=%d elapsed=%.1fs" %
                (app.shown, app.total, time.monotonic() - state["t_start"])))

        if not state["shot"] and state.get("t_start") and time.monotonic() - state["t_start"] > 45:
            finish("TIMEOUT shown=%d total=%d running=%s" % (app.shown, app.total, app.running))
            return
    except Exception as e:
        import traceback
        p("TICK ERROR: %r" % (e,))
        traceback.print_exc(file=log)
    if root.winfo_exists():
        root.after(200, tick)


root.after(500, tick)
root.after(70000, lambda: finish("HARD TIMEOUT"))
root.mainloop()
log.close()
