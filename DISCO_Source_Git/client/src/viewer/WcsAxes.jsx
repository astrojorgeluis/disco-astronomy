import React, { useMemo } from 'react';
import { niceTicks, pixToWorld } from './wcs';
import { screenToImage } from './coords';

/** SVG WCS / arcsec axes overlaid on the viewer. */
export default function WcsAxes({ width, height, transform, imgW, imgH, wcs, pixelScale }) {
  const ticks = useMemo(() => {
    if (!width || !height || !imgW) return { x: [], y: [] };
    const bl = screenToImage(40, height - 20, transform, imgH);
    const tr = screenToImage(width - 20, 20, transform, imgH);
    const xLo = Math.min(bl.x, tr.x);
    const xHi = Math.max(bl.x, tr.x);
    const yLo = Math.min(bl.y, tr.y);
    const yHi = Math.max(bl.y, tr.y);
    return {
      x: niceTicks(xLo, xHi, 5),
      y: niceTicks(yLo, yHi, 5),
    };
  }, [width, height, transform, imgW, imgH]);

  const labelX = (ix) => {
    if (wcs) {
      const w = pixToWorld(wcs, ix, imgH / 2);
      return w ? w.raStr : ix.toFixed(0);
    }
    if (pixelScale) {
      const off = (ix - imgW / 2) * pixelScale;
      return `${off.toFixed(2)}"`;
    }
    return ix.toFixed(0);
  };

  const labelY = (iy) => {
    if (wcs) {
      const w = pixToWorld(wcs, imgW / 2, iy);
      return w ? w.decStr : iy.toFixed(0);
    }
    if (pixelScale) {
      const off = (iy - imgH / 2) * pixelScale;
      return `${off.toFixed(2)}"`;
    }
    return iy.toFixed(0);
  };

  const toScreen = (ix, iy) => ({
    x: ix * transform.k + transform.x,
    y: (imgH - iy) * transform.k + transform.y,
  });

  return (
    <svg
      width={width}
      height={height}
      style={{ position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'hidden' }}
    >
      {ticks.x.map((ix) => {
        const p = toScreen(ix, 0);
        if (p.x < 30 || p.x > width - 10) return null;
        return (
          <g key={`x${ix}`}>
            <line x1={p.x} y1={height - 18} x2={p.x} y2={height - 12} stroke="var(--disco-text-muted)" strokeWidth={1} />
            <text x={p.x} y={height - 4} textAnchor="middle" fill="var(--disco-text-muted)" fontSize={9} fontFamily="var(--disco-mono)">
              {labelX(ix)}
            </text>
          </g>
        );
      })}
      {ticks.y.map((iy) => {
        const p = toScreen(0, iy);
        if (p.y < 12 || p.y > height - 24) return null;
        return (
          <g key={`y${iy}`}>
            <line x1={12} y1={p.y} x2={18} y2={p.y} stroke="var(--disco-text-muted)" strokeWidth={1} />
            <text x={10} y={p.y + 3} textAnchor="end" fill="var(--disco-text-muted)" fontSize={9} fontFamily="var(--disco-mono)">
              {labelY(iy)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
