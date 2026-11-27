"""Measure lip-sync objectively.

Every displayed frame's mouth region is captured (512x512 head render, mouth at
y 0.48-0.66, x 0.38-0.64). Mouth motion is the deviation from the clip's median
mouth, which tracks how far the lips are apart. Correlating that with the
audio's loudness curve gives the real audio/video offset.

  lag > 0  ->  mouth moves BEFORE the sound (lips early)
  lag < 0  ->  mouth moves AFTER the sound (lips late)
"""
import sys
import tkinter as tk

import cv2
import numpy as np
import soundfile as sf
import resampy

sys.path.insert(0, r"C:\AvatarProject\lip_sync_service")
from realtime_app import App, FPS

AUDIO = r"C:\Users\mosas.ASUS-GAMING\Downloads\lauren-crazy.mp3"
AVATAR = r"C:\AvatarProject\avatar_grid\Jinx.png"

# ---- audio envelope, one value per video frame ---------------------------
a, sr = sf.read(AUDIO, always_2d=False)
if a.ndim > 1:
    a = a.mean(axis=1)
a = np.asarray(a, np.float32)
if sr != 16000:
    a = resampy.resample(a, sr, 16000)
hop = 16000 // FPS
env = np.array([np.sqrt(np.mean(a[i:i + hop] ** 2)) for i in range(0, len(a) - hop, hop)])
env = (env - env.min()) / max(1e-9, env.max() - env.min())
print("audio: %.2fs, %d frame envelopes" % (len(a) / 16000.0, len(env)), flush=True)

root = tk.Tk()
app = App(root)
app.audio_path = AUDIO
app.audio_var.set(AUDIO)
app.avatar_path = AVATAR
app.avatar_var.set(AVATAR)
app._show_preview(AVATAR)

rois = {}
_orig = app._show_image


def show(img_bgr, composite=False):
    if composite and app._head_box is not None:
        try:
            h, w = img_bgr.shape[:2]
            roi = img_bgr[int(h * 0.48):int(h * 0.66), int(w * 0.38):int(w * 0.64)]
            g = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            rois[app.shown] = cv2.resize(g, (48, 24)).astype(np.float32)
        except Exception as e:
            print("metric failed:", e, flush=True)
    _orig(img_bgr, composite=composite)


app._show_image = show

state = {"connect": False, "start": False, "done": False}


def tick():
    try:
        if not state["connect"]:
            state["connect"] = True
            app.connect_server()
        elif app.connected and not state["start"]:
            state["start"] = True
            app.start_stream()
        elif not state["done"] and app.running is False and app.shown > 50:
            state["done"] = True
            report()
    except Exception as e:
        print("tick error:", e, flush=True)
    if not state["done"]:
        root.after(200, tick)


def report():
    idx = np.array(sorted(rois))
    stack = np.stack([rois[i] for i in idx])
    base = np.median(stack, axis=0)
    m = np.abs(stack - base).mean(axis=(1, 2))
    m = (m - m.mean()) / max(1e-9, m.std())

    best = None
    for lag_ms in range(-700, 701, 10):
        j = np.round(idx + lag_ms / (1000.0 / FPS)).astype(int)
        ok = (j >= 0) & (j < len(env))
        if ok.sum() < 60:
            continue
        c = float(np.corrcoef(m[ok], env[j[ok]])[0, 1])
        if best is None or c > best[1]:
            best = (lag_ms, c, ok.sum())

    # how much the mouth actually moves (0-255 grey levels)
    print("\nframes measured: %d" % len(idx), flush=True)
    print("mouth motion: mean %.1f  p90 %.1f  max %.1f grey levels" %
          (np.abs(stack - base).mean(), np.percentile(np.abs(stack - base).mean(axis=(1, 2)), 90),
           np.abs(stack - base).mean(axis=(1, 2)).max()), flush=True)
    print("BEST LAG: %+d ms  (correlation %.3f over %d frames)" % best, flush=True)
    print("positive = lips early, negative = lips late", flush=True)

    # compare with the finished video (same take) - this is the real proof
    try:
        v = np.load(r"C:\AvatarProject\lip_sync_service\_vid_motion.npy")
        vz = (v - v.mean()) / max(1e-9, v.std())
        bestv = None
        for lag in range(-1000, 1001, 5):
            j = np.round(idx + lag / (1000.0 / FPS)).astype(int)
            ok = (j >= 0) & (j < len(vz))
            if ok.sum() < 100:
                continue
            c = float(np.corrcoef(m[ok], vz[j[ok]])[0, 1])
            if bestv is None or c > bestv[1]:
                bestv = (lag, c, ok.sum())
        print("LIVE vs VIDEO mouth curve: best lag %+d ms, corr %.3f (%d frames)"
              % bestv, flush=True)
        j0 = idx[idx < len(vz)]
        c0 = float(np.corrcoef(m[:len(j0)], vz[j0])[0, 1])
        print("same-frame corr (0 ms): %.3f" % c0, flush=True)
    except Exception as e:
        print("video compare skipped:", e, flush=True)

    root.destroy()


root.after(400, tick)
root.mainloop()
