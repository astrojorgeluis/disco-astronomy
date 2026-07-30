/** Typed-ish API client for the DISCO FastAPI backend. */

export class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(path, options);
  } catch (err) {
    throw new ApiError(`Network error: ${path}`, 0, String(err?.message || err));
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new ApiError(`Request failed: ${path}`, res.status, detail);
  }
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) return res.json();
  return res;
}

function parseRasterHeaders(res) {
  return {
    width: Number(res.headers.get('X-DISCO-Width')),
    height: Number(res.headers.get('X-DISCO-Height')),
    min: Number(res.headers.get('X-DISCO-Min')),
    max: Number(res.headers.get('X-DISCO-Max')),
    p995: Number(res.headers.get('X-DISCO-P995')),
    p999: Number(res.headers.get('X-DISCO-P999')),
    pixelScale: Number(res.headers.get('X-DISCO-PixelScale')),
    decimation: Number(res.headers.get('X-DISCO-Decimation') || 1),
    fullWidth: Number(res.headers.get('X-DISCO-FullWidth') || res.headers.get('X-DISCO-Width')),
    fullHeight: Number(res.headers.get('X-DISCO-FullHeight') || res.headers.get('X-DISCO-Height')),
    tileSize: Number(res.headers.get('X-DISCO-TileSize') || 256),
    level: Number(res.headers.get('X-DISCO-Level') || 0),
  };
}

export const api = {
  upload: async (file) => {
    const fd = new FormData();
    fd.append('file', file);
    return request('/api/upload', { method: 'POST', body: fd });
  },
  listImages: () => request('/api/images'),
  setActive: (image_id) =>
    request('/api/images/active', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_id }),
    }),
  removeImage: (id) => request(`/api/images/${id}`, { method: 'DELETE' }),
  getHeader: (image_id) =>
    request(image_id ? `/api/header?image_id=${image_id}` : '/api/header'),
  preview: (image_id) =>
    request(image_id ? `/api/preview?image_id=${image_id}` : '/api/preview'),
  runPipeline: (params) =>
    request('/api/run_pipeline', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    }),
  optimizeGeometry: (params) =>
    request('/api/optimize_geometry', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    }),
  renderPlot: (params) =>
    request('/api/render_plot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    }),
  buildFigure: (params) =>
    request('/api/figure', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    }),
  probe: (params) =>
    request('/api/probe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    }),
  regionStats: (params) =>
    request('/api/regions/stats', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    }),
  querySimbad: () => request('/api/query_simbad'),
  resetSession: (wipe = false) =>
    request(`/api/reset_session?wipe_disk=${wipe}`, { method: 'POST' }),
  getSession: () => request('/api/session'),
  restoreSession: (state) =>
    request('/api/session/restore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ state }),
    }),
  getHistory: () => request('/api/history'),
  getHistoryScript: () => request('/api/history/script'),
  setRegions: (regions) =>
    request('/api/session/regions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(regions),
    }),
  rasterMeta: (product = 'data', image_id) => {
    const q = new URLSearchParams({ product });
    if (image_id) q.set('image_id', image_id);
    return request(`/api/raster/meta?${q}`);
  },
  fetchRaster: async (product = 'data', image_id, maxSize = 2048, signal) => {
    const q = new URLSearchParams({ product, max_size: String(maxSize) });
    if (image_id) q.set('image_id', image_id);
    const res = await request(`/api/raster?${q}`, signal ? { signal } : {});
    const buf = await res.arrayBuffer();
    return { data: new Float32Array(buf), meta: parseRasterHeaders(res) };
  },
  fetchTile: async (imageId, product, z, tx, ty, signal) => {
    const res = await request(`/api/tiles/${imageId}/${product}/${z}/${tx}/${ty}`, signal ? { signal } : {});
    const buf = await res.arrayBuffer();
    return { data: new Float32Array(buf), meta: parseRasterHeaders(res) };
  },
  // Legacy (small images only)
  pixelsMeta: (product = 'data', image_id) => {
    const q = new URLSearchParams({ product });
    if (image_id) q.set('image_id', image_id);
    return request(`/api/pixels/meta?${q}`);
  },
};

export default api;
