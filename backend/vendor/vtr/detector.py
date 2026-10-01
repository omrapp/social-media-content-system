"""ONNX YOLO11 text-region detector (clean-room, cog-free).

Reimplements the detection half of hjunior29/video-text-remover: a single-class
YOLO11s detector exported to ONNX (`converted_best.onnx`) that finds burned-in
caption/watermark text regions in a frame. Standard YOLOv8/v11 letterbox-640
preprocessing + center→corner decode + NMS.

Only onnxruntime + numpy + cv2 are needed — all already in the image.
"""

import logging

import cv2
import numpy as np
import onnxruntime as ort

log = logging.getLogger(__name__)

_INPUT_SIZE = 640
_PAD_VALUE = 114


class OnnxTextDetector:
    def __init__(self, weights_path: str, conf: float = 0.35, iou: float = 0.45):
        self.conf = float(conf)
        self.iou = float(iou)
        # CUDA if a GPU worker ever appears, else CPU (the VPS default). Intersect
        # with what onnxruntime actually has so CPU-only hosts don't warn.
        _available = set(ort.get_available_providers())
        providers = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider")
                     if p in _available] or ["CPUExecutionProvider"]
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
        so.intra_op_num_threads = 2
        self.sess = ort.InferenceSession(weights_path, sess_options=so, providers=providers)
        self.input_name = self.sess.get_inputs()[0].name
        self.output_names = [o.name for o in self.sess.get_outputs()]

    # -- preprocessing -------------------------------------------------------
    def _letterbox(self, frame):
        """Resize keeping aspect ratio into 640x640, pad with 114. Returns the
        blob plus (scale, pad_x, pad_y) so boxes can be projected back."""
        h, w = frame.shape[:2]
        scale = min(_INPUT_SIZE / w, _INPUT_SIZE / h)
        nw, nh = int(round(w * scale)), int(round(h * scale))
        resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
        canvas = np.full((_INPUT_SIZE, _INPUT_SIZE, 3), _PAD_VALUE, dtype=np.uint8)
        pad_x, pad_y = (_INPUT_SIZE - nw) // 2, (_INPUT_SIZE - nh) // 2
        canvas[pad_y:pad_y + nh, pad_x:pad_x + nw] = resized
        rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        blob = np.transpose(rgb, (2, 0, 1))[None, ...]  # (1,3,640,640)
        return blob, scale, pad_x, pad_y

    # -- postprocessing ------------------------------------------------------
    @staticmethod
    def _to_detections(preds):
        """Normalize the raw ONNX output to an (N, 4+C) array of
        [cx, cy, w, h, *class_scores]. Handles both (1, C, N) and (1, N, C)."""
        arr = np.asarray(preds)
        if arr.ndim == 3:
            arr = arr[0]
        # arr is 2-D now; YOLOv8/v11 exports (4+C, N) — transpose to (N, 4+C).
        if arr.shape[0] < arr.shape[1]:
            arr = arr.T
        return arr

    def detect(self, frame, region=None):
        """Return a list of [x1, y1, x2, y2] text boxes in frame pixels.
        `region` = (x1, y1, x2, y2) keeps only boxes overlapping that band."""
        h, w = frame.shape[:2]
        blob, scale, pad_x, pad_y = self._letterbox(frame)
        outputs = self.sess.run(self.output_names, {self.input_name: blob})
        dets = self._to_detections(outputs[0])
        if dets.size == 0:
            return []

        boxes_xywh = dets[:, :4]
        scores = dets[:, 4:]
        conf = scores.max(axis=1) if scores.shape[1] else np.zeros(len(dets))
        keep = conf >= self.conf
        if not np.any(keep):
            return []
        boxes_xywh, conf = boxes_xywh[keep], conf[keep]

        # center-format (letterbox space) → corner-format → original frame space.
        cx, cy, bw, bh = boxes_xywh.T
        x1 = (cx - bw / 2 - pad_x) / scale
        y1 = (cy - bh / 2 - pad_y) / scale
        x2 = (cx + bw / 2 - pad_x) / scale
        y2 = (cy + bh / 2 - pad_y) / scale
        corners = np.stack([x1, y1, x2, y2], axis=1)
        corners[:, 0::2] = corners[:, 0::2].clip(0, w - 1)
        corners[:, 1::2] = corners[:, 1::2].clip(0, h - 1)

        # NMS (cv2 wants x,y,w,h).
        rects = [[int(a), int(b), int(c - a), int(d - b)] for a, b, c, d in corners]
        idxs = cv2.dnn.NMSBoxes(rects, conf.tolist(), self.conf, self.iou)
        if idxs is None or len(idxs) == 0:
            return []
        idxs = np.array(idxs).flatten()

        out = []
        for i in idxs:
            x1i, y1i, x2i, y2i = (int(v) for v in corners[i])
            if x2i <= x1i or y2i <= y1i:
                continue
            if region and not _overlaps((x1i, y1i, x2i, y2i), region):
                continue
            out.append([x1i, y1i, x2i, y2i])
        return out


def _overlaps(a, b) -> bool:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return not (ax2 < bx1 or ax1 > bx2 or ay2 < by1 or ay1 > by2)
