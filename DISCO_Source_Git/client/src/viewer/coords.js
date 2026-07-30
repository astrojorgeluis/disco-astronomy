/**
 * Single coordinate convention for DISCO viewer.
 *
 * Image / array space (FITS):
 *   - Origin at bottom-left
 *   - x increases to the right (east usually decreases in RA)
 *   - y increases upward (north)
 *
 * Screen / CSS space:
 *   - Origin at top-left
 *   - y increases downward
 *
 * Analysis products (deproj/model/residuals) are a square crop centered on the
 * disk: pixel (W/2, H/2) ↔ full-data (cx, cy). Regions and probes are stored
 * in full-data array coordinates and mapped when drawn on a cropped product.
 *
 * Viewport transform {x, y, k} maps *display-down* pixels to screen:
 *   displayY = imgH - arrayY
 *   screenX  = displayX * k + x
 *   screenY  = displayY * k + y
 */

export function arrayToDisplay(ix, iy, imgH) {
  return { x: ix, y: imgH - iy };
}

export function displayToArray(dx, dy, imgH) {
  return { x: dx, y: imgH - dy };
}

export function imageToScreen(ix, iy, transform, imgH) {
  const { x, y, k } = transform;
  return {
    x: ix * k + x,
    y: (imgH - iy) * k + y,
  };
}

export function screenToImage(sx, sy, transform, imgH) {
  const { x, y, k } = transform;
  const dx = (sx - x) / k;
  const dy = (sy - y) / k;
  return { x: dx, y: imgH - dy };
}

/** Cropped analysis products share pixel scale with data but a shifted origin. */
export function isCroppedProduct(product) {
  return product === 'deproj' || product === 'model' || product === 'residuals';
}

/** Local product array coords → full-data array coords. */
export function toDataCoords(x, y, product, imgW, imgH, cx, cy) {
  if (!isCroppedProduct(product)) return { x, y };
  return { x: x - imgW / 2 + cx, y: y - imgH / 2 + cy };
}

/** Full-data array coords → local product array coords. */
export function toProductCoords(x, y, product, imgW, imgH, cx, cy) {
  if (!isCroppedProduct(product)) return { x, y };
  return { x: x - cx + imgW / 2, y: y - cy + imgH / 2 };
}

/**
 * Konva group in *display* coordinates (y↓, positive scale).
 * Prefer this for interactive shapes so Transformer/resize works.
 */
export function konvaDisplayGroupProps(transform) {
  const { x, y, k } = transform;
  return { x, y, scaleX: k, scaleY: k };
}

/** @deprecated negative scaleY breaks Konva Transformer — use konvaDisplayGroupProps */
export function konvaImageGroupProps(transform, imgH) {
  const { x, y, k } = transform;
  return {
    x,
    y: y + imgH * k,
    scaleX: k,
    scaleY: -k,
  };
}
