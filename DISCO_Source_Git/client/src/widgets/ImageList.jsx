import React from 'react';
import { Button, HTMLTable, Radio, RadioGroup } from '@blueprintjs/core';
import useSessionStore from '../state/session';
import useViewportStore from '../state/viewport';
import useRegionsStore from '../state/regions';

export default function ImageList() {
  const images = useSessionStore((s) => s.images);
  const activeImageId = useSessionStore((s) => s.activeImageId);
  const setActiveImage = useSessionStore((s) => s.setActiveImage);
  const removeImage = useSessionStore((s) => s.removeImage);
  const viewMode = useSessionStore((s) => s.viewMode);
  const setViewMode = useSessionStore((s) => s.setViewMode);
  const regions = useRegionsStore((s) => s.regions);
  const selectedRegionId = useRegionsStore((s) => s.selectedRegionId);
  const setSelectedRegionId = useRegionsStore((s) => s.setSelectedRegionId);
  const removeRegion = useRegionsStore((s) => s.removeRegion);
  const sliceLine = useRegionsStore((s) => s.sliceLine);
  const setSliceLine = useRegionsStore((s) => s.setSliceLine);
  const matchXY = useViewportStore((s) => s.matchXY);
  const setMatchXY = useViewportStore((s) => s.setMatchXY);

  return (
    <div style={{ padding: 8, height: '100%', display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div className="compact-label">Image list</div>
      <div className="custom-scroll" style={{ flex: 1, overflow: 'auto' }}>
        <HTMLTable compact striped interactive style={{ width: '100%', fontSize: 11 }}>
          <thead>
            <tr><th>#</th><th>Image</th><th>Shape</th><th /></tr>
          </thead>
          <tbody>
            {images.map((img, i) => (
              <tr
                key={img.id}
                style={{ background: img.id === activeImageId ? 'var(--disco-accent-soft)' : undefined, cursor: 'pointer' }}
                onClick={() => setActiveImage(img.id)}
              >
                <td>{i}</td>
                <td>{img.filename}</td>
                <td className="disco-numeric">{img.shape?.join('×')}</td>
                <td>
                  <Button minimal small icon="cross" onClick={(e) => { e.stopPropagation(); removeImage(img.id); }} />
                </td>
              </tr>
            ))}
            {!images.length && (
              <tr><td colSpan={4} style={{ color: 'var(--disco-text-muted)' }}>No images loaded</td></tr>
            )}
          </tbody>
        </HTMLTable>

        <div className="compact-label" style={{ marginTop: 10 }}>Regions</div>
        <HTMLTable compact striped style={{ width: '100%', fontSize: 11 }}>
          <tbody>
            {regions.map((r) => (
              <tr
                key={r.id}
                style={{ background: r.id === selectedRegionId ? 'var(--disco-accent-soft)' : undefined, cursor: 'pointer' }}
                onClick={() => setSelectedRegionId(r.id)}
              >
                <td style={{ color: r.color }}>●</td>
                <td>{r.name}</td>
                <td>{r.type}</td>
                <td>
                  <Button minimal small icon="cross" onClick={(e) => { e.stopPropagation(); removeRegion(r.id); }} />
                </td>
              </tr>
            ))}
            {sliceLine && (
              <tr style={{ cursor: 'default' }}>
                <td style={{ color: 'var(--disco-roi-alt)' }}>／</td>
                <td>Slice line</td>
                <td className="disco-numeric" style={{ fontSize: 10 }}>
                  ({sliceLine.x0.toFixed(0)},{sliceLine.y0.toFixed(0)})→({sliceLine.x1.toFixed(0)},{sliceLine.y1.toFixed(0)})
                </td>
                <td>
                  <Button minimal small icon="cross" onClick={() => setSliceLine(null)} />
                </td>
              </tr>
            )}
            {!regions.length && !sliceLine && (
              <tr><td colSpan={4} style={{ color: 'var(--disco-text-muted)' }}>No regions</td></tr>
            )}
          </tbody>
        </HTMLTable>
      </div>

      <div style={{
        display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap',
        borderTop: '1px solid var(--disco-border)', paddingTop: 6, minHeight: 28,
      }}>
        <RadioGroup
          inline
          selectedValue={viewMode}
          onChange={(e) => setViewMode(e.currentTarget.value)}
          style={{ margin: 0 }}
        >
          <Radio label="Individual" value="single" style={{ marginBottom: 0 }} />
          <Radio label="Mosaico" value="mosaic" style={{ marginBottom: 0 }} />
        </RadioGroup>
        {viewMode === 'mosaic' && (
          <label
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              fontSize: 14, lineHeight: '30px', margin: 0, cursor: 'pointer',
              color: 'var(--disco-text)',
            }}
          >
            <input
              type="checkbox"
              checked={matchXY}
              onChange={(e) => {
                const on = e.target.checked;
                setMatchXY(on);
                if (on) useViewportStore.getState().setMosaicView({ offsetX: 0, offsetY: 0, k: 0 });
              }}
              style={{ margin: 0 }}
            />
            Matching XY
          </label>
        )}
        {images.length >= 4 && (
          <span style={{ color: 'var(--disco-warning)', fontSize: 10 }}>Max 4 images in RAM</span>
        )}
      </div>
    </div>
  );
}
