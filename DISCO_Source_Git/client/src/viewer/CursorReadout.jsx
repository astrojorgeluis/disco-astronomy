import React from 'react';
import useSessionStore from '../state/session';
import { pixToWorld, parseWcs } from './wcs';

const READOUT_STYLE = {
  borderTop: 'none',
  borderBottom: '1px solid var(--disco-border)',
  height: 22,
  flexShrink: 0,
  overflow: 'hidden',
};

/** Cursor readout — WCS + pixel + value + deprojected radius. */
export default function CursorReadout() {
  const probe = useSessionStore((s) => s.probe);
  const headerInfo = useSessionStore((s) => s.headerInfo);
  const pixelScale = useSessionStore((s) => s.pixelScale);
  const wcs = parseWcs(headerInfo);

  if (!probe || probe.x == null) {
    return (
      <div className="disco-status" style={READOUT_STYLE}>
        <span>Use the Radial tool and move the cursor over the image</span>
      </div>
    );
  }

  let wcsStr = '—';
  if (wcs && Number.isFinite(probe.x) && Number.isFinite(probe.y)) {
    const w = pixToWorld(wcs, probe.x, probe.y);
    if (w) wcsStr = `(${w.raStr}, ${w.decStr})`;
  } else if (probe.ra && probe.dec) {
    wcsStr = `(${probe.ra}, ${probe.dec})`;
  }

  const val = probe.pending
    ? '…'
    : (probe.value == null ? '—' : Number(probe.value).toExponential(5));

  const rStr = Number.isFinite(probe.radius) ? `${probe.radius.toFixed(3)}"` : '—';

  return (
    <div className="disco-status" style={READOUT_STYLE}>
      <span>
        WCS: {wcsStr}; Image: ({probe.x.toFixed(1)}, {probe.y.toFixed(1)});
        Value: {val}; R<sub>deproj</sub>: {rStr}; Scale: {pixelScale?.toPrecision?.(3)}&quot;/pix
      </span>
    </div>
  );
}
