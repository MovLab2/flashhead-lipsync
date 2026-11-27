"""
Trim leading/trailing idle frames from FlashHead output so lip movement
aligns with audio start/end.

FlashHead renders a few seconds of idle before speech begins (render lead)
and idle after speech ends. We detect lip motion by comparing each frame
to the reference head image, then keep only frames where the mouth region
is actively moving.
"""
import cv2
import logging
import numpy as np
from pathlib import Path

logger = logging.getLogger("trim")


def _mouth_region(frame, box_frac=(0.25, 0.65, 0.40, 0.80)):
    """
    Extract the mouth region from a 512x512 frame.
    box_frac: (y1, y2, x1, x2) as fractions of height/width.
    Returns grayscale mouth crop, or None if frame is too small.
    """
    h, w = frame.shape[:2]
    y1 = int(h * box_frac[0])
    y2 = int(h * box_frac[1])
    x1 = int(w * box_frac[2])
    x2 = int(w * box_frac[3])
    if y2 <= y1 or x2 <= x1:
        return None
    mouth = frame[y1:y2, x1:x2]
    gray = cv2.cvtColor(mouth, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)
    return gray.astype(np.float32)


def detect_speech_frames(frames_dir, ref_image_path, fps=25,
                         motion_threshold=8.0, min_speech_frames=5,
                         pad_frames=3):
    """
    Analyze frames and return (start_idx, end_idx) of actual speech animation.

    Args:
        frames_dir: directory with lip_frame_%06d.png
        ref_image_path: path to the static reference head (512x512)
        fps: frame rate
        motion_threshold: mean abs diff threshold for mouth region (higher = more motion needed)
        min_speech_frames: minimum consecutive frames with motion to count as speech
        pad_frames: frames of padding to add before/after detected speech

    Returns:
        (start_idx, end_idx) inclusive indices into the sorted frame list.
        Returns (0, len-1) if no speech detected (keep all frames).
    """
    frames_dir = Path(frames_dir)
    ref = cv2.imread(str(ref_image_path))
    if ref is None:
        logger.warning("Cannot read reference image, keeping all frames")
        return 0, len(list(frames_dir.glob("*.png"))) - 1

    ref_mouth = _mouth_region(ref)
    if ref_mouth is None:
        return 0, len(list(frames_dir.glob("*.png"))) - 1

    frames = sorted(frames_dir.glob("*.png"))
    if not frames:
        return 0, -1

    n = len(frames)
    motion = np.zeros(n, np.float32)

    for i, fp in enumerate(frames):
        frame = cv2.imread(str(fp))
        if frame is None:
            continue
        mouth = _mouth_region(frame)
        if mouth is None:
            continue
        diff = np.abs(mouth - ref_mouth).mean()
        motion[i] = diff

    # Find frames with significant mouth motion
    active = motion > motion_threshold

    # Smooth: require min_speech_frames consecutive active frames
    speech_start = None
    speech_end = None
    i = 0
    while i < n:
        if active[i]:
            # Count consecutive active frames
            j = i
            while j < n and active[j]:
                j += 1
            run_len = j - i
            if run_len >= min_speech_frames:
                speech_start = i
                speech_end = j - 1
                # Keep going to find the last run
                i = j
            else:
                i = j
        else:
            i += 1

    if speech_start is None:
        logger.warning("No speech motion detected, keeping all %d frames", n)
        return 0, n - 1

    # Add padding
    start_idx = max(0, speech_start - pad_frames)
    end_idx = min(n - 1, speech_end + pad_frames)

    logger.info("Speech detected: frames %d-%d of %d (motion threshold=%.1f)",
                start_idx, end_idx, n, motion_threshold)
    logger.info("Max mouth motion: %.1f at frame %d",
                motion.max(), int(motion.argmax()))

    return start_idx, end_idx


def trim_frames(frames_dir, start_idx, end_idx, output_dir=None):
    """
    Keep only frames[start_idx:end_idx+1], renumbered from 0.
    Returns output_dir.
    """
    frames_dir = Path(frames_dir)
    if output_dir is None:
        output_dir = frames_dir
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    frames = sorted(frames_dir.glob("*.png"))
    if start_idx < 0 or end_idx >= len(frames) or start_idx > end_idx:
        logger.warning("Invalid trim range %d-%d for %d frames, keeping all",
                       start_idx, end_idx, len(frames))
        start_idx, end_idx = 0, len(frames) - 1

    count = 0
    for new_i, old_i in enumerate(range(start_idx, end_idx + 1)):
        src = frames[old_i]
        dst = output_dir / ("lip_frame_%06d.png" % new_i)
        dst.write_bytes(src.read_bytes())
        count += 1

    logger.info("Trimmed %d -> %d frames (kept %d-%d)",
                len(frames), count, start_idx, end_idx)
    return output_dir
