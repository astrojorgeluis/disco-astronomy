/** Disk ellipse from rim points (max 4). Ellipse passes through the vertices. */

/**
 * Fit ellipse so it passes through 3–4 rim points.
 * Uses PCA axes + radial scaling so points lie on the ellipse (LS for 4 pts).
 */
export function ellipseThroughPoints(points, pixelScale) {
  if (!points || points.length < 3) return null;
  const pts = points.slice(0, 4);
  const n = pts.length;

  let cx = 0;
  let cy = 0;
  if (n === 4) {
    // Prefer diagonal intersection for a quad
    const mid1x = (pts[0].x + pts[2].x) / 2;
    const mid1y = (pts[0].y + pts[2].y) / 2;
    const mid2x = (pts[1].x + pts[3].x) / 2;
    const mid2y = (pts[1].y + pts[3].y) / 2;
    cx = (mid1x + mid2x) / 2;
    cy = (mid1y + mid2y) / 2;
  } else {
    for (const p of pts) { cx += p.x; cy += p.y; }
    cx /= n;
    cy /= n;
  }

  let mxx = 0;
  let myy = 0;
  let mxy = 0;
  for (const p of pts) {
    const dx = p.x - cx;
    const dy = p.y - cy;
    mxx += dx * dx;
    myy += dy * dy;
    mxy += dx * dy;
  }
  mxx /= n;
  myy /= n;
  mxy /= n;

  const tmp = Math.sqrt(((mxx - myy) / 2) ** 2 + mxy ** 2);
  const l1 = (mxx + myy) / 2 + tmp;
  const l2 = Math.max((mxx + myy) / 2 - tmp, 1e-12);
  let ang = 0.5 * Math.atan2(2 * mxy, mxx - myy); // rad, major axis direction
  const cos = Math.cos(ang);
  const sin = Math.sin(ang);

  // Project points into principal frame; solve a,b so x²/a² + y²/b² ≈ 1 for all
  let sumA = 0;
  let sumB = 0;
  let cnt = 0;
  for (const p of pts) {
    const dx = p.x - cx;
    const dy = p.y - cy;
    const xp = dx * cos + dy * sin;
    const yp = -dx * sin + dy * cos;
    // For unit ellipse scaled by (a,b): need a,b with xp²/a² + yp²/b² = 1
    // Use aspect from eigenvalues, then scale to pass through this point
    const aspect = Math.sqrt(l1 / l2); // a/b
    // xp²/(s*aspect)² + yp²/s² = 1  => s² = yp² + xp²/aspect²
    const s2 = yp * yp + (xp * xp) / (aspect * aspect);
    if (s2 > 1e-12) {
      const s = Math.sqrt(s2);
      sumB += s;
      sumA += s * aspect;
      cnt += 1;
    }
  }
  if (!cnt) return null;
  const a = sumA / cnt; // semi-major in pixels
  const b = sumB / cnt; // semi-minor in pixels

  // DISCO PA: position angle of the major axis, East of North (East = -x),
  // so a major axis at angle `ang` CCW from +x (array coords) means PA = ang - 90.
  const pa = (((ang * 180) / Math.PI - 90) % 180 + 180) % 180;
  const ratio = Math.min(a, b) / Math.max(a, b);
  const incl = Math.acos(Math.min(1, Math.max(0, ratio))) * (180 / Math.PI);
  const rout = Math.min(2, Math.max(0.05, Math.max(a, b) * (pixelScale || 0.03)));

  return { cx, cy, pa, incl, rout, a, b };
}

/** @deprecated use ellipseThroughPoints */
export function ellipseFromPolygon(points, pixelScale) {
  return ellipseThroughPoints(points, pixelScale);
}
