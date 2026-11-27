"""Play the probe through the real app and measure the A/V offset.

Each burst of speech must open the mouth. We correlate the measured mouth
motion with the known burst schedule; the best-matching lag IS the offset
between what is shown and what is heard.
"""
import sys
import tkinter as tk

import cv2
import numpy as np

sys.path.insert(0, r"C:\AvatarProject\lip_sync_service")
from realtime_app import App, FPS

AUDIO = r"C:\AvatarProject\lip_sync_service\probe.wav"
AVATAR = r"C:\AvatarProject\avatar_grid\Jinx.png"

# burst schedule: 0.25s speech, 0.75s silence, repeated 8x
BURST, GAP, N = 0.25, 0.75, 8
period = BURST + GAP
n_frames = int(round(N * period * FPS))
square = np.array([1.0 if (i / FPS) % period < BURST else 0.0 for i in range(n_frames)])

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
        elif not state["done"] and app.running is False and app.shown > 30:
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
    mz = (m - m.mean()) / max(1e-9, m.std())

    print("\nframes: %d  (%.1fs)" % (len(idx), len(idx) / float(FPS)), flush=True)
    print("mouth motion: mean %.1f  max %.1f" % (m.mean(), m.max()), flush=True)

    best = None
    for lag_ms in range(-600, 601, 5):
        j = np.round(idx + lag_ms / (1000.0 / FPS)).astype(int)
        ok = (j >= 0) & (j < len(square))
        if ok.sum() < 40:
            continue
        c = float(np.corrcoef(mz[ok], square[j[ok]])[0, 1])
        if best is None or c > best[1]:
            best = (lag_ms, c)

    print("BEST LAG: %+d ms  (corr %.3f)" % best, flush=True)
    print("positive = lips early, negative = lips late", flush=True)

    # per-burst view: when does the mouth peak inside each burst window?
    print("\nper burst (mouth peak vs burst start):", flush=True)
    peaks = []
    for k in range(N):
        t0 = k * period
        sel = (idx / float(FPS) >= t0 - 0.1) & (idx / float(FPS) < t0 + 0.55)
        if not sel.any():
            continue
        sub = idx[sel]
        peak = sub[int(np.argmax(m[sel]))] / float(FPS) - t0
        peaks.append(peak)
        print("  burst %d: peak at %+.2fs" % (k + 1, peak), flush=True)
    if peaks:
        print("median peak: %+.3fs" % float(np.median(peaks)), flush=True)
    root.destroy()


root.after(400, tick)
root.mainloop()
