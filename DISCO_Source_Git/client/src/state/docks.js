import { create } from 'zustand';

/** Analysis widgets that can move between dock slots. */
export const WIDGET_META = {
  radialProfile: { id: 'radialProfile', label: 'Radial Profile' },
  cumulative: { id: 'cumulative', label: 'Cumulative Flux' },
  sliceProfile: { id: 'sliceProfile', label: 'Slice' },
  gaussianFit: { id: 'gaussianFit', label: 'Gaussian Fit' },
  statistics: { id: 'statistics', label: 'Statistics' },
  histogram: { id: 'histogram', label: 'Histogram' },
};

export const DOCK_SLOTS = ['midTop', 'midBot', 'rightBot'];

export const DEFAULT_DOCKS = {
  midTop: ['radialProfile', 'cumulative'],
  midBot: ['gaussianFit', 'sliceProfile'],
  rightBot: ['statistics', 'histogram'],
};

function firstTab(slots, slotId) {
  const tabs = slots[slotId] || [];
  return tabs[0] || null;
}

export const useDockStore = create((set) => ({
  slots: { ...DEFAULT_DOCKS, midTop: [...DEFAULT_DOCKS.midTop], midBot: [...DEFAULT_DOCKS.midBot], rightBot: [...DEFAULT_DOCKS.rightBot] },
  active: {
    midTop: 'radialProfile',
    midBot: 'gaussianFit',
    rightBot: 'statistics',
  },

  setActive: (slotId, tabId) =>
    set((s) => ({ active: { ...s.active, [slotId]: tabId } })),

  resetDocks: () =>
    set({
      slots: {
        midTop: [...DEFAULT_DOCKS.midTop],
        midBot: [...DEFAULT_DOCKS.midBot],
        rightBot: [...DEFAULT_DOCKS.rightBot],
      },
      active: {
        midTop: 'radialProfile',
        midBot: 'gaussianFit',
        rightBot: 'statistics',
      },
    }),

  /**
   * Move a widget tab from one slot to another (or reorder within the same slot).
   * Empty source slots are allowed; the destination becomes active for that tab.
   */
  moveTab: (tabId, fromSlot, toSlot, toIndex = null) => {
    if (!WIDGET_META[tabId] || !DOCK_SLOTS.includes(toSlot)) return;
    set((s) => {
      const slots = {
        midTop: [...s.slots.midTop],
        midBot: [...s.slots.midBot],
        rightBot: [...s.slots.rightBot],
      };
      const active = { ...s.active };

      // Remove from wherever it currently lives (tolerate stale fromSlot)
      for (const id of DOCK_SLOTS) {
        const i = slots[id].indexOf(tabId);
        if (i >= 0) slots[id].splice(i, 1);
      }

      const dest = slots[toSlot];
      const idx = toIndex == null || toIndex < 0 || toIndex > dest.length
        ? dest.length
        : toIndex;
      dest.splice(idx, 0, tabId);

      active[toSlot] = tabId;
      if (fromSlot && fromSlot !== toSlot && active[fromSlot] === tabId) {
        active[fromSlot] = firstTab(slots, fromSlot);
      }
      // Keep active pointing at something still in each slot
      for (const id of DOCK_SLOTS) {
        if (active[id] && !slots[id].includes(active[id])) {
          active[id] = firstTab(slots, id);
        }
      }
      return { slots, active };
    });
  },
}));

export default useDockStore;
