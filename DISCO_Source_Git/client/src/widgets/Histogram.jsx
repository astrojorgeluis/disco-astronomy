import React, { useMemo } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceLine,
} from 'recharts';
import useSessionStore from '../state/session';
import useVizStore from '../state/viz';

function fmt(v) {
  if (!Number.isFinite(v)) return '—';
  const a = Math.abs(v);
  if (a !== 0 && (a < 1e-2 || a >= 1e4)) return v.toExponential(2);
  return v.toPrecision(4);
}

/**
 * Pixel-value histogram for the active image.
 * Shows how many pixels fall in each intensity bin, plus stretch markers.
 */
export default function Histogram() {
  const rasterMeta = useSessionStore((s) => s.rasterMeta);
  const viz = useVizStore();
  const stats = rasterMeta?.stats;
  const limits = useVizStore((s) => s.limitsFromStats)(stats);

  const data = useMemo(() => {
    const hist = stats?.histogram;
    if (!hist?.counts?.length || !hist?.edges?.length) return [];
    const { counts, edges } = hist;
    return counts.map((count, i) => ({
      x: (edges[i] + edges[i + 1]) / 2,
      lo: edges[i],
      hi: edges[i + 1],
      count,
    }));
  }, [stats]);

  if (!stats) {
    return (
      <div style={{ padding: 12, color: 'var(--disco-text-muted)' }}>
        Load a FITS image to see its intensity distribution.
      </div>
    );
  }

  return (
    <div style={{ padding: 8, height: '100%', display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div className="compact-label">Pixel intensity histogram</div>
      <div style={{ fontSize: 10, color: 'var(--disco-text-muted)', lineHeight: 1.35 }}>
        How many pixels have each brightness value (from min to 99.9th percentile).
        Dashed lines mark the current display stretch.
      </div>

      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px 10px',
        fontSize: 11,
      }} className="disco-numeric">
        <span>min {fmt(stats.min)}</span>
        <span>max {fmt(stats.max)}</span>
        <span>median {fmt(stats.median)}</span>
        <span>99.5% {fmt(stats.p995)}</span>
      </div>

      <div style={{ flex: 1, minHeight: 100 }}>
        {data.length ? (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
              <CartesianGrid stroke="var(--disco-grid)" strokeDasharray="3 3" />
              <XAxis
                dataKey="x"
                tick={{ fontSize: 9, fill: 'var(--disco-text-muted)' }}
                tickFormatter={(v) => fmt(v)}
                label={{ value: 'Pixel value', position: 'insideBottom', offset: -2, fontSize: 9, fill: 'var(--disco-text-muted)' }}
              />
              <YAxis
                tick={{ fontSize: 9, fill: 'var(--disco-text-muted)' }}
                width={44}
                allowDecimals={false}
                label={{ value: 'Count', angle: -90, position: 'insideLeft', offset: 8, fontSize: 9, fill: 'var(--disco-text-muted)' }}
              />
              <Tooltip
                contentStyle={{
                  fontSize: 11,
                  background: 'var(--disco-bg-panel)',
                  border: '1px solid var(--disco-border)',
                  color: 'var(--disco-text)',
                }}
                formatter={(count) => [count, 'pixels']}
                labelFormatter={(_, payload) => {
                  const row = payload?.[0]?.payload;
                  return row ? `${fmt(row.lo)} … ${fmt(row.hi)}` : '';
                }}
              />
              {Number.isFinite(limits?.vmin) && (
                <ReferenceLine x={limits.vmin} stroke="var(--disco-warning)" strokeDasharray="4 3" />
              )}
              {Number.isFinite(limits?.vmax) && (
                <ReferenceLine x={limits.vmax} stroke="var(--disco-warning)" strokeDasharray="4 3" />
              )}
              <Bar dataKey="count" fill="var(--disco-accent)" name="pixels" />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div style={{ padding: 12, color: 'var(--disco-text-muted)', fontSize: 11 }}>
            Histogram bins are not available yet — reload the image.
          </div>
        )}
      </div>

      <div style={{ fontSize: 10, color: 'var(--disco-text-muted)' }}>
        Display stretch: {fmt(limits?.vmin)} – {fmt(limits?.vmax)}
        {viz.limitMode ? ` (${viz.limitMode})` : ''}
      </div>
    </div>
  );
}
