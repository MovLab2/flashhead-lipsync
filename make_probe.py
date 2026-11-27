"""Build a probe audio: 6 loud speech bursts separated by silence.

The mouth has to open on every burst, so the mouth-motion curve becomes a
square wave we can align against the audio to the millisecond.
"""
import numpy as np
import soundfile as sf
import resampy

SRC = r"C:\Users\mosas.ASUS-GAMING\Downloads\lauren-crazy.mp3"
OUT = r"C:\AvatarProject\lip_sync_service\probe.wav"

a, sr = sf.read(SRC, always_2d=False)
if a.ndim > 1:
    a = a.mean(axis=1)
a = np.asarray(a, np.float32)
if sr != 16000:
    a = resampy.resample(a, sr, 16000)

# loudest 0.25s window
win = 16000 * 25 // 100
best = max(range(0, len(a) - win, 400), key=lambda i: np.sqrt(np.mean(a[i:i + win] ** 2)))
burst = a[best:best + win]
burst = burst / max(1e-6, np.abs(burst).max()) * 0.9

gap = np.zeros(16000 * 75 // 100, np.float32)
parts = []
for _ in range(8):
    parts.append(burst)
    parts.append(gap)
out = np.concatenate(parts)
sf.write(OUT, out, 16000, subtype="PCM_16")
print("probe: %.2fs, 8 bursts of %.2fs starting at %s"
      % (len(out) / 16000.0, win / 16000.0,
         ", ".join("%.1f" % (i * 1.0) for i in range(8))))
