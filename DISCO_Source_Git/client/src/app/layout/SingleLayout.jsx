import React from 'react';
import Split from 'react-split';
import { HTMLSelect } from '@blueprintjs/core';
import Dock from './Dock';
import MovableDock from './MovableDock';
import AnalysisWidget from './AnalysisWidget';
import MosaicGrid from './MosaicGrid';
import ImageCanvas from '../../viewer/ImageCanvas';
import CursorReadout from '../../viewer/CursorReadout';
import RenderConfig from '../../widgets/RenderConfig';
import ImageList from '../../widgets/ImageList';
import FitsHeader from '../../widgets/FitsHeader';
import useSessionStore from '../../state/session';
import useVizStore from '../../state/viz';
import { useDockStore } from '../../state/docks';
import { PRODUCT_IDS, productLabel } from '../../viewer/products';

/**
 * Shared shell for Individual and Mosaic modes.
 * Mosaic only swaps the main viewer for a 2×2 grid; side panels stay the same.
 */
export default function SingleLayout({ onRun, running }) {
  const activeImageId = useSessionStore((s) => s.activeImageId);
  const filename = useSessionStore((s) => s.filename);
  const imgDimensions = useSessionStore((s) => s.imgDimensions);
  const headerInfo = useSessionStore((s) => s.headerInfo);
  const pixelScale = useSessionStore((s) => s.pixelScale);
  const viewerEpoch = useSessionStore((s) => s.viewerEpoch);
  const hasRunPipeline = useSessionStore((s) => s.hasRunPipeline);
  const activeViewerTab = useSessionStore((s) => s.activeViewerTab);
  const setActiveViewerTab = useSessionStore((s) => s.setActiveViewerTab);
  const viewMode = useSessionStore((s) => s.viewMode);
  const rasterMeta = useSessionStore((s) => s.rasterMeta);
  const params = useSessionStore((s) => s.params);
  const layoutEpoch = useSessionStore((s) => s.layoutEpoch);
  const resetDocks = useDockStore((s) => s.resetDocks);
  const viz = useVizStore();
  const limitsOrStats = useVizStore((s) => s.limitsOrStats);
  const setProduct = useVizStore((s) => s.setProduct);
  const limits = viz.autoLimits === false ? limitsOrStats(rasterMeta?.stats) : null;
  const isMosaic = viewMode === 'mosaic';

  React.useEffect(() => {
    if (layoutEpoch > 0) resetDocks();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layoutEpoch]);

  React.useEffect(() => {
    if (isMosaic) {
      setActiveViewerTab('mosaic');
    } else {
      const tab = useSessionStore.getState().activeViewerTab;
      if (tab === 'mosaic') {
        setActiveViewerTab(hasRunPipeline ? 'product' : 'renderConfig');
      }
    }
    // Only when switching Individual ↔ Mosaic
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isMosaic]);

  const imgW = imgDimensions?.width || 0;
  const imgH = imgDimensions?.height || 0;
  const diskCenter = { cx: params.cx, cy: params.cy };
  const diskHalfPx = pixelScale > 0 ? (params.rout / pixelScale) * 1.15 : 0;

  const viewerTabs = isMosaic
    ? [
      { id: 'mosaic', label: 'Mosaic Viewer' },
      { id: 'renderConfig', label: 'Render Configuration' },
    ]
    : [
      { id: 'renderConfig', label: 'Render Configuration' },
      ...(hasRunPipeline ? [{ id: 'product', label: filename || 'Product' }] : []),
    ];

  const dockActive = viewerTabs.some((t) => t.id === activeViewerTab)
    ? activeViewerTab
    : viewerTabs[0].id;

  return (
    <Split
      key={`main-layout-${layoutEpoch}-${viewMode}`}
      sizes={[53 / 128 * 100, 40 / 128 * 100, 35 / 128 * 100]}
      minSize={[200, 200, 160]}
      gutterSize={4}
      direction="horizontal"
      style={{ display: 'flex', flex: 1, minHeight: 0, width: '100%' }}
    >
      <Split
        key={`left-col-${isMosaic ? 'mosaic' : 'single'}-${layoutEpoch}`}
        sizes={isMosaic ? [78, 22] : [62, 38]}
        minSize={[140, 100]}
        gutterSize={4}
        direction="vertical"
        style={{ display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0, width: '100%' }}
      >
        <Dock
          tabs={viewerTabs}
          activeId={dockActive}
          onChange={setActiveViewerTab}
          noScroll
          extra={!isMosaic && hasRunPipeline && dockActive === 'product' ? (
            <HTMLSelect
              minimal
              value={viz.product}
              options={PRODUCT_IDS.map((id) => ({ value: id, label: productLabel(id) }))}
              onChange={(e) => setProduct(e.target.value)}
            />
          ) : null}
        >
          <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            <CursorReadout />
            <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
              {/* Mosaic 2×2 — only difference vs individual */}
              {isMosaic && (
                <div style={{
                  display: dockActive === 'mosaic' ? 'block' : 'none',
                  height: '100%',
                }}>
                  <MosaicGrid />
                </div>
              )}

              <div style={{
                display: dockActive === 'renderConfig' ? 'flex' : 'none',
                height: '100%',
              }}>
                <div style={{ flex: 1, minWidth: 0, minHeight: 0 }}>
                  <ImageCanvas
                    imageId={activeImageId}
                    product="data"
                    headerInfo={headerInfo}
                    imgW={imgW}
                    imgH={imgH}
                    pixelScale={pixelScale}
                    viz={viz}
                    limits={limits}
                    epoch={viewerEpoch}
                    showGeometry
                    showRegions
                    interactive
                    showColorbar={viz.showColorbar}
                    showAxes={viz.showAxes}
                  />
                </div>
                <div style={{
                  width: 270, borderLeft: '1px solid var(--disco-border)',
                  overflowX: 'hidden', overflowY: 'auto', flexShrink: 0,
                }}>
                  <RenderConfig onRun={onRun} running={running} />
                </div>
              </div>

              {!isMosaic && hasRunPipeline && (
                <div style={{
                  display: dockActive === 'product' ? 'block' : 'none',
                  height: '100%',
                }}>
                  <ImageCanvas
                    imageId={activeImageId}
                    product={viz.product || 'deproj'}
                    headerInfo={headerInfo}
                    imgW={imgW}
                    imgH={imgH}
                    pixelScale={pixelScale}
                    viz={viz}
                    limits={limits}
                    epoch={viewerEpoch}
                    frameDisk
                    diskCenter={diskCenter}
                    diskHalfPx={diskHalfPx}
                    showGeometry={false}
                    showRegions
                    interactive
                    showColorbar={viz.showColorbar}
                    showAxes={viz.showAxes}
                  />
                </div>
              )}
            </div>
          </div>
        </Dock>

        <Dock tabs={[{ id: 'header', label: 'Header' }]} activeId="header" onChange={() => {}}>
          <FitsHeader />
        </Dock>
      </Split>

      <Split
        key={`mid-col-${layoutEpoch}-${viewMode}`}
        sizes={[50, 50]}
        minSize={60}
        gutterSize={4}
        direction="vertical"
        style={{ display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0, width: '100%' }}
      >
        <MovableDock slotId="midTop">
          {(id) => <AnalysisWidget id={id} />}
        </MovableDock>
        <MovableDock slotId="midBot">
          {(id) => <AnalysisWidget id={id} />}
        </MovableDock>
      </Split>

      <Split
        key={`right-col-${layoutEpoch}-${viewMode}`}
        sizes={[58, 42]}
        minSize={[100, 80]}
        gutterSize={4}
        direction="vertical"
        style={{ display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0, width: '100%' }}
      >
        <Dock
          tabs={[{ id: 'imageList', label: 'Image List / Files' }]}
          activeId="imageList"
          onChange={() => {}}
        >
          <ImageList />
        </Dock>
        <MovableDock slotId="rightBot">
          {(id) => <AnalysisWidget id={id} />}
        </MovableDock>
      </Split>
    </Split>
  );
}
