import React, { useMemo } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceLine,
} from 'recharts';
import useSessionStore from '../state/session';

const tickStyle = { fontSize: 10, fill: 'var(--disco-text-muted)' };
const tooltipStyle = {
  fontSize: 11,
  background: 'var(--disco-bg-panel)',
  border: '1px solid var(--disco-border)',
  color: 'var(--disco-text)',
};

export default function CumulativeFlux() {
  const profile = useSessionStore((s) => s.profileData);
  const probe = useSessionStore((s) => s.probe);

  const data = useMemo(() => {
    if (!profile?.radius?.length) return [];
    let acc = 0;
    const I = profile.intensity || profile.tb || [];
    return profile.radius.map((r, i) => {
      const dr = i === 0 ? r : r - profile.radius[i - 1];
      acc += (I[i] || 0) * 2 * Math.PI * Math.max(r, 0) * Math.max(dr, 0);
      return { r, flux: acc };
    });
  }, [profile]);

  if (!data.length) {
    return (
      <div style={{ padding: 12, color: 'var(--disco-text-muted)' }}>
        Cumulative flux will appear after you run the pipeline.
      </div>
    );
  }

  return (
    <div style={{ padding: 8, height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--disco-chart-bg)' }}>
      <div className="compact-label">Cumulative flux</div>
      <div style={{ flex: 1, minHeight: 100 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
            <CartesianGrid stroke="var(--disco-grid)" strokeDasharray="3 3" />
            <XAxis dataKey="r" tick={tickStyle} />
            <YAxis tick={tickStyle} width={48} />
            <Tooltip contentStyle={tooltipStyle} />
            {Number.isFinite(probe?.radius) && (
              <ReferenceLine
                x={probe.radius}
                stroke="var(--disco-warning)"
                strokeDasharray="3 3"
                label={{ value: 'cursor', fontSize: 9, fill: 'var(--disco-warning)' }}
                ifOverflow="extendDomain"
              />
            )}
            <Line type="monotone" dataKey="flux" stroke="var(--disco-chart-2)" dot={false} strokeWidth={1.5} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
