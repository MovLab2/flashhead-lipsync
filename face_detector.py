"""
Head box detection using OpenCV Haar Cascade.

Returns the bounding box (x, y, w, h) of the largest frontal face in a frame.
The box is extended vertically to cover from above the head down to the chest,
so the animated head blends seamlessly into the body.
"""
import cv2
import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("face_detector")


class FaceDetector:
    def __init__(self, cascade_path: str):
        self.cascade_path = Path(cascade_path)
        if not self.cascade_path.exists():
            raise FileNotFoundError(f"Haar cascade not found: {self.cascade_path}")
        self.cascade = cv2.CascadeClassifier(str(self.cascade_path))
        if self.cascade.empty():
            raise RuntimeError(f"Failed to load Haar cascade: {self.cascade_path}")

    def detect_largest_face(
        self, image, scaleFactor: float = 1.1, minNeighbors: int = 5, minSize: Tuple[int, int] = (60, 60)
    ) -> Optional[Tuple[int, int, int, int]]:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        faces = self.cascade.detectMultiScale(
            gray,
            scaleFactor=scaleFactor,
            minNeighbors=minNeighbors,
            minSize=minSize,
            flags=cv2.CASCADE_SCALE_IMAGE,
        )
        if len(faces) == 0:
            return None
        faces = sorted(faces, key=lambda r: r[2] * r[3], reverse=True)
        x, y, fw, fh = faces[0]
        return int(x), int(y), int(fw), int(fh)

    def detect_head_box(
        self,
        image,
        above_head_pad: float = 1.0,   # padding above head (1.0 = 100% of face height, includes hair)
        chest_pad: float = 1.2,         # padding below chin into chest
        side_pad: float = 0.8,          # padding on each side (includes arms/shoulders)
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        Detect the head box extended from above the head down to the chest.
        Returns (x, y, w, h) or None.
        """
        h_img, w_img = image.shape[:2]
        face = self.detect_largest_face(image)
        if face is None:
            return None
        x, y, fw, fh = face

        # Above head: extend up by fraction of face height
        y1 = max(0, y - int(fh * above_head_pad))
        # Below chin: extend down into chest area
        y2 = min(h_img, y + fh + int(fh * chest_pad))
        # Sides: extend by side_pad of face width
        x1 = max(0, x - int(fw * side_pad))
        x2 = min(w_img, x + fw + int(fw * side_pad))

        return x1, y1, x2 - x1, y2 - y1
