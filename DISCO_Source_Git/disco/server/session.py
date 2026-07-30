"""Multi-image session store with TTL cleanup and pyramid cache."""
from __future__ import annotations

import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

UPLOAD_DIR = os.path.join(os.getcwd(), ".disco_uploads")
SESSION_TTL_SEC = 60 * 60 * 6  # 6 hours
MAX_IMAGES_IN_MEMORY = 4


@dataclass
class ImageEntry:
    id: str
    filename: str
    path: str
    data: np.ndarray
    header: Any
    pixel_scale: float
    results: dict = field(default_factory=dict)
    extents: dict = field(default_factory=dict)
    profile_data: Optional[dict] = None
    geometry: Optional[dict] = None
    fit: Optional[dict] = None
    params: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    # Lazy image pyramid: {product: [level0, level1, ...]} level 0 = full res
    pyramid: Optional[dict] = field(default=None, repr=False)
    pyramid_stats: Optional[dict] = field(default=None, repr=False)
    _pyramid_lock: Any = field(default=None, repr=False)


def _release_entry(img: ImageEntry):
    """Drop heavy arrays so GC can reclaim memory."""
    img.data = np.empty((0, 0), dtype=np.float32)
    img.results = {}
    img.extents = {}
    img.profile_data = None
    img.geometry = None
    img.fit = None
    img.pyramid = None
    img.pyramid_stats = None


class SessionStore:
    def __init__(self, upload_dir: str = UPLOAD_DIR, ttl: float = SESSION_TTL_SEC):
        self.upload_dir = upload_dir
        self.ttl = ttl
        self.images: dict[str, ImageEntry] = {}
        self.active_id: Optional[str] = None
        self.history: list[dict] = []
        self.regions: list[dict] = []
        self.layout: Any = None
        self.viz: dict = {}
        self._lock = threading.RLock()
        os.makedirs(self.upload_dir, exist_ok=True)

    def touch(self):
        pass

    def active(self) -> Optional[ImageEntry]:
        with self._lock:
            if self.active_id and self.active_id in self.images:
                return self.images[self.active_id]
            return None

    def list_images(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "id": img.id,
                    "filename": img.filename,
                    "shape": list(img.data.shape) if img.data is not None else [0, 0],
                    "pixel_scale": img.pixel_scale,
                    "active": img.id == self.active_id,
                }
                for img in self.images.values()
            ]

    def add_image(self, entry: ImageEntry, set_active: bool = True) -> ImageEntry:
        with self._lock:
            entry._pyramid_lock = threading.RLock()
            self.images[entry.id] = entry
            if set_active:
                self.active_id = entry.id
            # Evict oldest non-active images if over limit
            while len(self.images) > MAX_IMAGES_IN_MEMORY:
                victims = [
                    i for i, img in self.images.items()
                    if i != self.active_id
                ]
                if not victims:
                    break
                oldest = min(victims, key=lambda i: self.images[i].created_at)
                self._drop_image(oldest, unlink=False)
            self.log("load_image", {"id": entry.id, "filename": entry.filename})
            return entry

    def set_active(self, image_id: str) -> ImageEntry:
        with self._lock:
            if image_id not in self.images:
                raise KeyError(image_id)
            self.active_id = image_id
            self.log("set_active", {"id": image_id})
            return self.images[image_id]

    def _drop_image(self, image_id: str, unlink: bool = True):
        img = self.images.pop(image_id, None)
        if not img:
            return
        if unlink and os.path.isfile(img.path):
            try:
                os.unlink(img.path)
            except OSError:
                pass
        _release_entry(img)
        if self.active_id == image_id:
            self.active_id = next(iter(self.images), None)

    def remove_image(self, image_id: str):
        with self._lock:
            self._drop_image(image_id, unlink=True)
            self.log("remove_image", {"id": image_id})

    def clear(self, wipe_disk: bool = True):
        with self._lock:
            for img in list(self.images.values()):
                _release_entry(img)
            self.images.clear()
            self.active_id = None
            self.history.clear()
            self.regions.clear()
            self.layout = None
            self.viz = {}
            if wipe_disk and os.path.exists(self.upload_dir):
                for name in os.listdir(self.upload_dir):
                    path = os.path.join(self.upload_dir, name)
                    try:
                        if os.path.isfile(path) or os.path.islink(path):
                            os.unlink(path)
                        elif os.path.isdir(path):
                            shutil.rmtree(path)
                    except OSError:
                        pass
            else:
                os.makedirs(self.upload_dir, exist_ok=True)

    def log(self, action: str, payload: Optional[dict] = None):
        self.history.append({
            "ts": time.time(),
            "action": action,
            "payload": payload or {},
        })
        if len(self.history) > 2000:
            self.history = self.history[-1000:]

    def export_state(self) -> dict:
        with self._lock:
            return {
                "active_id": self.active_id,
                "images": [
                    {
                        "id": img.id,
                        "filename": img.filename,
                        "path": os.path.basename(img.path),
                        "params": img.params,
                        "pixel_scale": img.pixel_scale,
                    }
                    for img in self.images.values()
                ],
                "regions": self.regions,
                "layout": self.layout,
                "viz": self.viz,
                "history": self.history[-200:],
                "timestamp": time.time(),
            }

    def purge_expired(self):
        now = time.time()
        with self._lock:
            expired = [i for i, img in self.images.items() if now - img.created_at > self.ttl]
            for i in expired:
                self.remove_image(i)


def new_image_id() -> str:
    return uuid.uuid4().hex[:12]


# Global store used by the app factory
store = SessionStore()
