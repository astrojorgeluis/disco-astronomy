import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Button, ButtonGroup } from '@blueprintjs/core';
import { Renderer } from './Renderer';
import { TileCache, TILE_SIZE } from './TileCache';
import { ViewportController } from './ViewportController';
import { screenToImage, imageToScreen } from './coords';
import { api } from '../api/client';
import OverlayLayer from './OverlayLayer';
import WcsAxes from './WcsAxes';
import Colorbar from './Colorbar';
import { parseWcs } from './wcs';
import useViewportStore from '../state/viewport';
import useSessionStore from '../state/session';
import useRegionsStore from '../state/regions';

/**
 * ImageCanvas — WebGL2 raster + Konva overlays.
 * Fits to view by default when the raster identity changes; preserves
 * per-product views across remounts; Matching XY uses shared physical k/offset.
 */
const DEFAULT_DISK_HALF_PX = 500; // fallback disk FOV when Rout is unknown
const JITTER_PX = 12; // scrollbars/gutters: follow the size but never move the image
const GESTURE_MS = 220; // resizes during a zoom/pan are applied after it settles

/** Percentile helpers for Float32 overview samples (NaN-safe). */
function percentile(sorted, p) {
  if (!sorted.length) return 0;
  const i = Math.min(sorted.length - 1, Math.max(0, Math.floor((p / 100) * (sorted.length - 1))));
  return sorted[i];
}

/** Stretch stats from the disk FOV of a full-field overview (matches analysis products better). */
function diskRegionStats(data, ow, oh, fullW, fullH, cx, cy, halfPx) {
  if (!data?.length || !ow || !oh || !fullW || !fullH) return null;
  const sx = ow / fullW;
  const sy = oh / fullH;
  const half = Math.max(halfPx || DEFAULT_DISK_HALF_PX, 8);
  const x0 = Math.max(0, Math.floor((cx - half) * sx));
  const x1 = Math.min(ow - 1, Math.ceil((cx + half) * sx));
  const y0 = Math.max(0, Math.floor((cy - half) * sy));
  const y1 = Math.min(oh - 1, Math.ceil((cy + half) * sy));
  const vals = [];
  const step = Math.max(1, Math.floor(Math.max(x1 - x0, y1 - y0) / 128));
  for (let y = y0; y <= y1; y += step) {
    const row = y * ow;
    for (let x = x0; x <= x1; x += step) {
      const v = data[row + x];
      if (Number.isFinite(v)) vals.push(v);
    }
  }
  if (vals.length < 8) return null;
  vals.sort((a, b) => a - b);
  return {
    min: vals[0],
    max: vals[vals.length - 1],
    p995: percentile(vals, 99.5),
    p999: percentile(vals, 99.9),
  };
}

