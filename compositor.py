"""
Composite an animated head (FlashHead output) back onto the original frame.

FlashHead produces a talking-head video. We paste it back into the detected
head box of the original avatar frame so the rest of the body/background
stays intact. The bottom edge is feather-blended so there's no hard line
where the head meets the chest/shoulders.
"""
import cv2
import logging
import numpy as np
from typing import Tuple

logger = logging.getLogger("compositor")


def _feather_mask(height, width, blend_frac=0.18):
    """
    Build a soft alpha mask for blending the head into the body.

    The mask is 1.0 (full head) across most of the box, fading to 0.0 at the
    bottom edge over `blend_frac` of the box height. This removes the hard
    seam at the neck/chest boundary.
    """
    mask = np.ones((height, width), np.float32)
    if blend_frac <= 0:
        return mask
    blend_px = max(1, int(height * blend_frac))
    # Gradient from 1.0 down to 0.0 in the bottom blend_px rows
    ramp = np.linspace(1.0, 0.0, blend_px, dtype=np.float32)
    mask[height - blend_px:height, :] = ramp[:, np.newaxis]
    return mask


def composite_head(base_frame, head_frame, box: Tuple[int, int, int, int],
                   blend_frac: float = 0.18):
    """
    Paste head_frame into base_frame at box (x, y, w, h).

    The bottom edge of the head is feather-blended into the base frame so the
    neck/chest boundary is seamless. Returns the composited frame.
    """
    x, y, w, h = box
    base = base_frame.copy()

    # Resize head to match the box dimensions
    head_resized = cv2.resize(head_frame, (w, h), interpolation=cv2.INTER_AREA)

    # Build feather mask (1.0 = full head, 0.0 = base frame at bottom edge)
    mask = _feather_mask(h, w, blend_frac=blend_frac)
    mask3 = np.stack([mask, mask, mask], axis=2)

    # Alpha blend: base * (1 - mask) + head * mask
    head_region = base[y : y + h, x : x + w].astype(np.float32)
    blended = head_resized.astype(np.float32) * mask3 + head_region * (1.0 - mask3)
    base[y : y + h, x : x + w] = blended.astype(np.uint8)
    return base
