import React from 'react';
import { Button, FormGroup, NumericInput, Slider, Tag } from '@blueprintjs/core';
import useSessionStore from '../state/session';
import useRegionsStore from '../state/regions';

function CompactSlider({ label, value, min, max, step = 0.1, labelStep, onChange, unit = '' }) {
  return (
    <FormGroup
      label={label}
      labelInfo={<Tag minimal className="disco-numeric">{value.toFixed(step < 1 ? 2 : 1)}{unit}</Tag>}
      style={{ marginBottom: 6 }}
      className="disco-compact-fg"
    >
      <div style={{ padding: '0 8px' }}>
        <Slider
          min={min}
          max={max}
          stepSize={step}
          labelStepSize={labelStep ?? (max - min) / 2}
          value={Math.min(max, Math.max(min, value))}
          onChange={onChange}
          showTrackFill={false}
        />
      </div>
    </FormGroup>
  );
}

export default function RenderConfig({ onRun, running }) {
  const params = useSessionStore((s) => s.params);
  const setParams = useSessionStore((s) => s.setParams);
  const regionTool = useRegionsStore((s) => s.regionTool);
  const setRegionTool = useRegionsStore((s) => s.setRegionTool);
  const clearGeomPolyDraft = useRegionsStore((s) => s.clearGeomPolyDraft);

  const startGeomPoly = () => {
    useRegionsStore.getState().setGeomPolyDraft(null);
    setRegionTool('geomPoly');
  };

  return (
    <div style={{ padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 4, height: '100%', fontSize: 11 }}>
      <div className="compact-label" style={{ marginBottom: 2 }}>Geometry</div>

      <CompactSlider label="Inclination" value={params.incl} min={0} max={90} step={0.5} labelStep={45}
        unit="°" onChange={(v) => setParams({ incl: v })} />
      <CompactSlider label="Position angle" value={params.pa} min={0} max={180} step={0.5} labelStep={90}
        unit="°" onChange={(v) => setParams({ pa: v })} />
      <CompactSlider label="Outer radius" value={params.rout} min={0} max={2} step={0.01} labelStep={1}
        unit='"' onChange={(v) => setParams({ rout: v })} />

      <div style={{ display: 'flex', gap: 6, marginTop: 2 }}>
        <FormGroup label="cx" style={{ flex: 1, marginBottom: 4 }}>
          <NumericInput fill small value={params.cx} buttonPosition="none"
            onValueChange={(v) => Number.isFinite(v) && setParams({ cx: v })} />
        </FormGroup>
        <FormGroup label="cy" style={{ flex: 1, marginBottom: 4 }}>
          <NumericInput fill small value={params.cy} buttonPosition="none"
            onValueChange={(v) => Number.isFinite(v) && setParams({ cy: v })} />
        </FormGroup>
      </div>

      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 }}>
        <Button small icon="polygon-filter"
          active={regionTool === 'geomPoly'}
          text="Trace disk"
          onClick={startGeomPoly}
          title="Click up to 4 points on the disk rim — the ellipse passes through them"
        />
        {regionTool === 'geomPoly' && (
          <Button small text="Cancel" onClick={clearGeomPolyDraft} />
        )}
      </div>

      <div style={{ flex: 1, minHeight: 4 }} />
      <Button fill intent="primary" text="Run" icon="play" onClick={onRun} loading={running} />
    </div>
  );
}