export default function ImageCanvas({
  imageId,
  product = 'data',
  headerInfo = [],
  imgW: imgWProp = 0,
  imgH: imgHProp = 0,
  pixelScale = 0.03,
  viz,
  limits,
  epoch = 0,
  showGeometry = false,
  showRegions = true,
  interactive = true,
  sharedVp = null,
  onActivate = null,
  active = false,
  showColorbar = true,
  showAxes = true,
  persistView = true,
  showZoomControls = true,
  frameDisk = false, // frame full-res data on the disk instead of the whole field
  diskCenter = null, // { cx, cy } in array coords of the full data image
  diskHalfPx = 0, // half FOV of the analysis products, in full-res pixels
}) {
  const containerRef = useRef(null);
  const canvasRef = useRef(null);
  const rendererRef = useRef(null);
  const cacheRef = useRef(null);
  const vpRef = useRef(null);
  const overviewRef = useRef(null);
  const statsRef = useRef(null);
  const fittedKeyRef = useRef('');
  const fitViewSizeRef = useRef({ w: 0, h: 0 });
  const dimsRef = useRef({ w: 0, h: 0 });
  const imgSizeRef = useRef({ w: 0, h: 0 });
  const applyingNormRef = useRef(false);
  const matchXYRef = useRef(false);
  const persistViewRef = useRef(persistView);
  const restoreOrFitRef = useRef(null);
  const diskCenterRef = useRef(diskCenter);
  const diskHalfRef = useRef(DEFAULT_DISK_HALF_PX);
  const gestureUntilRef = useRef(0);
  const pendingSizeRef = useRef(null);
  const deferTimerRef = useRef(0);
  const [dims, setDims] = useState({ w: 0, h: 0 });
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 });
  const [ready, setReady] = useState(false);
  const [rasterSize, setRasterSize] = useState({ w: imgWProp, h: imgHProp });

  const imgW = rasterSize.w || imgWProp;
  const imgH = rasterSize.h || imgHProp;
  imgSizeRef.current = { w: imgW, h: imgH };
  diskCenterRef.current = diskCenter;
  diskHalfRef.current = diskHalfPx > 8 ? diskHalfPx : DEFAULT_DISK_HALF_PX;

  const wcs = product === 'data' || product === 'deproj' ? parseWcs(headerInfo) : null;

  const setView = useViewportStore((s) => s.setView);
  const darkMode = useSessionStore((s) => s.darkMode);
  const regionTool = useRegionsStore((s) => s.regionTool);
  const geomPolyDraft = useRegionsStore((s) => s.geomPolyDraft);
  const geomPolyCount = geomPolyDraft?.points?.length || 0;
  const matchXY = useViewportStore((s) => s.matchXY);
  const mosaicView = useViewportStore((s) => s.mosaicView);
  const mosaicViewEpoch = useViewportStore((s) => s.mosaicViewEpoch);
  const setMosaicView = useViewportStore((s) => s.setMosaicView);
  const viewMode = useSessionStore((s) => s.viewMode);
  const viewKey = `${imageId || ''}:${product}`;
  // Matching XY only applies in mosaic, and never to polar (different axes)
  const matchXYActive = matchXY && viewMode === 'mosaic' && product !== 'polar';

  matchXYRef.current = matchXYActive;
  persistViewRef.current = persistView;

  /** Center of the disk in THIS product's array coordinates. */
  const productCenter = useCallback((fullW, fullH) => {
    // Cropped / remapped products are centered on their own grid
    if (product === 'deproj' || product === 'model' || product === 'residuals' || product === 'polar') {
      return { cx: fullW / 2, cy: fullH / 2 };
    }
    const dc = diskCenterRef.current;
    if (dc && Number.isFinite(dc.cx) && Number.isFinite(dc.cy)) {
      return { cx: dc.cx, cy: dc.cy };
    }
    return { cx: fullW / 2, cy: fullH / 2 };
  }, [product]);

  /** Apply shared physical mosaic view {offsetX, offsetY, k} to this cell. */
  const applyPhysicalToVp = useCallback((view, fullW, fullH, viewW, viewH) => {
    const vp = vpRef.current;
    if (!vp || !fullW || !viewW || !viewH) return;
    const { cx, cy } = productCenter(fullW, fullH);
    let k = view.k;
    if (!k || k <= 0) {
      // Auto: frame the product FOV (disk + margin) in the cell
      const region = Math.min(diskHalfRef.current * 2, Math.min(fullW, fullH));
      k = Math.min(viewW / region, viewH / region) * 0.92;
    }
    const ix = cx + (view.offsetX || 0);
    const iyDisplay = fullH - (cy + (view.offsetY || 0));
    const x = viewW / 2 - ix * k;
    const y = viewH / 2 - iyDisplay * k;
    applyingNormRef.current = true;
    vp.set({ x, y, k });
    requestAnimationFrame(() => { applyingNormRef.current = false; });
  }, [productCenter]);

  const vpToPhysical = (vp, fullW, fullH, viewW, viewH) => {
    const { cx, cy } = productCenter(fullW, fullH);
    const ix = (viewW / 2 - vp.x) / vp.k;
    const iyDisplay = (viewH / 2 - vp.y) / vp.k;
    const iyArray = fullH - iyDisplay;
    return {
      offsetX: ix - cx,
      offsetY: iyArray - cy,
      k: vp.k,
    };
  };

  /** Frame the disk region (for full-res data in mosaic) or fit whole image. */
  const fitDiskOrImage = useCallback((vp, fullW, fullH, viewW, viewH) => {
    const diskHalf = diskHalfRef.current;
    const isFullData = frameDisk && product === 'data' && fullW > diskHalf * 2.5;
    if (isFullData) {
      const { cx, cy } = productCenter(fullW, fullH);
      const region = diskHalf * 2;
      const k = Math.min(viewW / region, viewH / region) * 0.92;
      const iyDisplay = fullH - cy;
      vp.set({
        x: viewW / 2 - cx * k,
        y: viewH / 2 - iyDisplay * k,
        k,
      });
    } else {
      vp.fit(fullW, fullH, viewW, viewH);
    }
  }, [frameDisk, product, productCenter]);

  const restoreOrFit = useCallback((fullW, fullH, viewW, viewH) => {
    const vp = vpRef.current;
    if (!vp || !fullW || !fullH || viewW < 50 || viewH < 50) return false;

    if (matchXYRef.current && !sharedVp) {
      applyPhysicalToVp(useViewportStore.getState().mosaicView, fullW, fullH, viewW, viewH);
      fittedKeyRef.current = `${imageId}:${product}:${fullW}x${fullH}`;
      fitViewSizeRef.current = { w: viewW, h: viewH };
      return true;
    }

    // Polar has a different aspect / axes — always fit; never reuse Matching XY or stale pans
    const forceFit = product === 'polar';
    const saved = !forceFit && persistViewRef.current && !sharedVp
      ? useViewportStore.getState().views?.[`${imageId}:${product}`]
      : null;
    if (saved && saved.imgW === fullW && saved.imgH === fullH && saved.t) {
      vp.set(saved.t);
    } else {
      fitDiskOrImage(vp, fullW, fullH, viewW, viewH);
      if (persistViewRef.current && imageId && !forceFit) {
        setView(`${imageId}:${product}`, vp.transform, fullW, fullH);
      }
    }
    fittedKeyRef.current = `${imageId}:${product}:${fullW}x${fullH}`;
    fitViewSizeRef.current = { w: viewW, h: viewH };
    return true;
  }, [applyPhysicalToVp, fitDiskOrImage, imageId, product, setView, sharedVp]);

  restoreOrFitRef.current = restoreOrFit;

  // Viewport controller (stable per viewKey)
  useEffect(() => {
    if (sharedVp) {
      vpRef.current = sharedVp;
      const unsub = sharedVp.subscribe((t) => setTransform({ ...t }));
      setTransform({ ...sharedVp.transform });
      return unsub;
    }
    const vp = new ViewportController();
    vpRef.current = vp;
    let persistTimer = 0;
    const unsub = vp.subscribe((t) => {
      setTransform({ ...t });
      const { w: iw, h: ih } = imgSizeRef.current;
      const { w: vw, h: vh } = dimsRef.current;
      if (persistViewRef.current && imageId && iw > 0) {
        clearTimeout(persistTimer);
        persistTimer = setTimeout(() => setView(viewKey, t, iw, ih), 120);
      }
      if (
        matchXYRef.current
        && iw > 0 && vw > 50
        && !applyingNormRef.current
        && fittedKeyRef.current
      ) {
        setMosaicView(vpToPhysical(vp, iw, ih, vw, vh));
      }
    });
    return () => {
      unsub();
      clearTimeout(persistTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sharedVp, viewKey]);

  // Apply mosaicView from another cell
  useEffect(() => {
    if (!matchXYActive || sharedVp || !imgW || dims.w < 50 || !fittedKeyRef.current) return;
    applyPhysicalToVp(mosaicView, imgW, imgH, dims.w, dims.h);
  }, [mosaicViewEpoch, matchXYActive, imgW, imgH, dims.w, dims.h, applyPhysicalToVp, mosaicView, sharedVp]);

  // Measure container once; ignore sub-pixel jitter; refit on large size jumps
  useEffect(() => {
    if (!containerRef.current) return undefined;
    const el = containerRef.current;

    const applySize = (w, h) => {
      const nw = Math.max(0, Math.floor(w));
      const nh = Math.max(0, Math.floor(h));
      const prev = dimsRef.current;
      if (prev.w === nw && prev.h === nh) return;

      // A resize mid-gesture would visibly shift/rescale the image: defer it
      if (Date.now() < gestureUntilRef.current) {
        pendingSizeRef.current = { w: nw, h: nh };
        clearTimeout(deferTimerRef.current);
        deferTimerRef.current = setTimeout(() => {
          const p = pendingSizeRef.current;
          pendingSizeRef.current = null;
          if (p) applySize(p.w, p.h);
        }, GESTURE_MS + 40);
        return;
      }

      // Keep the backing store exactly on the container so nothing is stretched
      dimsRef.current = { w: nw, h: nh };
      setDims({ w: nw, h: nh });

      const vp = vpRef.current;
      const { w: iw, h: ih } = imgSizeRef.current;
      const key = fittedKeyRef.current;
      if (!vp || !key || iw <= 0 || nw < 50 || nh < 50) return;

      if (prev.w < 50 || prev.h < 50 || fitViewSizeRef.current.w < 50) {
        restoreOrFitRef.current?.(iw, ih, nw, nh);
        return;
      }
      // Scrollbars/gutters: follow the size but leave the transform alone
      if (Math.abs(nw - prev.w) <= JITTER_PX && Math.abs(nh - prev.h) <= JITTER_PX) {
        fitViewSizeRef.current = { w: nw, h: nh };
        return;
      }
      const dw = Math.abs(nw - prev.w) / Math.max(prev.w, 1);
      const dh = Math.abs(nh - prev.h) / Math.max(prev.h, 1);
      // Large layout change (tab/mosaic) → refit rather than keep a bad zoom
      if (dw > 0.2 || dh > 0.2) {
        restoreOrFitRef.current?.(iw, ih, nw, nh);
      } else {
        vp.reanchor(prev.w, prev.h, nw, nh);
        fitViewSizeRef.current = { w: nw, h: nh };
      }
    };

    const rect = el.getBoundingClientRect();
    applySize(rect.width, rect.height);

    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        applySize(e.contentRect.width, e.contentRect.height);
      }
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      clearTimeout(deferTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (!canvasRef.current) return undefined;
    try {
      rendererRef.current = new Renderer(canvasRef.current);
      const dark = document.body.classList.contains('bp6-dark');
      rendererRef.current.setClearColor(
        ...(dark ? [0.043, 0.071, 0.125, 1] : [0.898, 0.906, 0.922, 1]),
      );
    } catch (e) {
      console.error(e);
    }
    return () => {
      rendererRef.current?.destroy();
      rendererRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!imageId) {
      rendererRef.current?.clearAll();
      setReady(false);
      overviewRef.current = null;
      statsRef.current = null;
      fittedKeyRef.current = '';
    }
  }, [imageId]);

  const paint = useCallback((overrideLimits, overrideTransform) => {
    const r = rendererRef.current;
    const vp = vpRef.current;
    if (!r || !vp || !overviewRef.current) return;
    const stats = statsRef.current;
    let vmin = overrideLimits?.vmin;
    let vmax = overrideLimits?.vmax;
    if (!Number.isFinite(vmin) || !Number.isFinite(vmax)) {
      // Custom absolute limits, else per-product stretch from stats + limitMode
      if (viz?.limitMode === 'custom' && Number.isFinite(viz?.vmin) && Number.isFinite(viz?.vmax)) {
        vmin = viz.vmin;
        vmax = viz.vmax;
      } else if (limits && Number.isFinite(limits.vmin) && Number.isFinite(limits.vmax)
          && (viz?.autoLimits === false || viz?.limitMode === 'custom')) {
        vmin = limits.vmin;
        vmax = limits.vmax;
      } else if (stats) {
        const mode = viz?.limitMode || 'minmax';
        vmin = stats.min;
        if (mode === 'p995') vmax = stats.p995 ?? stats.max;
        else if (mode === 'p999') vmax = stats.p999 ?? stats.max;
        else vmax = stats.max;
      } else if (limits && Number.isFinite(limits.vmin) && Number.isFinite(limits.vmax)) {
        vmin = limits.vmin;
        vmax = limits.vmax;
      } else return;
    }
    r.setLut(viz?.cmap || 'inferno', !!viz?.invert);
    r.resize(Math.max(1, dims.w), Math.max(1, dims.h));
    r.render({
      vmin,
      vmax,
      stretch: viz?.stretch || 'linear',
      transform: overrideTransform || vp.transform,
      preferTiles: r._tiles.size > 0,
    });
  }, [dims.w, dims.h, limits, viz?.autoLimits, viz?.limitMode, viz?.vmin, viz?.vmax, viz?.cmap, viz?.invert, viz?.stretch]);

  useEffect(() => {
    const r = rendererRef.current;
    if (!r) return;
    if (darkMode) r.setClearColor(0.043, 0.071, 0.125, 1);
    else r.setClearColor(0.898, 0.906, 0.922, 1);
    paint();
  }, [darkMode, paint]);

  const doFit = useCallback(() => {
    const vp = vpRef.current;
    const d = dimsRef.current;
    if (!vp || !imgW || d.w < 20) return;
    fitDiskOrImage(vp, imgW, imgH, d.w, d.h);
    fittedKeyRef.current = `${viewKey}:${imgW}x${imgH}`;
    fitViewSizeRef.current = { w: d.w, h: d.h };
    if (persistView && imageId) setView(viewKey, vp.transform, imgW, imgH);
    if (matchXYActive) {
      setMosaicView({ offsetX: 0, offsetY: 0, k: 0 });
    }
  }, [imgW, imgH, viewKey, persistView, imageId, setView, matchXYActive, setMosaicView, fitDiskOrImage]);

  // Load overview
  useEffect(() => {
    let cancelled = false;
    const ctrl = new AbortController();
    (async () => {
      if (!imageId) {
        setReady(false);
        return;
      }
      // Drop the previous product immediately so a stale frame isn't left on screen
      setReady(false);
      overviewRef.current = null;
      fittedKeyRef.current = '';
      setRasterSize({ w: 0, h: 0 });
      cacheRef.current?.clear();
      rendererRef.current?.clearTiles();
      try {
        const { data, meta } = await api.fetchRaster(product, imageId, 2048, ctrl.signal);
        if (cancelled) return;
        const fullW = meta.fullWidth || imgWProp || meta.width;
        const fullH = meta.fullHeight || imgHProp || meta.height;
        setRasterSize({ w: fullW, h: fullH });
        imgSizeRef.current = { w: fullW, h: fullH };
        overviewRef.current = { data, meta };
        let stats = {
          min: meta.min, max: meta.max, p995: meta.p995, p999: meta.p999,
        };
        // Full-field data stretch is dominated by sky/noise; use disk FOV when framing the disk
        if (frameDisk && product === 'data') {
          const dc = diskCenterRef.current;
          const diskStats = diskRegionStats(
            data, meta.width, meta.height, fullW, fullH,
            dc?.cx ?? fullW / 2, dc?.cy ?? fullH / 2, diskHalfRef.current,
          );
          if (diskStats) stats = diskStats;
        }
        statsRef.current = stats;
        cacheRef.current = new TileCache({
          maxTiles: 64,
          fetchTile: async (z, tx, ty, signal) => {
            const { data: tile } = await api.fetchTile(imageId, product, z, tx, ty, signal);
            return tile;
          },
        });
        const r = rendererRef.current;
        if (r) {
          r.clearTiles();
          r.setImageSize(fullW, fullH);
          r.uploadOverview(data, meta.width, meta.height);
        }

        const d = dimsRef.current;
        const vp = vpRef.current;
        if (vp && d.w >= 50 && d.h >= 50) {
          restoreOrFit(fullW, fullH, d.w, d.h);
        } else {
          fittedKeyRef.current = '';
        }

        let paintVmin;
        let paintVmax;
        if (viz?.limitMode === 'custom' && Number.isFinite(viz?.vmin) && Number.isFinite(viz?.vmax)) {
          paintVmin = viz.vmin;
          paintVmax = viz.vmax;
        } else {
          const mode = viz?.limitMode || 'minmax';
          paintVmin = stats.min;
          paintVmax = mode === 'p995' ? (stats.p995 ?? stats.max)
            : mode === 'p999' ? (stats.p999 ?? stats.max)
              : stats.max;
        }
        if (r && vp) {
          r.setLut(viz?.cmap || 'inferno', !!viz?.invert);
          r.resize(Math.max(1, d.w), Math.max(1, d.h));
          r.render({
            vmin: paintVmin,
            vmax: paintVmax,
            stretch: viz?.stretch || 'linear',
            transform: vp.transform,
            preferTiles: false,
          });
        }
        setReady(true);
      } catch (e) {
        if (e?.name !== 'AbortError') console.warn('raster load', e);
        setReady(false);
      }
    })();
    return () => {
      cancelled = true;
      ctrl.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imageId, product, epoch]);

  // Fit once real container size is known after load
  useEffect(() => {
    if (!ready || !imgW || dims.w < 50 || dims.h < 50) return;
    const key = `${imageId}:${product}:${imgW}x${imgH}`;
    if (fittedKeyRef.current !== key) {
      restoreOrFit(imgW, imgH, dims.w, dims.h);
    }
  }, [ready, dims.w, dims.h, imgW, imgH, imageId, product, restoreOrFit]);

  useEffect(() => { paint(); }, [paint, transform]);

  // Progressive tiles
  useEffect(() => {
    const cache = cacheRef.current;
    const r = rendererRef.current;
    const vp = vpRef.current;
    const ov = overviewRef.current;
    if (!cache || !r || !vp || !ov || !imgW || !imageId || dims.w < 1) return undefined;
    const decim = ov.meta.decimation || 1;
    if (vp.k * decim < 1.2) return undefined;
    const z = Math.max(0, Math.min(3, Math.round(Math.log2(Math.max(1, 1 / vp.k)))));
    const tl = screenToImage(0, 0, vp.transform, imgH);
    const br = screenToImage(dims.w, dims.h, vp.transform, imgH);
    let cancelled = false;
    const t = setTimeout(() => {
      cache.requestVisible({
        z, imgW, imgH,
        x0: Math.min(tl.x, br.x), y0: Math.min(tl.y, br.y),
        x1: Math.max(tl.x, br.x), y1: Math.max(tl.y, br.y),
        onTile: (tz, tx, ty, data) => {
          if (cancelled) return;
          r.uploadTile(tz, tx, ty, data, TILE_SIZE, TILE_SIZE);
          paint();
        },
      });
    }, 100);
    return () => { cancelled = true; clearTimeout(t); };
  }, [transform.k, transform.x, transform.y, imgW, imgH, dims.w, dims.h, imageId, paint]);

  const markGesture = () => {
    gestureUntilRef.current = Date.now() + GESTURE_MS;
  };

  const handleWheel = (e) => {
    if (!interactive) return;
    e.evt.preventDefault();
    markGesture();
    const ptr = e.target.getStage().getPointerPosition();
    vpRef.current?.zoomAt(ptr.x, ptr.y, e.evt.deltaY < 0 ? 1.12 : 1 / 1.12);
  };

  const handlePanMove = (dx, dy) => {
    const vp = vpRef.current;
    if (!vp) return;
    markGesture();
    paint(undefined, { x: vp.x + dx, y: vp.y + dy, k: vp.k });
  };

  const handlePanEnd = (dx, dy) => {
    markGesture();
    vpRef.current?.pan(dx, dy);
  };

  const zoomBtn = (factor) => {
    markGesture();
    vpRef.current?.zoomAt(dims.w / 2, dims.h / 2, factor);
  };

  return (
    <div
      ref={containerRef}
      className="disco-viewer-frame"
      onMouseDown={() => onActivate?.()}
      style={{ outline: active ? '2px solid var(--disco-accent)' : undefined, outlineOffset: -2 }}
    >
      <canvas
        ref={canvasRef}
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}
      />
      {!imageId && (
        <div style={{
          position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
          justifyContent: 'center', color: 'var(--disco-text-muted)', pointerEvents: 'none',
        }}>
          No image loaded
        </div>
      )}
      {showAxes && imgW > 0 && ready && dims.w > 0 && (
        <WcsAxes
          width={dims.w} height={dims.h} transform={transform}
          imgW={imgW} imgH={imgH} wcs={wcs} pixelScale={pixelScale}
        />
      )}
      {ready && imgW > 0 && dims.w > 0 && (
        <OverlayLayer
          width={dims.w}
          height={dims.h}
          transform={transform}
          imgW={imgW}
          imgH={imgH}
          pixelScale={pixelScale}
          showGeometry={showGeometry}
          showRegions={showRegions}
          interactive={interactive}
          product={product}
          onWheel={handleWheel}
          onPanMove={handlePanMove}
          onPanEnd={handlePanEnd}
          screenToImage={(sx, sy) => screenToImage(sx, sy, transform, imgH)}
          imageToScreen={(ix, iy) => imageToScreen(ix, iy, transform, imgH)}
        />
      )}
      {showColorbar && statsRef.current && ready && (() => {
        const st = statsRef.current;
        let cbMin;
        let cbMax;
        if (viz?.limitMode === 'custom' && Number.isFinite(viz?.vmin) && Number.isFinite(viz?.vmax)) {
          cbMin = viz.vmin;
          cbMax = viz.vmax;
        } else if (limits && Number.isFinite(limits.vmin) && Number.isFinite(limits.vmax)
            && viz?.autoLimits === false) {
          cbMin = limits.vmin;
          cbMax = limits.vmax;
        } else {
          const mode = viz?.limitMode || 'minmax';
          cbMin = st.min;
          cbMax = mode === 'p995' ? (st.p995 ?? st.max)
            : mode === 'p999' ? (st.p999 ?? st.max)
              : st.max;
        }
        return (
          <Colorbar
            vmin={cbMin}
            vmax={cbMax}
            cmap={viz?.cmap || 'inferno'}
            invert={!!viz?.invert}
          />
        );
      })()}
      {regionTool === 'geomPoly' && (
        <div className="disco-trace-hint">
          Click the disk rim
          <span className="disco-numeric"> · {geomPolyCount}/4</span>
        </div>
      )}
      {showZoomControls && imageId && (
        <div style={{ position: 'absolute', left: 6, bottom: 6, zIndex: 3 }}>
          <ButtonGroup minimal>
            <Button small icon="zoom-in" title="Zoom in" onClick={() => zoomBtn(1.25)} />
            <Button small icon="zoom-out" title="Zoom out" onClick={() => zoomBtn(1 / 1.25)} />
            <Button small icon="zoom-to-fit" title="Fit to view" onClick={doFit} />
          </ButtonGroup>
        </div>
      )}
    </div>
  );
}
