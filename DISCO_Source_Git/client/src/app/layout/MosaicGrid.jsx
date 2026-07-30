import React, { useMemo } from 'react';
import { HTMLSelect } from '@blueprintjs/core';
import ImageCanvas from '../../viewer/ImageCanvas';
import useSessionStore from '../../state/session';
import useVizStore from '../../state/viz';
import useViewportStore from '../../state/viewport';
import { MOSAIC_PRODUCT_IDS, productLabel } from '../../viewer/products';

function MosaicCell({ index }) {
  const images = useSessionStore((s) => s.images);
  const activeImageId = useSessionStore((s) => s.activeImageId);
  const headerInfo = useSessionStore((s) => s.headerInfo);
  const pixelScale = useSessionStore((s) => s.pixelScale);
  const viewerEpoch = useSessionStore((s) => s.viewerEpoch);
  const hasRunPipeline = useSessionStore((s) => s.hasRunPipeline);
  const params = useSessionStore((s) => s.params);
  const viz = useVizStore();
  const limitsOrStats = useVizStore((s) => s.limitsOrStats);
  const rasterMeta = useSessionStore((s) => s.rasterMeta);
  const limits = viz.autoLimits === false ? limitsOrStats(rasterMeta?.stats) : null;
  const source = useViewportStore((s) => s.mosaicSources[index]);
  const setMosaicSource = useViewportStore((s) => s.setMosaicSource);
  const activeMosaicCell = useViewportStore((s) => s.activeMosaicCell);
  const setActiveMosaicCell = useViewportStore((s) => s.setActiveMosaicCell);

  let product = 'data';
  let imageId = activeImageId;
  if (source.kind === 'product') {
    product = source.product === 'polar' ? 'data' : source.product;
    if (product !== 'data' && !hasRunPipeline) product = 'data';
  } else if (source.kind === 'file' && source.imageId) {
    imageId = source.imageId;
    product = 'data';
  }

  const options = useMemo(() => {
    const opts = MOSAIC_PRODUCT_IDS.map((p) => ({
      value: `product:${p}`,
      label: productLabel(p),
    }));
    for (const img of images) {
      opts.push({ value: `file:${img.id}`, label: img.filename });
    }
    return opts;
  }, [images]);

  const selectValue = source.kind === 'file'
    ? `file:${source.imageId}`
    : `product:${source.product === 'polar' ? 'data' : source.product}`;

  const diskCenter = { cx: params.cx, cy: params.cy };
  const diskHalfPx = pixelScale > 0 ? (params.rout / pixelScale) * 1.15 : 0;

  return (
    <div
      className={`disco-mosaic-cell${activeMosaicCell === index ? ' active' : ''}`}
      onMouseDown={() => setActiveMosaicCell(index)}
    >
      <div style={{
        position: 'absolute', top: 4, left: 4, zIndex: 2,
        background: 'var(--disco-bg-panel)', borderRadius: 2,
        border: '1px solid var(--disco-border)', padding: '0 2px',
      }}>
        <HTMLSelect
          minimal
          value={selectValue}
          options={options}
          onChange={(e) => {
            const v = e.target.value;
            if (v.startsWith('file:')) {
              setMosaicSource(index, { kind: 'file', imageId: v.slice(5), product: 'data' });
            } else {
              setMosaicSource(index, { kind: 'product', product: v.slice(8), imageId: null });
            }
          }}
        />
      </div>
      <ImageCanvas
        imageId={imageId}
        product={product}
        headerInfo={headerInfo}
        imgW={0}
        imgH={0}
        pixelScale={pixelScale}
        viz={viz}
        limits={limits}
        epoch={viewerEpoch}
        showGeometry={false}
        showRegions
        interactive
        persistView={false}
        frameDisk
        diskCenter={diskCenter}
        diskHalfPx={diskHalfPx}
        onActivate={() => setActiveMosaicCell(index)}
        active={activeMosaicCell === index}
        showColorbar
        showAxes={product === 'data' || product === 'deproj'}
      />
    </div>
  );
}

/** 2×2 mosaic grid — same analysis side panels as individual mode. */
export default function MosaicGrid() {
  return (
    <div className="disco-mosaic-grid" style={{ height: '100%', minHeight: 0 }}>
      {[0, 1, 2, 3].map((i) => (
        <MosaicCell key={i} index={i} />
      ))}
    </div>
  );
}
