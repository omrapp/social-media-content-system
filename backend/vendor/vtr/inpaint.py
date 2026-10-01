"""Frame inpainting for detected text regions (clean-room, cog-free).

Reimplements the removal half of hjunior29/video-text-remover: build one binary
mask over all detected boxes (expanded + dilated) and run a single cv2.inpaint
per frame. Methods map to the settings `algorithm` enum:
    telea  → cv2.INPAINT_TELEA  (Fast Marching)
    ns     → cv2.INPAINT_NS     (Navier-Stokes)
    hybrid → TELEA with a wider 20px context margin (default; best on IG captions)
"""

import cv2
import numpy as np

_HYBRID_MARGIN = 20
_INPAINT_RADIUS = 3


def _flag(method: str):
    return cv2.INPAINT_NS if method == "ns" else cv2.INPAINT_TELEA


def build_mask(shape, boxes, method: str, dilate_px: int) -> np.ndarray:
    """Binary uint8 mask (255 = inpaint) over every box, expanded for hybrid and
    dilated by dilate_px so anti-aliased text edges are fully covered."""
    h, w = shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    margin = _HYBRID_MARGIN if method == "hybrid" else 0
    for x1, y1, x2, y2 in boxes:
        x1 = max(0, int(x1) - margin)
        y1 = max(0, int(y1) - margin)
        x2 = min(w, int(x2) + margin)
        y2 = min(h, int(y2) + margin)
        if x2 > x1 and y2 > y1:
            mask[y1:y2, x1:x2] = 255
    if dilate_px and dilate_px > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * dilate_px + 1, 2 * dilate_px + 1))
        mask = cv2.dilate(mask, k)
    return mask


def inpaint_frame(frame: np.ndarray, boxes, method: str, dilate_px: int) -> np.ndarray:
    """Return the frame with all `boxes` inpainted. No-op when boxes is empty."""
    if not boxes:
        return frame
    mask = build_mask(frame.shape, boxes, method, dilate_px)
    if not mask.any():
        return frame
    return cv2.inpaint(frame, mask, _INPAINT_RADIUS, _flag(method))
