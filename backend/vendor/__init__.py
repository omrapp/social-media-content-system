"""Vendored third-party inference code (kept out of pip deps).

Currently holds `vtr` — the video-text-remover stub (YOLO11 detect + OpenCV
inpaint). The real inference code + weights are installed MANUALLY by the user
via backend/scripts/setup_decaption.py; until then the stub raises ImportError so
the decaption stage degrades to a pass-through.
"""
