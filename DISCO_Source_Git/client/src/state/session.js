import { create } from 'zustand';
import { api } from '../api/client';
import { useRegionsStore } from './regions';
import { useViewportStore } from './viewport';

const defaultParams = () => ({
  incl: 0,
  pa: 0,
  cx: 0,
  cy: 0,
  rout: 1.2,
  fit_rmin: 0,
  fit_rmax: 0,
});

export const useSessionStore = create((set, get) => ({
  darkMode: true,
  viewMode: 'single', // 'single' | 'mosaic'
  layoutEpoch: 0,
  connected: true,
  images: [],
  activeImageId: null,
  filename: 'No Data Loaded',
  imgDimensions: null, // { width, height }
  pixelScale: 0.03,
  headerInfo: [],
  params: defaultParams(),
  results: null,
  profileData: null,
  fitStats: null,
  geometry: null,
  rasterMeta: null,
  viewerEpoch: 0,
  hasRunPipeline: false,
  activeViewerTab: 'renderConfig', // 'renderConfig' | 'product'
  loading: { pipeline: false, autoTune: false, simbad: false, image: false },
  probe: null,

  setDarkMode: (darkMode) => set({ darkMode }),
  resetLayout: () => set({ layoutEpoch: get().layoutEpoch + 1 }),
  setViewMode: (viewMode) => {
    if (viewMode === 'mosaic') {
      useViewportStore.getState().setMosaicView({ offsetX: 0, offsetY: 0, k: 0 });
    }
    set({ viewMode });
  },
  setConnected: (connected) => set({ connected }),
  setProbe: (probe) => set({ probe }),
  setParams: (updater) =>
    set((s) => ({
      params: typeof updater === 'function' ? updater(s.params) : { ...s.params, ...updater },
    })),
  setLoading: (key, val) => set((s) => ({ loading: { ...s.loading, [key]: val } })),
  setActiveViewerTab: (activeViewerTab) => set({ activeViewerTab }),

  applyUpload: (payload, header) => {
    const shape = payload.shape || [0, 0];
    const ny = shape[0] || 0;
    const nx = shape[1] || 0;
    const ps = payload.pixel_scale || 0.03;
    const serverParams = payload.params || {};
    const rout = Math.min(2, serverParams.rout ?? Math.max(0.3, Math.min(2, (Math.min(nx, ny) / 2) * 0.35 * ps)));
    useViewportStore.getState().clearTransform();
    useRegionsStore.getState().setActiveTool('select');
    set({
      activeImageId: payload.id,
      filename: payload.filename,
      imgDimensions: { width: nx, height: ny },
      pixelScale: ps,
      headerInfo: header?.header || [],
      params: {
        ...defaultParams(),
        cx: serverParams.cx ?? nx / 2,
        cy: serverParams.cy ?? ny / 2,
        rout,
        incl: serverParams.incl ?? 0,
        pa: serverParams.pa ?? 0,
      },
      results: null,
      profileData: null,
      fitStats: null,
      geometry: null,
      rasterMeta: null,
      hasRunPipeline: false,
      activeViewerTab: 'renderConfig',
      viewerEpoch: get().viewerEpoch + 1,
      images: [
        ...get().images.filter((i) => i.id !== payload.id),
        {
          id: payload.id,
          filename: payload.filename,
          shape,
          pixel_scale: ps,
          params: { cx: nx / 2, cy: ny / 2, rout },
        },
      ],
    });
  },

  setActiveImage: async (id) => {
    const entry = get().images.find((i) => i.id === id);
    if (!entry) return;
    set({ loading: { ...get().loading, image: true } });
    try {
      await api.setActive(id);
      const [header, meta] = await Promise.all([
        api.getHeader(id),
        api.rasterMeta('data', id),
      ]);
      const w = meta.full_width;
      const h = meta.full_height;
      const ps = meta.pixel_scale || entry.pixel_scale || 0.03;
      const saved = entry.params || {};
      const rout = saved.rout ?? Math.max(0.3, Math.min(5, (Math.min(w, h) / 2) * 0.35 * ps));
      set({
        activeImageId: id,
        filename: entry.filename,
        headerInfo: header?.header || [],
        imgDimensions: { width: w, height: h },
        pixelScale: ps,
        rasterMeta: meta,
        params: {
          ...get().params,
          cx: saved.cx ?? w / 2,
          cy: saved.cy ?? h / 2,
          rout,
          incl: saved.incl ?? get().params.incl,
          pa: saved.pa ?? get().params.pa,
        },
        results: null,
        profileData: null,
        fitStats: null,
        hasRunPipeline: false,
        activeViewerTab: 'renderConfig',
        viewerEpoch: get().viewerEpoch + 1,
        loading: { ...get().loading, image: false },
      });
    } catch (e) {
      set({ loading: { ...get().loading, image: false } });
      throw e;
    }
  },

  applyPipeline: (data) => {
    const profile = data.profile || null;
    let fitPatch = {};
    const cur = get().params;
    if (profile?.radius?.length && !(cur.fit_rmax > cur.fit_rmin)) {
      const rMax = profile.radius[profile.radius.length - 1] || 1;
      fitPatch = { fit_rmin: rMax * 0.15, fit_rmax: rMax * 0.7 };
    }
    set({
      results: data.images || null,
      profileData: profile,
      fitStats: data.fit || null,
      geometry: data.geometry || null,
      hasRunPipeline: true,
      activeViewerTab: 'product',
      viewerEpoch: get().viewerEpoch + 1,
      params: { ...get().params, ...fitPatch },
    });
    // Reset mosaic sync to fit so mixed-size products don't inherit a stale pan
    useViewportStore.getState().setMosaicView({ offsetX: 0, offsetY: 0, k: 0 });
  },

  removeImage: async (id) => {
    await api.removeImage(id);
    const images = get().images.filter((i) => i.id !== id);
    if (get().activeImageId === id) {
      if (images.length) {
        await get().setActiveImage(images[0].id);
      } else {
        get().resetWorkspace(false);
      }
    } else {
      set({ images });
    }
  },

  resetWorkspace: async (wipe = false) => {
    try {
      await api.resetSession(wipe);
    } catch {
      /* ignore */
    }
    useRegionsStore.getState().clearRegions();
    useViewportStore.getState().clearTransform();
    set({
      images: [],
      activeImageId: null,
      filename: 'No Data Loaded',
      imgDimensions: null,
      pixelScale: 0.03,
      headerInfo: [],
      params: defaultParams(),
      results: null,
      profileData: null,
      fitStats: null,
      geometry: null,
      rasterMeta: null,
      hasRunPipeline: false,
      activeViewerTab: 'renderConfig',
      viewerEpoch: get().viewerEpoch + 1,
      probe: null,
      loading: { pipeline: false, autoTune: false, simbad: false, image: false },
    });
  },

  /** Human-readable status for the menubar. */
  statusLabel: () => {
    const s = get();
    if (!s.connected) return 'Offline';
    if (s.loading.image) return 'Loading image…';
    if (s.loading.pipeline) return 'Running pipeline…';
    if (s.loading.autoTune) return 'Optimizing…';
    if (s.loading.simbad) return 'Querying SIMBAD…';
    return 'Idle';
  },

  exportSession: () => {
    const s = get();
    return {
      version: 3,
      activeImageId: s.activeImageId,
      images: s.images,
      params: s.params,
      viewMode: s.viewMode,
      darkMode: s.darkMode,
    };
  },
}));

export default useSessionStore;
