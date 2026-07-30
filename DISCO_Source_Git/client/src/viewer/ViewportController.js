/** Viewport transform controller — pan/zoom with multi-listener support. */

export class ViewportController {
  constructor({ onChange } = {}) {
    this.x = 0;
    this.y = 0;
    this.k = 1;
    this._listeners = new Set();
    if (onChange) this._listeners.add(onChange);
    this._raf = 0;
  }

  get transform() {
    return { x: this.x, y: this.y, k: this.k };
  }

  /** Register a listener; returns unsubscribe. */
  subscribe(fn) {
    this._listeners.add(fn);
    return () => this._listeners.delete(fn);
  }

  /** @deprecated prefer subscribe() — kept for single-handler assignment */
  set _onChange(fn) {
    this._legacy = typeof fn === 'function' ? fn : null;
  }

  get _onChange() {
    return this._legacy || (() => {});
  }

  set(t) {
    this.x = t.x;
    this.y = t.y;
    this.k = t.k;
    this._notify();
  }

  fit(imgW, imgH, viewW, viewH, margin = 0.92) {
    if (!imgW || !imgH || !viewW || !viewH) return;
    const k = Math.min(viewW / imgW, viewH / imgH) * margin;
    this.k = k;
    this.x = (viewW - imgW * k) / 2;
    this.y = (viewH - imgH * k) / 2;
    this._notify();
  }

  /** Keep the image point under the view center fixed when the container resizes. */
  reanchor(oldW, oldH, newW, newH) {
    if (!oldW || !oldH || !newW || !newH) return;
    const ix = (oldW / 2 - this.x) / this.k;
    const iy = (oldH / 2 - this.y) / this.k;
    this.x = newW / 2 - ix * this.k;
    this.y = newH / 2 - iy * this.k;
    this._notify();
  }

  zoomAt(screenX, screenY, factor) {
    const old = this.k;
    const next = Math.max(0.01, Math.min(64, old * factor));
    const mx = (screenX - this.x) / old;
    const my = (screenY - this.y) / old;
    this.k = next;
    this.x = screenX - mx * next;
    this.y = screenY - my * next;
    this._notify();
  }

  pan(dx, dy) {
    this.x += dx;
    this.y += dy;
    this._notify();
  }

  screenToImage(sx, sy) {
    return { x: (sx - this.x) / this.k, y: (sy - this.y) / this.k };
  }

  imageToScreen(ix, iy) {
    return { x: ix * this.k + this.x, y: iy * this.k + this.y };
  }

  _notify() {
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => {
      this._raf = 0;
      const t = this.transform;
      for (const fn of this._listeners) {
        try { fn(t); } catch { /* ignore */ }
      }
      if (this._legacy) {
        try { this._legacy(t); } catch { /* ignore */ }
      }
    });
  }
}
