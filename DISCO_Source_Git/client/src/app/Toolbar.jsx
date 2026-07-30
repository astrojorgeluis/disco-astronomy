import React, { useState } from 'react';
import {
  Button, ButtonGroup, Dialog, DialogBody, DialogFooter,
  Divider, FormGroup, HTMLSelect, NumericInput,
} from '@blueprintjs/core';
import useRegionsStore from '../state/regions';
import useSessionStore from '../state/session';
import useVizStore from '../state/viz';
import { COLORMAP_NAMES } from '../viewer/colormaps';
import MatplotlibDialog from '../widgets/MatplotlibDialog';

export default function Toolbar({ onOptimize, running }) {
  const activeTool = useRegionsStore((s) => s.activeTool);
  const regionTool = useRegionsStore((s) => s.regionTool);
  const setActiveTool = useRegionsStore((s) => s.setActiveTool);
  const setRegionTool = useRegionsStore((s) => s.setRegionTool);
  const viz = useVizStore();
  const setViz = useVizStore((s) => s.setViz);
  const applyStats = useVizStore((s) => s.applyStats);
  const setCustomLimits = useVizStore((s) => s.setCustomLimits);
  const [mplOpen, setMplOpen] = useState(false);
  const [customOpen, setCustomOpen] = useState(false);
  const [draftMin, setDraftMin] = useState('');
  const [draftMax, setDraftMax] = useState('');

  const applyPreset = (mode) => {
    applyStats(null, mode);
    if (mode === 'minmax') setViz({ stretch: 'linear' });
  };

  const openCustom = () => {
    const cur = useVizStore.getState();
    let lo = cur.vmin;
    let hi = cur.vmax;
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) {
      const stats = useSessionStore.getState().rasterMeta?.stats;
      const derived = cur.limitsFromStats(stats);
      lo = derived.vmin;
      hi = derived.vmax;
    }
    setDraftMin(Number.isFinite(lo) ? String(lo) : '');
    setDraftMax(Number.isFinite(hi) ? String(hi) : '');
    setCustomOpen(true);
  };

  const applyCustom = () => {
    if (setCustomLimits(draftMin, draftMax)) setCustomOpen(false);
  };

  return (
    <div className="disco-toolbar">
      <ButtonGroup minimal>
        <Button icon="hand-up" active={activeTool === 'pan'} title="Pan" onClick={() => setActiveTool('pan')} />
        <Button icon="select" active={activeTool === 'select'} title="Select / Edit shapes" onClick={() => setActiveTool('select')} />
        <Button
          icon="layout-circle"
          active={activeTool === 'radial'}
          title="Radial probe (fixed center)"
          onClick={() => setActiveTool('radial')}
        />
      </ButtonGroup>
      <Divider />
      <ButtonGroup minimal>
        <Button icon="widget" active={regionTool === 'rectangle'} title="Box ROI" onClick={() => setRegionTool(regionTool === 'rectangle' ? null : 'rectangle')} />
        <Button icon="circle" active={regionTool === 'ellipse'} title="Ellipse ROI" onClick={() => setRegionTool(regionTool === 'ellipse' ? null : 'ellipse')} />
        <Button icon="polygon-filter" active={regionTool === 'polygon'} title="Polygon ROI" onClick={() => setRegionTool(regionTool === 'polygon' ? null : 'polygon')} />
        <Button icon="doughnut-chart" active={regionTool === 'annulus'} title="Annulus ROI" onClick={() => setRegionTool(regionTool === 'annulus' ? null : 'annulus')} />
        <Button icon="minus" active={regionTool === 'line'} title="Slice line" onClick={() => setRegionTool(regionTool === 'line' ? null : 'line')} />
      </ButtonGroup>
      <Divider />
      <HTMLSelect
        minimal
        value={viz.cmap}
        onChange={(e) => setViz({ cmap: e.target.value })}
        options={COLORMAP_NAMES.filter((n) => n !== 'grey')}
      />
      <HTMLSelect
        minimal
        value={viz.stretch}
        onChange={(e) => setViz({ stretch: e.target.value })}
        options={['linear', 'asinh', 'log', 'sqrt']}
      />
      <ButtonGroup minimal>
        <Button small text="min/max" active={viz.limitMode === 'minmax'} onClick={() => applyPreset('minmax')} />
        <Button small text="99.5%" active={viz.limitMode === 'p995'} onClick={() => applyPreset('p995')} />
        <Button small text="99.9%" active={viz.limitMode === 'p999'} onClick={() => applyPreset('p999')} />
        <Button small text="Custom" active={viz.limitMode === 'custom'} onClick={openCustom} />
        <Button small icon="contrast" active={viz.invert} onClick={() => setViz({ invert: !viz.invert })} title="Invert colormap" />
      </ButtonGroup>
      <div style={{ flex: 1 }} />
      <ButtonGroup>
        <Button
          small
          text="Matplotlib"
          icon="media"
          onClick={() => setMplOpen(true)}
          title="Export scientific plot via Matplotlib"
        />
        <Button
          small
          text="Optimize geometry"
          icon="predictive-analysis"
          onClick={onOptimize}
          disabled={running}
          loading={running}
        />
      </ButtonGroup>
      <MatplotlibDialog isOpen={mplOpen} onClose={() => setMplOpen(false)} />
      <Dialog
        isOpen={customOpen}
        onClose={() => setCustomOpen(false)}
        title="Custom scale"
        style={{ width: 320 }}
      >
        <DialogBody>
          <FormGroup label="vmin" labelFor="custom-vmin" style={{ marginBottom: 12 }}>
            <NumericInput
              id="custom-vmin"
              fill
              allowNumericCharactersOnly={false}
              value={draftMin}
              onValueChange={(_n, s) => setDraftMin(s)}
              onButtonClick={(_n, s) => setDraftMin(s)}
              stepSize={0.1}
              minorStepSize={0.01}
              majorStepSize={1}
            />
          </FormGroup>
          <FormGroup label="vmax" labelFor="custom-vmax" style={{ marginBottom: 0 }}>
            <NumericInput
              id="custom-vmax"
              fill
              allowNumericCharactersOnly={false}
              value={draftMax}
              onValueChange={(_n, s) => setDraftMax(s)}
              onButtonClick={(_n, s) => setDraftMax(s)}
              stepSize={0.1}
              minorStepSize={0.01}
              majorStepSize={1}
            />
          </FormGroup>
        </DialogBody>
        <DialogFooter
          actions={(
            <>
              <Button text="Cancel" onClick={() => setCustomOpen(false)} />
              <Button intent="primary" text="Apply" onClick={applyCustom} />
            </>
          )}
        />
      </Dialog>
    </div>
  );
}
