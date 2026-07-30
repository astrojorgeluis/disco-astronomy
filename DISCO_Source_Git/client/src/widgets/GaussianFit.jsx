import React, { useMemo, useState } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceArea, ReferenceLine,
} from 'recharts';
import { Button, ControlGroup, NumericInput, FormGroup } from '@blueprintjs/core';
import useSessionStore from '../state/session';

/** Numeric field that keeps intermediate decimals while typing (Blueprint quirk). */
function DecimalField({ label, value, onCommit }) {
  const [draft, setDraft] = useState(null); // null → show committed value
  const display = draft === null ? String(value ?? '') : draft;

  const commit = () => {
    const raw = draft === null ? String(value ?? '') : draft;
    const v = parseFloat(raw);
    setDraft(null);
    if (Number.isFinite(v)) onCommit(v);
  };

  return (
    <FormGroup label={label} style={{ flex: 1, margin: 0 }}>
      <NumericInput
        fill
        small
        buttonPosition="none"
        stepSize={0.01}
        minorStepSize={0.001}
        majorStepSize={0.1}
        value={display}
        onFocus={() => setDraft(String(value ?? ''))}
        onValueChange={(_n, s) => setDraft(s)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') e.currentTarget.blur();
        }}
      />
    </FormGroup>
  );
}

export default function GaussianFit() {
  const fit = useSessionStore((s) => s.fitStats);
  const profile = useSessionStore((s) => s.profileData);
  const params = useSessionStore((s) => s.params);
  const setParams = useSessionStore((s) => s.setParams);
  const probe = useSessionStore((s) => s.probe);

  const model = useMemo(() => {
    if (!profile?.radius?.length) return [];
    const I = profile.intensity || profile.tb || [];
    const rows = profile.radius.map((r, i) => ({ r, data: I[i], model: null }));
    if (fit && params.fit_rmax > params.fit_rmin) {
      const { peak_radius: x0, fwhm, peak_intensity: a } = fit;
      const sigma = Math.max((fwhm || 1) / (2 * Math.sqrt(2 * Math.log(2))), 1e-6);
      for (const row of rows) {
        row.model = a * Math.exp(-((row.r - x0) ** 2) / (2 * sigma ** 2));
      }
    }
    return rows;
  }, [fit, profile, params.fit_rmin, params.fit_rmax]);

  const rMax = profile?.radius?.length ? profile.radius[profile.radius.length - 1] : 1;

  if (!profile?.radius?.length) {
    return (
      <div style={{ padding: 12, color: 'var(--disco-text-muted)' }}>
        Run the pipeline to fit a Gaussian ring to the radial profile.
      </div>
    );
  }

  return (
    <div style={{ padding: 8, height: '100%', display: 'flex', flexDirection: 'column', gap: 6, background: 'var(--disco-chart-bg)' }}>
      <div className="compact-label">Gaussian ring fit</div>
      <div style={{ fontSize: 10, color: 'var(--disco-text-muted)' }}>
        Set the radial window used for the ring fit, then re-run the pipeline.
      </div>
      <ControlGroup fill>
        <DecimalField
          label='rmin (")'
          value={params.fit_rmin}
          onCommit={(v) => setParams({ fit_rmin: v })}
        />
        <DecimalField
          label='rmax (")'
          value={params.fit_rmax}
          onCommit={(v) => setParams({ fit_rmax: v })}
        />
        <Button
          small
          text="Auto"
          style={{ alignSelf: 'flex-end', marginBottom: 2 }}
          onClick={() => setParams({ fit_rmin: rMax * 0.15, fit_rmax: rMax * 0.7 })}
        />
      </ControlGroup>

      {fit && params.fit_rmax > params.fit_rmin ? (
        <div style={{ display: 'flex', gap: 12, fontSize: 11 }} className="disco-numeric">
          <span>R<sub>peak</sub>={fit.peak_radius?.toFixed(3)}&quot;</span>
          <span>FWHM={fit.fwhm?.toFixed(3)}&quot;</span>
          <span>I<sub>peak</sub>={Number(fit.peak_intensity).toExponential(3)}</span>
        </div>
      ) : (
        <div style={{ fontSize: 10, color: 'var(--disco-text-muted)' }}>
          No fit yet — choose rmin &lt; rmax and run again.
        </div>
      )}

      <div style={{ flex: 1, minHeight: 100 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={model} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
            <CartesianGrid stroke="var(--disco-grid)" strokeDasharray="3 3" />
            <XAxis dataKey="r" tick={{ fontSize: 10, fill: 'var(--disco-text-muted)' }} />
            <YAxis tick={{ fontSize: 10, fill: 'var(--disco-text-muted)' }} width={48} />
            <Tooltip
              contentStyle={{
                fontSize: 11,
                background: 'var(--disco-bg-panel)',
                border: '1px solid var(--disco-border)',
                color: 'var(--disco-text)',
              }}
            />
            {params.fit_rmax > params.fit_rmin && (
              <ReferenceArea x1={params.fit_rmin} x2={params.fit_rmax} fill="var(--disco-accent-soft)" />
            )}
            {Number.isFinite(probe?.radius) && (
              <ReferenceLine x={probe.radius} stroke="var(--disco-warning)" strokeDasharray="3 3" label={{ value: 'cursor', fontSize: 9, fill: 'var(--disco-warning)' }} ifOverflow="extendDomain" />
            )}
            <Line type="monotone" dataKey="data" stroke="var(--disco-chart-1)" dot={false} strokeWidth={1} name="Profile" />
            {fit && <Line type="monotone" dataKey="model" stroke="var(--disco-chart-3)" dot={false} strokeWidth={1.5} name="Gaussian" />}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
