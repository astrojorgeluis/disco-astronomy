/** Canonical product ids → UI labels. */
export const PRODUCT_LABELS = {
  data: 'Data',
  deproj: 'Deprojected',
  polar: 'Polar',
  model: 'Model',
  residuals: 'Residuals',
};

export const PRODUCT_IDS = Object.keys(PRODUCT_LABELS);

/** Mosaic dropdown: no polar (too tall / wrong aspect for the 2×2 grid). */
export const MOSAIC_PRODUCT_IDS = ['data', 'deproj', 'model', 'residuals'];

export function productLabel(id) {
  return PRODUCT_LABELS[id] || id;
}
