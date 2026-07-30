/**
 * Lightweight celestial WCS (TAN/SIN) from FITS header keyword list.
 * Expects header rows: [{key, value, comment}, ...] from /api/header.
 */

function hdrMap(headerList) {
  const m = {};
  for (const row of headerList || []) {
    if (row?.key) m[String(row.key).trim().toUpperCase()] = row.value;
  }
  return m;
}

function num(v, fallback = NaN) {
  const n = typeof v === 'number' ? v : parseFloat(v);
  return Number.isFinite(n) ? n : fallback;
}

function degToHms(raDeg) {
  let h = ((raDeg / 15) % 24 + 24) % 24;
  const hh = Math.floor(h);
  h = (h - hh) * 60;
  const mm = Math.floor(h);
  const ss = (h - mm) * 60;
  return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}:${ss.toFixed(3).padStart(6, '0')}`;
}

function degToDms(decDeg) {
  const sign = decDeg < 0 ? '-' : '+';
  let d = Math.abs(decDeg);
  const dd = Math.floor(d);
  d = (d - dd) * 60;
  const mm = Math.floor(d);
  const ss = (d - mm) * 60;
  return `${sign}${String(dd).padStart(2, '0')}:${String(mm).padStart(2, '0')}:${ss.toFixed(2).padStart(5, '0')}`;
}

/**
 * Build a simple 2D celestial WCS from header keywords.
 * Returns null if insufficient keywords.
 */
export function parseWcs(headerList) {
  const h = hdrMap(headerList);
  const crval1 = num(h.CRVAL1);
  const crval2 = num(h.CRVAL2);
  const crpix1 = num(h.CRPIX1, 1);
  const crpix2 = num(h.CRPIX2, 1);
  if (!Number.isFinite(crval1) || !Number.isFinite(crval2)) return null;

  let cd11; let cd12; let cd21; let cd22;
  if (h.CD1_1 != null || h.CD2_2 != null) {
    cd11 = num(h.CD1_1, 0);
    cd12 = num(h.CD1_2, 0);
    cd21 = num(h.CD2_1, 0);
    cd22 = num(h.CD2_2, 0);
  } else {
    const cdelt1 = num(h.CDELT1, NaN);
    const cdelt2 = num(h.CDELT2, NaN);
    if (!Number.isFinite(cdelt1) || !Number.isFinite(cdelt2)) return null;
    const pc11 = num(h.PC1_1, 1);
    const pc12 = num(h.PC1_2, 0);
    const pc21 = num(h.PC2_1, 0);
    const pc22 = num(h.PC2_2, 1);
    cd11 = cdelt1 * pc11;
    cd12 = cdelt1 * pc12;
    cd21 = cdelt2 * pc21;
    cd22 = cdelt2 * pc22;
  }

  const ctype1 = String(h.CTYPE1 || 'RA---TAN').toUpperCase();
  const projection = ctype1.includes('SIN') ? 'SIN' : 'TAN';
  const pixelScale = (Math.abs(cd11) + Math.abs(cd22)) / 2 * 3600; // arcsec

  return {
    crval1, crval2, crpix1, crpix2,
    cd11, cd12, cd21, cd22,
    projection,
    pixelScale,
  };
}

/** Pixel (0-based array coords) → RA/Dec degrees. */
export function pixToWorld(wcs, x, y) {
  if (!wcs) return null;
  // FITS CRPIX is 1-based
  const dx = (x + 1) - wcs.crpix1;
  const dy = (y + 1) - wcs.crpix2;
  const xi = (wcs.cd11 * dx + wcs.cd12 * dy) * (Math.PI / 180);
  const eta = (wcs.cd21 * dx + wcs.cd22 * dy) * (Math.PI / 180);
  const ra0 = wcs.crval1 * (Math.PI / 180);
  const dec0 = wcs.crval2 * (Math.PI / 180);

  let ra; let dec;
  if (wcs.projection === 'SIN') {
    const rho = Math.hypot(xi, eta);
    const c = Math.asin(Math.min(1, rho));
    if (rho < 1e-12) {
      ra = ra0;
      dec = dec0;
    } else {
      dec = Math.asin(Math.cos(c) * Math.sin(dec0) + (eta * Math.sin(c) * Math.cos(dec0)) / rho);
      ra = ra0 + Math.atan2(xi * Math.sin(c), rho * Math.cos(dec0) * Math.cos(c) - eta * Math.sin(dec0) * Math.sin(c));
    }
  } else {
    // TAN
    const r = Math.hypot(xi, eta);
    const c = Math.atan(r);
    if (r < 1e-12) {
      ra = ra0;
      dec = dec0;
    } else {
      dec = Math.asin(Math.cos(c) * Math.sin(dec0) + (eta * Math.sin(c) * Math.cos(dec0)) / r);
      ra = ra0 + Math.atan2(xi * Math.sin(c), r * Math.cos(dec0) * Math.cos(c) - eta * Math.sin(dec0) * Math.sin(c));
    }
  }
  let raDeg = (ra * 180) / Math.PI;
  const decDeg = (dec * 180) / Math.PI;
  raDeg = ((raDeg % 360) + 360) % 360;
  return { ra: raDeg, dec: decDeg, raStr: degToHms(raDeg), decStr: degToDms(decDeg) };
}

export function formatOffsetArcsec(dxPix, dyPix, pixelScale) {
  if (!pixelScale) return null;
  return {
    x: dxPix * pixelScale,
    y: dyPix * pixelScale,
  };
}

/** Nice tick generator for axis labels. */
export function niceTicks(lo, hi, target = 5) {
  if (!(hi > lo)) return [lo];
  const span = hi - lo;
  const step0 = span / Math.max(target, 1);
  const mag = 10 ** Math.floor(Math.log10(step0));
  const norm = step0 / mag;
  let step;
  if (norm < 1.5) step = mag;
  else if (norm < 3) step = 2 * mag;
  else if (norm < 7) step = 5 * mag;
  else step = 10 * mag;
  const start = Math.ceil(lo / step) * step;
  const ticks = [];
  for (let v = start; v <= hi + step * 0.5; v += step) ticks.push(v);
  return ticks;
}

export { degToHms, degToDms };
