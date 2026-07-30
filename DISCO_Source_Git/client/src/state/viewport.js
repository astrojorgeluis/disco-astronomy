import { create } from 'zustand';

/**
 * Viewport store.
 * views[`${imageId}:${product}`] = { t, imgW, imgH }
 * mosaicView = physical Matching XY state:
 *   offsetX/Y — array-pixel offset from disk center (shared across products)
 *   k — CSS pixels per image pixel (0 = auto-fit disk FOV of ~1000px)
 */
export const useViewportStore = create((set) => ({
  matchXY: true,
  activeMosaicCell: 0,
  mosaicSources: [
    { kind: 'product', product: 'data', imageId: null },
    { kind: 'product', product: 'deproj', imageId: null },
    { kind: 'product', product: 'model', imageId: null },
    { kind: 'product', product: 'residuals', imageId: null },
  ],
  bottomTab: 'imageList',
  views: {},
  mosaicView: { offsetX: 0, offsetY: 0, k: 0 },
  mosaicViewEpoch: 0,

  setMatchXY: (matchXY) => set({ matchXY }),
  setActiveMosaicCell: (activeMosaicCell) => set({ activeMosaicCell }),
  setMosaicSource: (index, source) =>
    set((s) => {
      const mosaicSources = s.mosaicSources.slice();
      mosaicSources[index] = { ...mosaicSources[index], ...source };
      return { mosaicSources };
    }),
  setBottomTab: (bottomTab) => set({ bottomTab }),

  setView: (key, t, imgW, imgH) =>
    set((s) => ({
      views: { ...s.views, [key]: { t: { ...t }, imgW, imgH } },
    })),

  setMosaicView: (patch) =>
    set((s) => {
      const next = { ...s.mosaicView, ...patch };
      if (Number.isFinite(next.k) && next.k > 0) {
        next.k = Math.min(64, Math.max(0.001, next.k));
      }
      if (Number.isFinite(next.offsetX)) {
        next.offsetX = Math.min(20000, Math.max(-20000, next.offsetX));
      }
      if (Number.isFinite(next.offsetY)) {
        next.offsetY = Math.min(20000, Math.max(-20000, next.offsetY));
      }
      if (
        Math.abs(next.offsetX - s.mosaicView.offsetX) < 1e-4
        && Math.abs(next.offsetY - s.mosaicView.offsetY) < 1e-4
        && Math.abs((next.k || 0) - (s.mosaicView.k || 0)) < 1e-6
      ) {
        return s;
      }
      return {
        mosaicView: next,
        mosaicViewEpoch: s.mosaicViewEpoch + 1,
      };
    }),

  /** @deprecated alias kept for call-site migration */
  setMosaicNorm: (mosaicNorm) => {
    // Map legacy fractional payload → physical reset
    if (mosaicNorm && ('cx' in mosaicNorm || 'zoom' in mosaicNorm)) {
      return set((s) => ({
        mosaicView: { offsetX: 0, offsetY: 0, k: 0 },
        mosaicViewEpoch: s.mosaicViewEpoch + 1,
      }));
    }
    return set((s) => ({
      mosaicView: { ...s.mosaicView, ...mosaicNorm },
      mosaicViewEpoch: s.mosaicViewEpoch + 1,
    }));
  },

  clearTransform: () => set({
    views: {},
    mosaicView: { offsetX: 0, offsetY: 0, k: 0 },
    mosaicViewEpoch: 0,
  }),
}));

export default useViewportStore;
