import React, { useEffect, useMemo, useState } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import useRegionsStore from '../state/regions';
import useSessionStore from '../state/session';
import { api } from '../api/client';

/**
 * Intensity along a user-drawn slice line.
 * Samples the active image via the probe API at points along the segment.
 */
export default function SliceProfile() {
  const sliceLine = useRegionsStore((s) => s.sliceLine);
  const activeImageId = useSessionStore((s) => s.activeImageId);
  const pixelScale = useSessionStore((s) => s.pixelScale);
  const product = 'data';
  const [samples, setSamples] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!sliceLine || !activeImageId) {
        setSamples([]);
        return;
      }
      setLoading(true);
      try {
        const n = 64;
        const pts = [];
        for (let i = 0; i < n; i += 1) {
          const t = i / (n - 1);
          pts.push({
            x: sliceLine.x0 + (sliceLine.x1 - sliceLine.x0) * t,
            y: sliceLine.y0 + (sliceLine.y1 - sliceLine.y0) * t,
            t,
          });
        }
        // Probe in small batches to avoid flooding the server
        const out = [];
        const batch = 8;
        for (let i = 0; i < pts.length; i += batch) {
          const chunk = pts.slice(i, i + batch);
          const results = await Promise.all(
            chunk.map((p) => api.probe({
              x: p.x, y: p.y, product, image_id: activeImageId,
            }).catch(() => null)),
          );
          if (cancelled) return;
          results.forEach((r, j) => {
            const p = chunk[j];
            const distPix = Math.hypot(p.x - sliceLine.x0, p.y - sliceLine.y0);
            out.push({
              offset: distPix * (pixelScale || 0.03),
              I: r && Number.isFinite(r.value) ? r.value : null,
            });
          });
        }
        if (!cancelled) setSamples(out);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [sliceLine, activeImageId, pixelScale, product]);

  const data = useMemo(
    () => samples.filter((d) => Number.isFinite(d.I)),
    [samples],
  );

  if (!sliceLine) {
    return (
      <div style={{ padding: 12, color: 'var(--disco-text-muted)' }}>
        Draw a slice line with the − tool on the toolbar to plot intensity along that cut.
      </div>
    );
  }

  const lenPix = Math.hypot(sliceLine.x1 - sliceLine.x0, sliceLine.y1 - sliceLine.y0);
  const lenArc = lenPix * (pixelScale || 0.03);

  return (
    <div style={{ padding: 8, height: '100%', display: 'flex', flexDirection: 'column', gap: 4, background: 'var(--disco-chart-bg)' }}>
      <div className="compact-label">Slice profile</div>
      <div style={{ fontSize: 10, color: 'var(--disco-text-muted)' }}>
        Length {lenArc.toFixed(3)}&quot; · {loading ? 'sampling…' : `${data.length} samples`}
      </div>
      <div style={{ flex: 1, minHeight: 100 }}>
        {data.length ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
              <CartesianGrid stroke="var(--disco-grid)" strokeDasharray="3 3" />
              <XAxis
                dataKey="offset"
                tick={{ fontSize: 10, fill: 'var(--disco-text-muted)' }}
                label={{ value: 'Offset (")', position: 'insideBottom', offset: -2, fontSize: 10, fill: 'var(--disco-text-muted)' }}
              />
              <YAxis tick={{ fontSize: 10, fill: 'var(--disco-text-muted)' }} width={48} />
              <Tooltip
                contentStyle={{
                  fontSize: 11,
                  background: 'var(--disco-bg-panel)',
                  border: '1px solid var(--disco-border)',
                  color: 'var(--disco-text)',
                }}
              />
              <Line type="monotone" dataKey="I" stroke="var(--disco-roi-alt)" dot={false} strokeWidth={1.5} name="Intensity" />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div style={{ padding: 12, color: 'var(--disco-text-muted)', fontSize: 11 }}>
            {loading ? 'Sampling along the slice…' : 'No finite samples along this line.'}
          </div>
        )}
      </div>
    </div>
  );
}
