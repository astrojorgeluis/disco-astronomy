import React, { useMemo } from 'react';
import { getColormapLUT } from './colormaps';

/** Vertical colorbar on the right of the viewer. */
export default function Colorbar({ vmin, vmax, cmap = 'inferno', invert = false }) {
  const url = useMemo(() => {
    const lut = getColormapLUT(cmap, invert);
    const c = document.createElement('canvas');
    c.width = 1;
    c.height = 256;
    const ctx = c.getContext('2d');
    const img = ctx.createImageData(1, 256);
    for (let i = 0; i < 256; i++) {
      const j = 255 - i;
      img.data[i * 4] = lut[j * 4];
      img.data[i * 4 + 1] = lut[j * 4 + 1];
      img.data[i * 4 + 2] = lut[j * 4 + 2];
      img.data[i * 4 + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
    return c.toDataURL();
  }, [cmap, invert]);

  const fmt = (v) => {
    if (!Number.isFinite(v)) return '—';
    const a = Math.abs(v);
    if (a === 0) return '0';
    if (a >= 100 || a < 0.01) return v.toExponential(2);
    return v.toPrecision(3);
  };

  return (
    <div style={{
      position: 'absolute', right: 6, top: 24, bottom: 28, width: 36,
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      pointerEvents: 'none', gap: 2,
    }}>
      <span className="disco-numeric" style={{ fontSize: 9, color: 'var(--disco-text-muted)' }}>{fmt(vmax)}</span>
      <div style={{
        flex: 1, width: 12, border: '1px solid var(--disco-border)', borderRadius: 2,
        backgroundImage: `url(${url})`, backgroundSize: '100% 100%',
      }} />
      <span className="disco-numeric" style={{ fontSize: 9, color: 'var(--disco-text-muted)' }}>{fmt(vmin)}</span>
    </div>
  );
}
