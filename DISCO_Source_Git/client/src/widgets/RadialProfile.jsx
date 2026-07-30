import React from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceArea, ReferenceLine,
} from 'recharts';
import useSessionStore from '../state/session';

const tickStyle = { fontSize: 10, fill: 'var(--disco-text-muted)' };
const tooltipStyle = {
  fontSize: 11,
  background: 'var(--disco-bg-panel)',
  border: '1px solid var(--disco-border)',
  color: 'var(--disco-text)',
};

export default function RadialProfile() {
  const profile = useSessionStore((s) => s.profileData);
  const params = useSessionStore((s) => s.params);
  const probe = useSessionStore((s) => s.probe);

  if (!profile?.radius?.length) {
    return (
      <div style={{ padding: 12, color: 'var(--disco-text-muted)' }}>
        Radial profile will appear after you run the pipeline.
      </div>
    );
  }

  const data = profile.radius.map((r, i) => ({
    r,
    I: profile.intensity?.[i] ?? profile.tb?.[i],
  }));

  return (
    <div style={{ padding: 8, height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--disco-chart-bg)' }}>
      <div className="compact-label">Radial profile</div>
      <div style={{ flex: 1, minHeight: 120 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
            <CartesianGrid stroke="var(--disco-grid)" strokeDasharray="3 3" />
            <XAxis
              dataKey="r"
              tick={tickStyle}
              label={{ value: 'R (")', position: 'insideBottom', offset: -2, fontSize: 10, fill: 'var(--disco-text-muted)' }}
            />
            <YAxis tick={tickStyle} width={48} />
            <Tooltip contentStyle={tooltipStyle} />
            {params.fit_rmax > params.fit_rmin && (
              <ReferenceArea x1={params.fit_rmin} x2={params.fit_rmax} fill="var(--disco-accent-soft)" />
            )}
            {Number.isFinite(probe?.radius) && (
              <ReferenceLine
                x={probe.radius}
                stroke="var(--disco-warning)"
                strokeDasharray="3 3"
                label={{ value: 'cursor', fontSize: 9, fill: 'var(--disco-warning)' }}
                ifOverflow="extendDomain"
              />
            )}
            <Line type="monotone" dataKey="I" stroke="var(--disco-chart-1)" dot={false} strokeWidth={1.5} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
