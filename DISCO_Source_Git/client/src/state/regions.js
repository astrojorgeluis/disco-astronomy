import { create } from 'zustand';
import { useDockStore } from './docks';

let _seq = 1;
export function makeRegionId() {
  return `r${Date.now().toString(36)}_${_seq++}`;
}

const COLORS = ['#10b981', '#06b6d4', '#8b25eb', '#ea580c', '#dc2626', '#8b5cf6'];

function revealStatisticsTab() {
  const { slots, setActive } = useDockStore.getState();
  for (const [slotId, tabs] of Object.entries(slots)) {
    if (tabs.includes('statistics')) {
      setActive(slotId, 'statistics');
      return;
    }
  }
}

export const useRegionsStore = create((set, get) => ({
  activeTool: 'select', // pan | select | radial | region
  regionTool: null, // ellipse | rectangle | polygon | annulus | line | geomPoly | null
  regions: [],
  selectedRegionId: null,
  selectedGeom: false,
  regionStats: null,
  sliceLine: null,
  /** Temporary polygon for seeding disk ellipse — not a ROI. */
  geomPolyDraft: null,

  setActiveTool: (activeTool) => set({
    activeTool: activeTool === 'inspector' ? 'radial' : activeTool,
    regionTool: null, geomPolyDraft: null, selectedGeom: false,
  }),
  setRegionTool: (regionTool) =>
    set(
      regionTool
        ? { regionTool, activeTool: 'region', selectedRegionId: null, selectedGeom: false }
        : { regionTool: null, activeTool: 'select' },
    ),
  setGeomPolyDraft: (geomPolyDraft) => set({ geomPolyDraft }),
  clearGeomPolyDraft: () => set({ geomPolyDraft: null, regionTool: null, activeTool: 'select' }),
  setSelectedRegionId: (selectedRegionId) => {
    set({ selectedRegionId, selectedGeom: false });
    if (selectedRegionId) revealStatisticsTab();
  },
  setSelectedGeom: (selectedGeom) => set({ selectedGeom, selectedRegionId: selectedGeom ? null : get().selectedRegionId }),
  setRegionStats: (regionStats) => set({ regionStats }),
  setSliceLine: (sliceLine) => set({ sliceLine }),
  setRegions: (regions) => set({ regions }),

  addRegion: (region) =>
    set((s) => {
      const id = region.id || makeRegionId();
      const color = region.color || COLORS[s.regions.length % COLORS.length];
      const next = [
        ...s.regions,
        {
          ...region,
          id,
          name: region.name || `${region.type} ${s.regions.length + 1}`,
          color,
          locked: !!region.locked,
        },
      ];
      queueMicrotask(() => revealStatisticsTab());
      return { regions: next, selectedRegionId: id };
    }),

  updateRegion: (id, patch) =>
    set((s) => ({
      regions: s.regions.map((r) => (r.id === id ? { ...r, ...patch } : r)),
    })),

  removeRegion: (id) =>
    set((s) => ({
      regions: s.regions.filter((r) => r.id !== id),
      selectedRegionId: s.selectedRegionId === id ? null : s.selectedRegionId,
    })),

  clearRegions: () => set({
    regions: [],
    selectedRegionId: null,
    selectedGeom: false,
    regionStats: null,
    sliceLine: null,
    geomPolyDraft: null,
  }),
}));

export default useRegionsStore;
