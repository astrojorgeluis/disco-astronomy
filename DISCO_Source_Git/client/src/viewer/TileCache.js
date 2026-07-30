/** LRU tile cache with AbortController and viewport-priority fetches. */

const TILE = 256;

export class TileCache {
  constructor({ maxTiles = 96, fetchTile } = {}) {
    this.maxTiles = maxTiles;
    this.fetchTile = fetchTile; // async (z, tx, ty, signal) => Float32Array
    this._map = new Map(); // key -> { data, tex?, last }
    this._inflight = new Map();
    this._epoch = 0;
  }

  key(z, tx, ty) {
    return `${z}/${tx}/${ty}`;
  }

  clear() {
    this._epoch += 1;
    for (const [, ctrl] of this._inflight) ctrl.abort();
    this._inflight.clear();
    this._map.clear();
  }

  get(z, tx, ty) {
    const k = this.key(z, tx, ty);
    const e = this._map.get(k);
    if (!e) return null;
    e.last = performance.now();
    return e.data;
  }

  async ensure(z, tx, ty) {
    const k = this.key(z, tx, ty);
    if (this._map.has(k)) {
      const e = this._map.get(k);
      e.last = performance.now();
      return e.data;
    }
    if (this._inflight.has(k)) return this._inflight.get(k).promise;

    const ctrl = new AbortController();
    const epoch = this._epoch;
    const promise = (async () => {
      try {
        const data = await this.fetchTile(z, tx, ty, ctrl.signal);
        if (epoch !== this._epoch) return null;
        this._map.set(k, { data, last: performance.now() });
        this._evict();
        return data;
      } catch (e) {
        if (e?.name === 'AbortError') return null;
        throw e;
      } finally {
        this._inflight.delete(k);
      }
    })();
    this._inflight.set(k, { abort: () => ctrl.abort(), promise, ctrl });
    return promise;
  }

  /**
   * Request tiles covering the visible image rect at level z.
   * imgW/imgH are full-resolution dimensions; level z has size / 2^z.
   */
  async requestVisible({ z, imgW, imgH, x0, y0, x1, y1, onTile }) {
    const scale = 2 ** z;
    const lw = Math.ceil(imgW / scale);
    const lh = Math.ceil(imgH / scale);
    const ntx = Math.ceil(lw / TILE);
    const nty = Math.ceil(lh / TILE);
    const tx0 = Math.max(0, Math.floor((x0 / scale) / TILE));
    const ty0 = Math.max(0, Math.floor((y0 / scale) / TILE));
    const tx1 = Math.min(ntx - 1, Math.floor((x1 / scale) / TILE));
    const ty1 = Math.min(nty - 1, Math.floor((y1 / scale) / TILE));

    const jobs = [];
    for (let ty = ty0; ty <= ty1; ty++) {
      for (let tx = tx0; tx <= tx1; tx++) {
        jobs.push(
          this.ensure(z, tx, ty).then((data) => {
            if (data && onTile) onTile(z, tx, ty, data);
          }).catch(() => {}),
        );
      }
    }
    await Promise.all(jobs);
  }

  _evict() {
    while (this._map.size > this.maxTiles) {
      let oldestKey = null;
      let oldest = Infinity;
      for (const [k, v] of this._map) {
        if (v.last < oldest) {
          oldest = v.last;
          oldestKey = k;
        }
      }
      if (oldestKey != null) this._map.delete(oldestKey);
      else break;
    }
  }
}

export const TILE_SIZE = TILE;
