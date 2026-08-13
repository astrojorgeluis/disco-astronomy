import React, { useState, useRef, useEffect } from 'react';
import { Stage, Layer, Image as KonvaImage, Ellipse, Line, Circle, Group } from 'react-konva';
import useImage from 'use-image';

const InteractiveViewer = ({ imageSrc, params, setParams, activeTool, imgDimensions, pixelScale = 0.03 }) => {
  const [image] = useImage(imageSrc);
  const containerRef = useRef(null);
  
  const [dimensions, setDimensions] = useState({ width: 100, height: 100 });
  const [stagePos, setStagePos] = useState({ x: 0, y: 0 });
  const [stageScale, setStageScale] = useState(1);
  // Continuum PA is defined mod 180° → major axis has two tips. Keep the handle
  // on the tip closest to the pointer so it does not flip during drag.
  const handleSignRef = useRef(1);
  // Preserve zoom/pan across mosaic resizes only after the user has adjusted the view.
  const userAdjustedViewRef = useRef(false);
  const lastImageKeyRef = useRef('');

  // RESIZE OBSERVER
  useEffect(() => {
    if (!containerRef.current) return;
    const resizeObserver = new ResizeObserver((entries) => {
      for (let entry of entries) {
        setDimensions({
          width: entry.contentRect.width,
          height: entry.contentRect.height
        });
      }
    });
    resizeObserver.observe(containerRef.current);
    return () => resizeObserver.disconnect();
  }, []);

  // AUTO-FIT: new image always; resize only if the user has not zoomed/panned yet
  useEffect(() => {
    if (!imgDimensions || dimensions.width === 0 || dimensions.height === 0) return;

    const imageKey = `${imageSrc || ''}|${imgDimensions.width}x${imgDimensions.height}`;
    if (imageKey !== lastImageKeyRef.current) {
      lastImageKeyRef.current = imageKey;
      userAdjustedViewRef.current = false;
    } else if (userAdjustedViewRef.current) {
      return;
    }

    const { width: imgW, height: imgH } = imgDimensions;
    const { width: viewW, height: viewH } = dimensions;

    const scaleX = viewW / imgW;
    const scaleY = viewH / imgH;
    const fitScale = Math.min(scaleX, scaleY) * 0.9;

    const centerX = (viewW - imgW * fitScale) / 2;
    const centerY = (viewH - imgH * fitScale) / 2;

    setStageScale(fitScale);
    setStagePos({ x: centerX, y: centerY });
  }, [imageSrc, imgDimensions, dimensions.width, dimensions.height]);

  // GEOMETRY HELPERS
  const konvaRotation = 270 - params.pa; 
  
  const stopPropagation = (e) => {
    e.cancelBubble = true;
  };

  const round2 = (num) => Math.round(num * 100) / 100;
  const rad = (deg) => deg * (Math.PI / 180);

  const handleDragCenter = (e) => {
    stopPropagation(e);
    setParams({
      ...params,
      cx: round2(e.target.x()),
      cy: round2(e.target.y())
    });
  };

  const handleDragRotator = (e) => {
    stopPropagation(e);
    const stage = e.target.getStage();
    const pointer = stage.getPointerPosition();
    if (!pointer) return;
    const transform = stage.getAbsoluteTransform().copy();
    transform.invert();
    const pos = transform.point(pointer);

    const dx = pos.x - params.cx;
    const dy = pos.y - params.cy;
    const distPixels = Math.sqrt(dx * dx + dy * dy);
    if (distPixels < 1e-6) return;

    const angleDeg = Math.atan2(dy, dx) * (180 / Math.PI);
    let newPA = (270 - angleDeg) % 360;
    if (newPA < 0) newPA += 360;
    newPA = newPA % 180;

    const rot = 270 - newPA;
    const c = Math.cos(rad(rot));
    const s = Math.sin(rad(rot));
    const tipPlus = { x: params.cx + distPixels * c, y: params.cy + distPixels * s };
    const tipMinus = { x: params.cx - distPixels * c, y: params.cy - distPixels * s };
    const dPlus = (pos.x - tipPlus.x) ** 2 + (pos.y - tipPlus.y) ** 2;
    const dMinus = (pos.x - tipMinus.x) ** 2 + (pos.y - tipMinus.y) ** 2;
    handleSignRef.current = dPlus <= dMinus ? 1 : -1;

    const tip = handleSignRef.current > 0 ? tipPlus : tipMinus;
    e.target.position(tip);

    const maxRout = 0.5 * (params.fov || 3);
    const newRout = Math.min(Math.max(distPixels * pixelScale, 0.05), maxRout);

    setParams({
      ...params,
      pa: round2(newPA),
      rout: round2(newRout),
    });
  };

  // ZOOM HANDLER
  const handleWheel = (e) => {
    e.evt.preventDefault();
    const scaleBy = 1.1;
    const stage = e.target.getStage();
    const oldScale = stage.scaleX();
    const mousePointTo = {
      x: stage.getPointerPosition().x / oldScale - stage.x() / oldScale,
      y: stage.getPointerPosition().y / oldScale - stage.y() / oldScale,
    };

    const newScale = e.evt.deltaY < 0 ? oldScale * scaleBy : oldScale / scaleBy;
    
    if (newScale < 0.001 || newScale > 200) return;

    userAdjustedViewRef.current = true;
    setStagePos({
      x: -(mousePointTo.x - stage.getPointerPosition().x / newScale) * newScale,
      y: -(mousePointTo.y - stage.getPointerPosition().y / newScale) * newScale,
    });
    setStageScale(newScale);
  };

  // RENDERING CALCULATIONS
  const radiusX_Pixels = params.rout / pixelScale; 
  const radiusY_Pixels = radiusX_Pixels * Math.cos(rad(params.incl));
  
  const hx = params.cx + handleSignRef.current * radiusX_Pixels * Math.cos(rad(konvaRotation));
  const hy = params.cy + handleSignRef.current * radiusX_Pixels * Math.sin(rad(konvaRotation));

  if (!imageSrc) {
      return (
        <div ref={containerRef} style={{width:'100%', height:'100%', display:'flex', alignItems:'center', justifyContent:'center', background:'var(--disco-chart-bg)', color:'var(--disco-text-muted)'}}>
            NO DATA
        </div>
      );
  }

  return (
    <div ref={containerRef} style={{ width: '100%', height: '100%', background: 'var(--disco-chart-bg)', overflow: 'hidden' }}>
      <Stage 
        width={dimensions.width} 
        height={dimensions.height} 
        onWheel={handleWheel}
        scaleX={stageScale}
        scaleY={stageScale}
        x={stagePos.x}
        y={stagePos.y}
        draggable={activeTool === 'pan'}
        onDragEnd={(e) => {
            userAdjustedViewRef.current = true;
            setStagePos({ x: e.target.x(), y: e.target.y() });
        }}
      >
        <Layer>
          <KonvaImage 
            image={image} 
            width={imgDimensions ? imgDimensions.width : (image ? image.width : 100)}
            height={imgDimensions ? imgDimensions.height : (image ? image.height : 100)}
            listening={false}
          />
          
          <Group visible={true} listening={activeTool === 'select'}>
              {/* GEOMETRY OVERLAY */}
              <Ellipse 
                x={params.cx} 
                y={params.cy} 
                radiusX={radiusX_Pixels}
                radiusY={radiusY_Pixels}
                rotation={konvaRotation}
                stroke="#ab71ff" 
                strokeWidth={2 / stageScale}
                dash={[10, 5]}
                listening={false}
              />
              
              <Line 
                points={[
                    params.cx - radiusX_Pixels * Math.cos(rad(konvaRotation)),
                    params.cy - radiusX_Pixels * Math.sin(rad(konvaRotation)),
                    params.cx + radiusX_Pixels * Math.cos(rad(konvaRotation)),
                    params.cy + radiusX_Pixels * Math.sin(rad(konvaRotation))
                ]}
                stroke="#ab71ff"
                strokeWidth={1.5 / stageScale}
                dash={[5, 5]}
                opacity={0.6}
                listening={false}
              />

              {/* CENTER HANDLE */}
              <Group 
                x={params.cx} 
                y={params.cy}
                draggable
                onDragStart={stopPropagation}
                onDragMove={handleDragCenter}
                onDragEnd={stopPropagation}
                onMouseEnter={e => { const c = e.target.getStage().container(); c.style.cursor = "move"; }}
                onMouseLeave={e => { const c = e.target.getStage().container(); c.style.cursor = "default"; }}
              >
                 <Circle radius={15 / stageScale} fill="transparent" /> 
                 <Line points={[-12/stageScale, 0, 12/stageScale, 0]} stroke="#ffff00" strokeWidth={3/stageScale} />
                 <Line points={[0, -12/stageScale, 0, 12/stageScale]} stroke="#ffff00" strokeWidth={3/stageScale} />
              </Group>

              {/* ROTATOR HANDLE */}
              <Circle
                x={hx} y={hy} 
                radius={8 / stageScale} 
                fill="#ffffff" stroke="#ab71ff" strokeWidth={2 / stageScale}
                draggable 
                onDragStart={stopPropagation} onDragMove={handleDragRotator} onDragEnd={stopPropagation}
                onMouseEnter={e => { const c = e.target.getStage().container(); c.style.cursor = "pointer"; }}
                onMouseLeave={e => { const c = e.target.getStage().container(); c.style.cursor = "default"; }}
              />
          </Group>
        </Layer>
      </Stage>

      {/* ZOOM INDICATOR */}
      <div style={{
          position:'absolute', 
          bottom:10, 
          right:10, 
          color:'var(--disco-text)', 
          background:'rgba(20, 20, 20, 0.7)', 
          backdropFilter: 'blur(4px)',
          border: '1px solid var(--disco-border)',
          padding:'2px 6px', 
          fontSize:10, 
          fontFamily: 'JetBrains Mono, monospace',
          pointerEvents:'none', 
          borderRadius: 4
      }}>
          Zoom: {Math.round(stageScale * 100)}%
      </div>
    </div>
  );
};

export default InteractiveViewer;