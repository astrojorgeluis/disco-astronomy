import React, { useState } from 'react';
import {
  Dialog, DialogBody, DialogFooter, Button, FormGroup, HTMLSelect,
  Checkbox, NumericInput, ControlGroup,
} from '@blueprintjs/core';
import { api } from '../api/client';
import useSessionStore from '../state/session';
import useVizStore from '../state/viz';
import { COLORMAP_NAMES } from '../viewer/colormaps';

const PRODUCT_OPTS = [
  { value: 'data', label: 'Data' },
  { value: 'deproj', label: 'Deprojected' },
  { value: 'polar', label: 'Polar' },
  { value: 'model', label: 'Model' },
  { value: 'residuals', label: 'Residuals' },
  { value: 'profile', label: 'Radial profile' },
];

export default function MatplotlibDialog({ isOpen, onClose }) {
  const activeImageId = useSessionStore((s) => s.activeImageId);
  const hasRunPipeline = useSessionStore((s) => s.hasRunPipeline);
  const viz = useVizStore();

  const [type, setType] = useState(viz.product || 'data');
  const [cmap, setCmap] = useState(viz.cmap || 'inferno');
  const [stretch, setStretch] = useState(viz.stretch || 'linear');
  const [contours, setContours] = useState(false);
  const [showBeam, setShowBeam] = useState(true);
  const [showColorbar, setShowColorbar] = useState(true);
  const [showAxes, setShowAxes] = useState(true);
  const [showGrid, setShowGrid] = useState(false);
  const [dpi, setDpi] = useState(150);
  const [format, setFormat] = useState('png');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const needsPipeline = type !== 'data' && type !== 'profile';
  const canRender = !!activeImageId && (!needsPipeline || hasRunPipeline);

  const handleRender = async () => {
    if (!canRender) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.renderPlot({
        image_id: activeImageId,
        type,
        cmap,
        stretch,
        contours,
        contour_levels: 5,
        show_beam: showBeam,
        show_colorbar: showColorbar,
        show_axes: showAxes,
        show_grid: showGrid,
        dpi,
        format,
      });
      setResult(data);
    } catch (e) {
      setError(String(e?.detail || e?.message || e));
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = () => {
    if (!result?.image) return;
    const a = document.createElement('a');
    a.href = result.image;
    a.download = `disco_${type}.${result.format || format}`;
    a.click();
  };

  return (
    <Dialog
      isOpen={isOpen}
      onClose={onClose}
      title="Matplotlib export"
      style={{ width: 640, maxWidth: '95vw' }}
    >
      <DialogBody>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <FormGroup label="Product" style={{ margin: 0 }}>
            <HTMLSelect
              fill
              value={type}
              options={PRODUCT_OPTS}
              onChange={(e) => setType(e.target.value)}
            />
          </FormGroup>
          <FormGroup label="Colormap" style={{ margin: 0 }}>
            <HTMLSelect
              fill
              value={cmap}
              options={COLORMAP_NAMES.filter((n) => n !== 'grey')}
              onChange={(e) => setCmap(e.target.value)}
            />
          </FormGroup>
          <FormGroup label="Stretch" style={{ margin: 0 }}>
            <HTMLSelect
              fill
              value={stretch}
              options={['linear', 'asinh', 'log', 'sqrt']}
              onChange={(e) => setStretch(e.target.value)}
            />
          </FormGroup>
          <FormGroup label="Format" style={{ margin: 0 }}>
            <HTMLSelect
              fill
              value={format}
              options={['png', 'pdf', 'svg']}
              onChange={(e) => setFormat(e.target.value)}
            />
          </FormGroup>
          <FormGroup label="DPI" style={{ margin: 0 }}>
            <NumericInput
              fill
              min={72}
              max={600}
              value={dpi}
              onValueChange={(v) => Number.isFinite(v) && setDpi(v)}
              buttonPosition="none"
            />
          </FormGroup>
        </div>

        <ControlGroup style={{ marginTop: 10, flexWrap: 'wrap', gap: 8 }}>
          <Checkbox checked={showAxes} label="Axes" onChange={(e) => setShowAxes(e.target.checked)} />
          <Checkbox checked={showColorbar} label="Colorbar" onChange={(e) => setShowColorbar(e.target.checked)} />
          <Checkbox checked={showBeam} label="Beam" onChange={(e) => setShowBeam(e.target.checked)} />
          <Checkbox checked={showGrid} label="Grid" onChange={(e) => setShowGrid(e.target.checked)} />
          <Checkbox checked={contours} label="Contours" onChange={(e) => setContours(e.target.checked)} />
        </ControlGroup>

        {error && (
          <div style={{ color: 'var(--disco-danger, #c23030)', fontSize: 12, marginTop: 8 }}>
            {error}
          </div>
        )}

        {result?.image && (result.format === 'png' || !result.format || result.image.startsWith('data:image/png')) && (
          <div style={{
            marginTop: 12, border: '1px solid var(--disco-border)', borderRadius: 2,
            background: '#fff', maxHeight: 360, overflow: 'auto', textAlign: 'center',
          }}>
            <img src={result.image} alt="matplotlib" style={{ maxWidth: '100%' }} />
          </div>
        )}
        {result?.image && result.format && result.format !== 'png' && (
          <div style={{ marginTop: 10, fontSize: 12, color: 'var(--disco-text-muted)' }}>
            Preview not available for {result.format.toUpperCase()} — use Download.
          </div>
        )}
      </DialogBody>
      <DialogFooter
        actions={(
          <>
            <Button text="Close" onClick={onClose} />
            <Button
              text="Download"
              icon="download"
              disabled={!result?.image}
              onClick={handleDownload}
            />
            <Button
              intent="primary"
              text="Render"
              icon="media"
              loading={loading}
              disabled={!canRender}
              onClick={handleRender}
            />
          </>
        )}
      />
    </Dialog>
  );
}
