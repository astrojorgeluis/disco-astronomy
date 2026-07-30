import { create } from 'zustand';

export const useVizStore = create((set, get) => ({
  cmap: 'inferno',
  stretch: 'linear',
  vmin: null,
  vmax: null,
  invert: false,
  autoLimits: true,
  limitMode: 'minmax', // 'minmax' | 'p995' | 'p999' | 'custom'
  showAxes: true,
  showColorbar: true,
  product: 'deproj',

  setViz: (updater) =>
    set((s) => (typeof updater === 'function' ? updater(s) : { ...s, ...updater })),

  setProduct: (product) => set({ product }),

  /** Apply a percentile/minmax preset — each canvas uses its own product stats. */
  applyStats: (_stats, mode = 'minmax') => {
    set({
      autoLimits: true,
      limitMode: mode,
      vmin: null,
      vmax: null,
    });
  },

  /** Absolute custom stretch limits (shared across viewers). */
  setCustomLimits: (vmin, vmax) => {
    const lo = Number(vmin);
    const hi = Number(vmax);
    if (!Number.isFinite(lo) || !Number.isFinite(hi) || lo === hi) return false;
    set({
      autoLimits: false,
      limitMode: 'custom',
      vmin: Math.min(lo, hi),
      vmax: Math.max(lo, hi),
    });
    return true;
  },

  /** Derive stretch limits from a product's stats + current limitMode. */
  limitsFromStats: (stats) => {
    const s = get();
    if (!stats) return { vmin: 0, vmax: 1 };
    if (!s.autoLimits && s.limitMode === 'custom'
        && Number.isFinite(s.vmin) && Number.isFinite(s.vmax)) {
      return { vmin: s.vmin, vmax: s.vmax };
    }
    if (s.autoLimits) {
      if (s.limitMode === 'p995') return { vmin: stats.min, vmax: stats.p995 ?? stats.max };
      if (s.limitMode === 'p999') return { vmin: stats.min, vmax: stats.p999 ?? stats.max };
      return { vmin: stats.min, vmax: stats.max };
    }
    if (Number.isFinite(s.vmin) && Number.isFinite(s.vmax)) {
      return { vmin: s.vmin, vmax: s.vmax };
    }
    return { vmin: stats.min, vmax: stats.max };
  },

  limitsOrStats: (stats) => get().limitsFromStats(stats),
}));

export default useVizStore;
