import React, { useRef, useState, useEffect } from 'react';
import { Stage, Layer, Ellipse, Line, Circle, Group, Rect, Transformer } from 'react-konva';
import { konvaDisplayGroupProps, arrayToDisplay, displayToArray, toDataCoords, toProductCoords } from './coords';
import { resolveThemeColors } from '../theme/colors';
import useSessionStore from '../state/session';
import useRegionsStore from '../state/regions';
import { api } from '../api/client';
import { ellipseThroughPoints } from './geometry';

/**
 * Konva overlays in display space (y↓, +scale) so resize/rotate handles work like paint.
 */
export default function OverlayLayer({
  width, height, transform, imgW, imgH, pixelScale,
  showGeometry, showRegions, interactive, product = 'data',
  onWheel, onPanMove, onPanEnd, screenToImage,
}) {
  const colors = resolveThemeColors();
  const params = useSessionStore((s) => s.params);
  const setParams = useSessionStore((s) => s.setParams);
  const activeTool = useRegionsStore((s) => s.activeTool);
  const regionTool = useRegionsStore((s) => s.regionTool);
  const regions = useRegionsStore((s) => s.regions);
  const addRegion = useRegionsStore((s) => s.addRegion);
  const updateRegion = useRegionsStore((s) => s.updateRegion);
  const selectedRegionId = useRegionsStore((s) => s.selectedRegionId);
  const setSelectedRegionId = useRegionsStore((s) => s.setSelectedRegionId);
  const setSliceLine = useRegionsStore((s) => s.setSliceLine);
  const sliceLine = useRegionsStore((s) => s.sliceLine);
  const geomPolyDraft = useRegionsStore((s) => s.geomPolyDraft);
  const setGeomPolyDraft = useRegionsStore((s) => s.setGeomPolyDraft);
  const clearGeomPolyDraft = useRegionsStore((s) => s.clearGeomPolyDraft);
  const setProbe = useSessionStore((s) => s.setProbe);
  const probe = useSessionStore((s) => s.probe);
  const activeImageId = useSessionStore((s) => s.activeImageId);
  const selectedGeom = useRegionsStore((s) => s.selectedGeom);
  const setSelectedGeom = useRegionsStore((s) => s.setSelectedGeom);

  const [draft, setDraft] = useState(null);
  const probeTimer = useRef(0);
  const shapeRefs = useRef({});
  const geomRef = useRef(null);
  const trRef = useRef(null);

  const sw = Math.max(1.5, 2 / Math.max(transform.k, 0.01));
  const handleR = Math.max(5, 7 / Math.max(transform.k, 0.01));
  const rad = (d) => (d * Math.PI) / 180;
  const isDeprojProduct = product === 'deproj' || product === 'model' || product === 'residuals';
  const isPolar = product === 'polar';
  // Geometry / radial center: full-field data uses params; analysis products are grid-centered
  const centerCx = (isDeprojProduct || isPolar) ? imgW / 2 : params.cx;
  const centerCy = (isDeprojProduct || isPolar) ? imgH / 2 : params.cy;
  const radiusX = pixelScale > 0 ? params.rout / pixelScale : 40;
  const radiusY = Math.max(radiusX * Math.cos(rad(params.incl)), 1);
  // PA is East-of-North (East = -x): major axis = (-sin pa, cos pa) in array
  // coords, which in display space (y down) is a Konva rotation of -(pa + 90).
  const konvaRotation = -(params.pa + 90);
  const groupProps = konvaDisplayGroupProps(transform);
  const isGeomPoly = regionTool === 'geomPoly';
  const isPan = interactive && activeTool === 'pan';
  const isSelect = activeTool === 'select';
  const isRadial = activeTool === 'radial' && !isPolar;
  const showProbe = isRadial;

  const ay = (iy) => imgH - iy; // array → display y
  const geomDisp = arrayToDisplay(centerCx, centerCy, imgH);
  // Disk center in full-data coords (regions/probes are stored there)
  const dataCx = params.cx;
  const dataCy = params.cy;
  const localOf = (x, y) => toProductCoords(x, y, product, imgW, imgH, dataCx, dataCy);
  const dataOf = (x, y) => toDataCoords(x, y, product, imgW, imgH, dataCx, dataCy);
  // Probe cursor in this product's array coords
  const probeLocal = probe && Number.isFinite(probe.x) && Number.isFinite(probe.y)
    ? localOf(probe.x, probe.y)
    : null;
  const probeDisp = probeLocal ? arrayToDisplay(probeLocal.x, probeLocal.y, imgH) : null;
  const showRegionsHere = showRegions && !isPolar;
  const showSliceHere = !isPolar;

  useEffect(() => {
    const tr = trRef.current;
    if (!tr) return;
    if (isSelect && selectedRegionId && shapeRefs.current[selectedRegionId]) {
      tr.nodes([shapeRefs.current[selectedRegionId]]);
      setSelectedGeom(false);
      tr.getLayer()?.batchDraw();
    } else if (isSelect && selectedGeom && geomRef.current && showGeometry) {
      tr.nodes([geomRef.current]);
      tr.getLayer()?.batchDraw();
    } else {
      tr.nodes([]);
      tr.getLayer()?.batchDraw();
    }
  }, [selectedRegionId, selectedGeom, regions, isSelect, transform.k, centerCx, centerCy, params.rout, params.incl, params.pa, showGeometry, setSelectedGeom]);

  const applyGeomPoly = (pts) => {
    // Fit in full-data coords so cx/cy match the rest of the pipeline
    const dataPts = pts.map((p) => dataOf(p.x, p.y));
    const e = ellipseThroughPoints(dataPts, pixelScale);
    if (e) setParams({ cx: e.cx, cy: e.cy, pa: e.pa, incl: e.incl, rout: e.rout });
    clearGeomPolyDraft();
  };

  const deprojRadius = (ix, iy) => {
    const ps = pixelScale || 0.03;
    // Polar map: columns are radius from 0 → Rout across the image width
    if (isPolar) {
      const rout = params.rout || 1;
      return Math.max(0, Math.min(rout, (ix / Math.max(imgW, 1)) * rout));
    }
    const dx = ix - centerCx;
    const dy = iy - centerCy;
    // Already face-on products: euclidean radius in arcsec
    if (isDeprojProduct) {
      return Math.hypot(dx, dy) * ps;
    }
    const paRad = rad(params.pa);
    const inclRad = rad(params.incl);
    // Inverse of deproject_image (East = -x): disk radius from sky offset
    const xrot = -dx;
    const yrot = dy;
    const xc = xrot * Math.cos(paRad) - yrot * Math.sin(paRad);
    const yc = xrot * Math.sin(paRad) + yrot * Math.cos(paRad);
    const xd = xc / Math.max(Math.cos(inclRad), 0.05);
    return Math.hypot(xd, yc) * ps;
  };

  const runProbe = (ix, iy) => {
    if (!activeImageId) return;
    const rArc = deprojRadius(ix, iy);
    const dataPt = dataOf(ix, iy);
    setProbe({
      x: dataPt.x, y: dataPt.y,
      radius: rArc, pending: true, value: null,
      sourceProduct: product || 'data',
    });
    clearTimeout(probeTimer.current);
    probeTimer.current = setTimeout(async () => {
      try {
        const result = await api.probe({
          x: ix, y: iy, product: product || 'data', image_id: activeImageId,
        });
        setProbe({
          x: dataPt.x, y: dataPt.y,
          value: result.value, ra: result.ra, dec: result.dec,
          radius: rArc, pending: false,
          sourceProduct: product || 'data',
        });
      } catch {
        setProbe({
          x: dataPt.x, y: dataPt.y,
          value: null, radius: rArc, pending: false,
          sourceProduct: product || 'data',
        });
      }
    }, 40);
  };

  const handleMouseDown = (e) => {
    if (!interactive) return;
    if (e.target.getParent()?.className === 'Transformer') return;
    const ptr = e.target.getStage().getPointerPosition();
    if (!ptr) return;
    const img = screenToImage(ptr.x, ptr.y);

    if (isGeomPoly) {
      const pts = [...(geomPolyDraft?.points || []), { x: img.x, y: img.y }];
      if (pts.length >= 4) applyGeomPoly(pts.slice(0, 4));
      else setGeomPolyDraft({ points: pts, cursor: img });
      return;
    }

    if (activeTool === 'region' && regionTool) {
      if (isPolar) return; // polar is θ–R; sky regions / slices don't map
      if (regionTool === 'polygon') {
        const pts = draft?.points || [];
        setDraft({ type: 'polygon', points: [...pts, { x: img.x, y: img.y }], cursor: img });
        return;
      }
      if (regionTool === 'line') {
        setDraft({ type: 'line', x0: img.x, y0: img.y, x1: img.x, y1: img.y });
        return;
      }
      setDraft({ type: regionTool, x0: img.x, y0: img.y, x1: img.x, y1: img.y });
      return;
    }

    if (isSelect) {
      const name = e.target.name?.() || '';
      if (name === 'hit' || e.target === e.target.getStage()) {
        setSelectedRegionId(null);
        setSelectedGeom(false);
      }
    }
  };

  const handleMouseMove = (e) => {
    const ptr = e.target.getStage().getPointerPosition();
    if (!ptr) return;
    const img = screenToImage(ptr.x, ptr.y);

    if (isRadial) {
      runProbe(img.x, img.y);
      if (isGeomPoly && geomPolyDraft) setGeomPolyDraft({ ...geomPolyDraft, cursor: img });
      return;
    }

    if (isGeomPoly && geomPolyDraft) {
      setGeomPolyDraft({ ...geomPolyDraft, cursor: img });
    }
    if (draft?.type === 'polygon') {
      setDraft((d) => ({ ...d, cursor: img }));
    } else if (draft) {
      setDraft((d) => ({ ...d, x1: img.x, y1: img.y }));
    }
  };

  const handleMouseUp = () => {
    if (!draft || draft.type === 'polygon') return;
    const { type, x0, y0, x1, y1 } = draft;
    setDraft(null);
    if (Math.hypot(x1 - x0, y1 - y0) < 2) return;
    // Always store regions in full-data array coordinates
    const a0 = dataOf(x0, y0);
    const a1 = dataOf(x1, y1);
    if (type === 'line') {
      setSliceLine({ x0: a0.x, y0: a0.y, x1: a1.x, y1: a1.y });
      return;
    }
    if (type === 'ellipse') {
      addRegion({
        type: 'ellipse',
        cx: (a0.x + a1.x) / 2, cy: (a0.y + a1.y) / 2,
        rx: Math.abs(a1.x - a0.x) / 2, ry: Math.abs(a1.y - a0.y) / 2,
        rotation: 0,
      });
    } else if (type === 'rectangle') {
      addRegion({
        type: 'rectangle',
        x0: a0.x, y0: a0.y, x1: a1.x, y1: a1.y, rotation: 0,
      });
    } else if (type === 'annulus') {
      const r_out = Math.hypot(a1.x - a0.x, a1.y - a0.y);
      addRegion({ type: 'annulus', cx: a0.x, cy: a0.y, r_in: r_out * 0.5, r_out });
    }
  };

  const handleDblClick = () => {
    if (isGeomPoly && geomPolyDraft?.points?.length >= 3) {
      applyGeomPoly(geomPolyDraft.points);
      return;
    }
    if (draft?.type === 'polygon' && draft.points?.length >= 3) {
      addRegion({
        type: 'polygon',
        points: draft.points.map((p) => dataOf(p.x, p.y)),
      });
      setDraft(null);
    }
  };

  const commitRegionTransform = (id, node) => {
    const r = regions.find((x) => x.id === id);
    if (!r) return;
    if (r.type === 'ellipse') {
      const local = displayToArray(node.x(), node.y(), imgH);
      const data = dataOf(local.x, local.y);
      updateRegion(id, {
        cx: data.x, cy: data.y,
        rx: Math.abs(node.radiusX() * node.scaleX()),
        ry: Math.abs(node.radiusY() * node.scaleY()),
        rotation: node.rotation(),
      });
      node.scaleX(1);
      node.scaleY(1);
    } else if (r.type === 'rectangle') {
      const w = Math.abs(node.width() * node.scaleX());
      const h = Math.abs(node.height() * node.scaleY());
      const local0 = displayToArray(node.x(), node.y(), imgH);
      const local1 = displayToArray(node.x() + w, node.y() + h, imgH);
      const d0 = dataOf(local0.x, local0.y);
      const d1 = dataOf(local1.x, local1.y);
      updateRegion(id, {
        x0: d0.x, y0: Math.min(d0.y, d1.y),
        x1: d1.x, y1: Math.max(d0.y, d1.y),
        rotation: node.rotation(),
      });
      node.scaleX(1);
      node.scaleY(1);
      node.width(w);
      node.height(h);
    }
  };

  const commitGeomTransform = (node) => {
    const arr = displayToArray(node.x(), node.y(), imgH);
    const sx = Math.abs(node.scaleX());
    const sy = Math.abs(node.scaleY());
    const rx = Math.abs(node.radiusX() * sx);
    const ry = Math.abs(node.radiusY() * sy);
    // Local X is the major axis; if the user squashed it past ry the axes swap
    const swapped = ry > rx;
    const major = Math.max(rx, ry);
    const minor = Math.max(Math.min(rx, ry), 1e-6);
    const rout = Math.max(0.05, Math.min(2, major * (pixelScale || 0.03)));
    const incl = Math.acos(Math.min(1, Math.max(0, minor / major))) * (180 / Math.PI);
    // display rotation → PA (inverse of konvaRotation)
    const rotDeg = node.rotation() + (swapped ? 90 : 0);
    const pa = ((-rotDeg - 90) % 180 + 180) % 180;
    setParams({ cx: arr.x, cy: arr.y, rout, incl, pa });
    node.scaleX(1);
    node.scaleY(1);
  };

  const cursor = showProbe
    ? 'crosshair'
    : (isPan ? 'grab' : 'default');

  const radialRpix = Number.isFinite(probe?.radius) && pixelScale > 0
    ? probe.radius / pixelScale
    : 0;
  // Iso-R contour: circle on face-on products, inclined ellipse on full-field data
  const radialRy = isDeprojProduct
    ? Math.max(radialRpix, 1e-3)
    : Math.max(radialRpix * Math.cos(rad(params.incl)), 1e-3);
  const radialRotation = isDeprojProduct ? 0 : konvaRotation;
  const showProbeRing = isRadial && radialRpix > 0 && !isPolar;

  return (
    <Stage
      width={width}
      height={height}
      onWheel={onWheel}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onDblClick={handleDblClick}
      draggable={isPan}
      x={0}
      y={0}
      onDragMove={(e) => {
        if (!isPan) return;
        onPanMove?.(e.target.x(), e.target.y());
      }}
      onDragEnd={(e) => {
        if (!isPan) return;
        onPanEnd?.(e.target.x(), e.target.y());
        e.target.position({ x: 0, y: 0 });
      }}
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', cursor }}
    >
      <Layer listening>
        <Group {...groupProps}>
          <Rect
            name="hit"
            x={0} y={0} width={imgW} height={imgH}
            fill="rgba(0,0,0,0.001)"
            listening
          />

          {/* Disk geometry ellipse */}
          {showGeometry && radiusX > 0 && (
            <Ellipse
              ref={geomRef}
              name="geom"
              x={geomDisp.x}
              y={geomDisp.y}
              radiusX={radiusX}
              radiusY={radiusY}
              rotation={konvaRotation}
              stroke={colors.accent}
              strokeWidth={sw}
              dash={[8 / transform.k, 4 / transform.k]}
              hitStrokeWidth={12 / transform.k}
              draggable={isSelect}
              onClick={() => { setSelectedGeom(true); setSelectedRegionId(null); }}
              onTap={() => { setSelectedGeom(true); setSelectedRegionId(null); }}
              onDragEnd={(e) => {
                const arr = displayToArray(e.target.x(), e.target.y(), imgH);
                setParams({ cx: arr.x, cy: arr.y });
              }}
              onTransformEnd={(e) => commitGeomTransform(e.target)}
            />
          )}
          {showGeometry && (
            <Group x={geomDisp.x} y={geomDisp.y} listening={false}>
              <Line points={[-8 / transform.k, 0, 8 / transform.k, 0]} stroke={colors.warning} strokeWidth={sw} />
              <Line points={[0, -8 / transform.k, 0, 8 / transform.k]} stroke={colors.warning} strokeWidth={sw} />
            </Group>
          )}

          {showProbeRing && (
            <Group listening={false}>
              {probeDisp && (
                <Line
                  points={[geomDisp.x, geomDisp.y, probeDisp.x, probeDisp.y]}
                  stroke={colors.warning}
                  strokeWidth={sw}
                />
              )}
              <Ellipse
                x={geomDisp.x} y={geomDisp.y}
                radiusX={radialRpix} radiusY={radialRy}
                rotation={radialRotation}
                stroke={colors.warning}
                strokeWidth={sw}
                dash={[6 / transform.k, 4 / transform.k]}
              />
              {probeDisp && (
                <Circle
                  x={probeDisp.x} y={probeDisp.y}
                  radius={handleR * 0.6}
                  fill={colors.warning}
                />
              )}
            </Group>
          )}

          {showRegionsHere && regions.map((r) => {
            const selected = r.id === selectedRegionId;
            const stroke = r.color || colors.roi;
            const swR = selected ? sw * 1.8 : sw;
            const canDrag = !r.locked && isSelect;

            if (r.type === 'ellipse') {
              const loc = localOf(r.cx, r.cy);
              const d = arrayToDisplay(loc.x, loc.y, imgH);
              return (
                <Ellipse
                  key={r.id}
                  ref={(n) => { if (n) shapeRefs.current[r.id] = n; }}
                  x={d.x} y={d.y}
                  radiusX={r.rx} radiusY={r.ry}
                  rotation={r.rotation || 0}
                  stroke={stroke} strokeWidth={swR}
                  hitStrokeWidth={14 / transform.k}
                  draggable={canDrag}
                  onClick={() => { setSelectedRegionId(r.id); setSelectedGeom(false); }}
                  onTap={() => { setSelectedRegionId(r.id); setSelectedGeom(false); }}
                  onDragEnd={(e) => {
                    const local = displayToArray(e.target.x(), e.target.y(), imgH);
                    const data = dataOf(local.x, local.y);
                    updateRegion(r.id, { cx: data.x, cy: data.y });
                  }}
                  onTransformEnd={(e) => commitRegionTransform(r.id, e.target)}
                />
              );
            }
            if (r.type === 'rectangle') {
              const p0 = localOf(r.x0, r.y0);
              const p1 = localOf(r.x1, r.y1);
              const x0 = Math.min(p0.x, p1.x);
              const x1 = Math.max(p0.x, p1.x);
              const yLo = Math.min(p0.y, p1.y);
              const yHi = Math.max(p0.y, p1.y);
              return (
                <Rect
                  key={r.id}
                  ref={(n) => { if (n) shapeRefs.current[r.id] = n; }}
                  x={x0}
                  y={ay(yHi)}
                  width={x1 - x0}
                  height={yHi - yLo}
                  rotation={r.rotation || 0}
                  stroke={stroke} strokeWidth={swR}
                  hitStrokeWidth={14 / transform.k}
                  draggable={canDrag}
                  onClick={() => { setSelectedRegionId(r.id); setSelectedGeom(false); }}
                  onTap={() => { setSelectedRegionId(r.id); setSelectedGeom(false); }}
                  onDragEnd={(e) => {
                    const w = x1 - x0;
                    const h = yHi - yLo;
                    const local0 = displayToArray(e.target.x(), e.target.y(), imgH);
                    const local1 = displayToArray(e.target.x() + w, e.target.y() + h, imgH);
                    const d0 = dataOf(local0.x, local0.y);
                    const d1 = dataOf(local1.x, local1.y);
                    updateRegion(r.id, {
                      x0: d0.x, y0: Math.min(d0.y, d1.y),
                      x1: d1.x, y1: Math.max(d0.y, d1.y),
                    });
                  }}
                  onTransformEnd={(e) => commitRegionTransform(r.id, e.target)}
                />
              );
            }
            if (r.type === 'annulus') {
              const loc = localOf(r.cx, r.cy);
              const d = arrayToDisplay(loc.x, loc.y, imgH);
              return (
                <Group
                  key={r.id}
                  x={d.x} y={d.y}
                  draggable={canDrag}
                  onClick={() => { setSelectedRegionId(r.id); setSelectedGeom(false); }}
                  onDragEnd={(e) => {
                    const local = displayToArray(e.target.x(), e.target.y(), imgH);
                    const data = dataOf(local.x, local.y);
                    updateRegion(r.id, { cx: data.x, cy: data.y });
                  }}
                >
                  <Ellipse
                    ref={(n) => { if (n) shapeRefs.current[r.id] = n; }}
                    radiusX={r.r_out} radiusY={r.r_out}
                    stroke={stroke} strokeWidth={swR}
                    hitStrokeWidth={14 / transform.k}
                  />
                  <Ellipse radiusX={r.r_in} radiusY={r.r_in} stroke={stroke} strokeWidth={swR}
                    dash={[4 / transform.k, 4 / transform.k]} listening={false} />
                </Group>
              );
            }
            if (r.type === 'polygon' && r.points?.length) {
              return (
                <Line
                  key={r.id}
                  ref={(n) => { if (n) shapeRefs.current[r.id] = n; }}
                  points={r.points.flatMap((p) => {
                    const loc = localOf(p.x, p.y);
                    const d = arrayToDisplay(loc.x, loc.y, imgH);
                    return [d.x, d.y];
                  })}
                  closed
                  stroke={stroke} strokeWidth={swR}
                  hitStrokeWidth={14 / transform.k}
                  draggable={canDrag}
                  onClick={() => { setSelectedRegionId(r.id); setSelectedGeom(false); }}
                  onDragEnd={(e) => {
                    const dx = e.target.x();
                    const dy = e.target.y();
                    updateRegion(r.id, {
                      points: r.points.map((p) => {
                        const loc = localOf(p.x, p.y);
                        const d = arrayToDisplay(loc.x, loc.y, imgH);
                        const moved = displayToArray(d.x + dx, d.y + dy, imgH);
                        return dataOf(moved.x, moved.y);
                      }),
                    });
                    e.target.position({ x: 0, y: 0 });
                  }}
                />
              );
            }
            return null;
          })}

          {isSelect && (
            <Transformer
              ref={trRef}
              rotateEnabled
              flipEnabled={false}
              ignoreStroke
              borderStroke={colors.accent}
              anchorStroke={colors.accent}
              anchorFill="#fff"
              anchorSize={10}
              rotateAnchorOffset={18}
              enabledAnchors={[
                'top-left', 'top-right', 'bottom-left', 'bottom-right',
                'middle-left', 'middle-right', 'top-center', 'bottom-center',
              ]}
              boundBoxFunc={(oldBox, newBox) => {
                if (Math.abs(newBox.width) < 4 || Math.abs(newBox.height) < 4) return oldBox;
                return newBox;
              }}
            />
          )}

          {showSliceHere && sliceLine && (() => {
            const p0 = localOf(sliceLine.x0, sliceLine.y0);
            const p1 = localOf(sliceLine.x1, sliceLine.y1);
            const d0 = arrayToDisplay(p0.x, p0.y, imgH);
            const d1 = arrayToDisplay(p1.x, p1.y, imgH);
            return (
              <Line
                points={[d0.x, d0.y, d1.x, d1.y]}
                stroke={colors.roiAlt}
                strokeWidth={sw * 1.5}
                listening={false}
              />
            );
          })()}

          {geomPolyDraft?.points?.length > 0 && (
            <>
              <Line
                points={[
                  ...geomPolyDraft.points.flatMap((p) => {
                    const d = arrayToDisplay(p.x, p.y, imgH);
                    return [d.x, d.y];
                  }),
                  ...(geomPolyDraft.cursor
                    ? [arrayToDisplay(geomPolyDraft.cursor.x, geomPolyDraft.cursor.y, imgH).x,
                      arrayToDisplay(geomPolyDraft.cursor.x, geomPolyDraft.cursor.y, imgH).y]
                    : []),
                ]}
                stroke={colors.accent}
                strokeWidth={sw}
                dash={[6 / transform.k, 4 / transform.k]}
                listening={false}
              />
              {geomPolyDraft.points.map((p, i) => {
                const d = arrayToDisplay(p.x, p.y, imgH);
                return (
                  <Circle key={i} x={d.x} y={d.y} radius={handleR}
                    fill={colors.accent} listening={false} />
                );
              })}
            </>
          )}

          {draft?.type === 'line' && (
            <Line
              points={[
                arrayToDisplay(draft.x0, draft.y0, imgH).x, arrayToDisplay(draft.x0, draft.y0, imgH).y,
                arrayToDisplay(draft.x1, draft.y1, imgH).x, arrayToDisplay(draft.x1, draft.y1, imgH).y,
              ]}
              stroke={colors.roiAlt} strokeWidth={sw}
              dash={[6 / transform.k, 4 / transform.k]} listening={false} />
          )}
          {draft?.type === 'ellipse' && (
            <Ellipse
              x={(arrayToDisplay(draft.x0, draft.y0, imgH).x + arrayToDisplay(draft.x1, draft.y1, imgH).x) / 2}
              y={(arrayToDisplay(draft.x0, draft.y0, imgH).y + arrayToDisplay(draft.x1, draft.y1, imgH).y) / 2}
              radiusX={Math.abs(draft.x1 - draft.x0) / 2}
              radiusY={Math.abs(draft.y1 - draft.y0) / 2}
              stroke={colors.roi} strokeWidth={sw}
              dash={[6 / transform.k, 4 / transform.k]} listening={false} />
          )}
          {draft?.type === 'rectangle' && (
            <Rect
              x={Math.min(draft.x0, draft.x1)}
              y={Math.min(ay(draft.y0), ay(draft.y1))}
              width={Math.abs(draft.x1 - draft.x0)}
              height={Math.abs(draft.y1 - draft.y0)}
              stroke={colors.roi} strokeWidth={sw}
              dash={[6 / transform.k, 4 / transform.k]} listening={false} />
          )}
          {draft?.type === 'polygon' && draft.points?.length > 0 && (
            <Line
              points={[
                ...draft.points.flatMap((p) => {
                  const d = arrayToDisplay(p.x, p.y, imgH);
                  return [d.x, d.y];
                }),
                ...(draft.cursor
                  ? [arrayToDisplay(draft.cursor.x, draft.cursor.y, imgH).x,
                    arrayToDisplay(draft.cursor.x, draft.cursor.y, imgH).y]
                  : []),
              ]}
              stroke={colors.roi} strokeWidth={sw} listening={false} />
          )}
        </Group>
      </Layer>
    </Stage>
  );
}
