/** Resolve CSS custom properties for canvas / Konva (non-DOM contexts). */

const CACHE = {};

export function cssVar(name, fallback = '#000') {
  if (CACHE[name]) return CACHE[name];
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    CACHE[name] = v || fallback;
    return CACHE[name];
  } catch {
    return fallback;
  }
}

export function invalidateThemeColors() {
  Object.keys(CACHE).forEach((k) => delete CACHE[k]);
}

export function resolveThemeColors() {
  return {
    accent: cssVar('--disco-accent', '#2563eb'),
    roi: cssVar('--disco-roi', '#10b981'),
    roiAlt: cssVar('--disco-roi-alt', '#06b6d4'),
    warning: cssVar('--disco-warning', '#ea580c'),
    danger: cssVar('--disco-danger', '#dc2626'),
    text: cssVar('--disco-text', '#111827'),
    muted: cssVar('--disco-text-muted', '#6b7280'),
    border: cssVar('--disco-border', '#d1d5db'),
    panel: cssVar('--disco-bg-panel', '#ffffff'),
  };
}
