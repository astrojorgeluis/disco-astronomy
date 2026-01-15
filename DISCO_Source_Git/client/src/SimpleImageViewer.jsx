import React, { useState, useEffect, useCallback, useImperativeHandle, forwardRef, useRef } from 'react';
import { Stage, Layer, Image as KonvaImage, Line, Text, Group, Rect, Circle, Ellipse, Star, Ring } from 'react-konva';
import useImage from 'use-image';

// FORMATTERS
const axisFormatter = (num) => {
    if (num === 0) return "0"; 
    if (Math.abs(num) < 0.001 || Math.abs(num) >= 10000) return num.toExponential(1);
    return parseFloat(num.toPrecision(4)).toString(); 
};

const scientificFormatter = (num) => {
    if (num === 0) return "0.0";
    if (Math.abs(num) < 0.01 || Math.abs(num) > 1000) return num.toExponential(1);
    return num.toFixed(2);
};

const getNiceStep = (range, targetTickCount = 6) => {
    const roughStep = range / targetTickCount;
    const exponent = Math.floor(Math.log10(roughStep));
    const fraction = roughStep / Math.pow(10, exponent);
    let niceFraction;
    if (fraction < 1.5) niceFraction = 1;
    else if (fraction < 3) niceFraction = 2;
    else if (fraction < 7) niceFraction = 5;
    else niceFraction = 10;
    return niceFraction * Math.pow(10, exponent);
};

// DYNAMIC AXES COMPONENT
const DynamicAxes = ({ width, height, fieldOfView, transform, type, imgSize }) => {
    if (!width || !height || width <= 0 || height <= 0) return null;

    const xTicks = [];
    const yTicks = [];
    const gridLines = [];

    const startImgX = -transform.x / transform.k;
    const endImgX = (width - transform.x) / transform.k;
    const startImgY = -transform.y / transform.k;
    const endImgY = (height - transform.y) / transform.k;

    const cx = imgSize.w / 2;
    const cy = imgSize.h / 2;

    const AXIS_COLOR = "#888888"; 
    const GRID_COLOR = "rgba(128, 128, 128, 0.3)";
    const LABEL_COLOR = "#888888"; 

    // X AXIS LOGIC
    let minValX, maxValX, stepX;
    if (type === 'polar') {
        const pxToUnit = fieldOfView / imgSize.w;
        minValX = startImgX * pxToUnit;
        maxValX = endImgX * pxToUnit;
    } else {
        const pxToUnit = fieldOfView / imgSize.w;
        minValX = (startImgX - cx) * pxToUnit; 
        maxValX = (endImgX - cx) * pxToUnit;
        if (minValX > maxValX) [minValX, maxValX] = [maxValX, minValX]; 
    }

    stepX = getNiceStep(Math.abs(maxValX - minValX), 8); 
    const firstTickX = Math.floor(minValX / stepX) * stepX;
    
    for (let v = firstTickX; v <= maxValX + stepX/2; v += stepX) {
        let imgPx;
        if (type === 'polar') { imgPx = (v / fieldOfView) * imgSize.w; } 
        else { imgPx = (v / (fieldOfView / imgSize.w)) + cx; }
        const screenX = imgPx * transform.k + transform.x;

        if (screenX >= -20 && screenX <= width + 20) {
            gridLines.push(<Line key={`gx${v}`} points={[screenX, 0, screenX, height]} stroke={GRID_COLOR} dash={[4, 4]} listening={false}/>);
            xTicks.push(
                <Group key={`tx${v}`} x={screenX} y={height}>
                    <Line points={[0, 0, 0, -6]} stroke={AXIS_COLOR} strokeWidth={1} />
                    <Text text={axisFormatter(v)} x={-15} y={-20} fill={AXIS_COLOR} fontSize={10} fontFamily="monospace" fontStyle="bold"/>
                </Group>
            );
        }
    }

    // Y AXIS LOGIC
    let minValY, maxValY, stepY;
    if (type === 'polar') {
        const pxToDeg = 360 / imgSize.h;
        minValY = (startImgY * pxToDeg) - 180;
        maxValY = (endImgY * pxToDeg) - 180;
    } else {
        const pxToUnit = fieldOfView / imgSize.h;
        minValY = (startImgY - cy) * pxToUnit;
        maxValY = (endImgY - cy) * pxToUnit;
    }

    stepY = getNiceStep(Math.abs(maxValY - minValY), 6); 
    const firstTickY = Math.floor(minValY / stepY) * stepY;

    for (let v = firstTickY; v <= maxValY + stepY/2; v += stepY) {
        let imgPy;
        if (type === 'polar') { imgPy = ((v + 180) / 360) * imgSize.h; } 
        else { imgPy = (v / (fieldOfView / imgSize.h)) + cy; }
        const screenY = imgPy * transform.k + transform.y;

        if (screenY >= -20 && screenY <= height + 20) {
            gridLines.push(<Line key={`gy${v}`} points={[0, screenY, width, screenY]} stroke={GRID_COLOR} dash={[4, 4]} listening={false}/>);
            yTicks.push(
                <Group key={`ty${v}`} x={0} y={screenY}>
                    <Line points={[0, 0, 6, 0]} stroke={AXIS_COLOR} strokeWidth={1} />
                    <Text text={axisFormatter(v)} x={8} y={-5} fill={AXIS_COLOR} fontSize={10} fontFamily="monospace" fontStyle="bold"/>
                </Group>
            );
        }
    }

    const labelX = type === 'polar' ? "Radius [arcsec]" : "RA Offset [arcsec]";
    const labelY = type === 'polar' ? "Azimuth [deg]" : "Dec Offset [arcsec]";

    return (
        <Group>
            <Rect x={0} y={0} width={width} height={height} stroke={AXIS_COLOR} strokeWidth={1} listening={false}/>
            {gridLines}
            {xTicks}
            {yTicks}
            <Text text={labelX} x={width/2 - 50} y={height - 30} fill={LABEL_COLOR} fontSize={11} fontStyle="bold"/>
            <Group x={15} y={height/2 + 50} rotation={-90}>
                <Text text={labelY} fill={LABEL_COLOR} fontSize={11} fontStyle="bold"/>
            </Group>
        </Group>
    );
};

// COLOR BAR COMPONENT
const ColorBar = ({ cmap, vizStats }) => {
    const gradients = {
        magma: 'linear-gradient(to top, #000004, #3b0f70, #8c2981, #de4968, #fcfdbf)',
        inferno: 'linear-gradient(to top, #000004, #420a68, #932667, #dd513a, #fcfdbf)',
        viridis: 'linear-gradient(to top, #440154, #31688e, #35b779, #fde725)',
        gray: 'linear-gradient(to top, black, white)',
    };
    let bg = gradients[cmap.replace('_r', '')] || gradients.magma;
    if (cmap && cmap.endsWith('_r')) bg = bg.replace('to top', 'to bottom');

    const min = vizStats ? vizStats.vmin_used : 0;
    const max = vizStats ? vizStats.vmax_used : 1;
    const mid = (min + max) / 2;
    const textColor = 'var(--disco-text-muted)';
    const borderColor = 'var(--disco-border)';

    return (
        <div style={{position: 'absolute', right: 10, bottom: 60, top: 60, width: 50, display: 'flex', flexDirection: 'column', alignItems: 'center', pointerEvents: 'none', zIndex:5}}>
            <div style={{fontSize:9, color:textColor, marginBottom:2}}>{scientificFormatter(max)}</div>
            <div style={{flex:1, width:14, background: bg, border:`1px solid ${borderColor}`, position:'relative'}}>
                <div style={{position:'absolute', top:'50%', right:0, width:4, height:1, background:textColor}}></div>
                <div style={{position:'absolute', top:'50%', right:18, fontSize:9, color:textColor, transform:'translateY(-50%)'}}>{scientificFormatter(mid)}</div>
            </div>
            <div style={{fontSize:9, color:textColor, marginTop:2}}>{scientificFormatter(min)}</div>
        </div>
    );
};

// MAIN VIEWER COMPONENT
const SimpleImageViewer = forwardRef(({ 
    imageSrc, type, fieldOfView = 10, onHoverRadius, externalHoverRadius, 
    activeTool = 'pan', beam = null, pixelScale = 0.03, vizStats = null, 
    profileData = null, showAxes = true, showColorbar = true,
    markers = [], onPlotClick = null, isMarkerMode = false,
    onUpdateRange = null, currentFitRange = [0, 0]
}, ref) => {
  const [image] = useImage(imageSrc);
  const [dims, setDims] = useState({ w: 0, h: 0 });
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 });
  const [cursorVal, setCursorVal] = useState(null);
  const [container, setContainer] = useState(null);
  
  // DRAG STATE
  const [dragStartR, setDragStartR] = useState(null);
  const [dragCurrentR, setDragCurrentR] = useState(null);
  
  const lastImageSize = useRef({ w: 0, h: 0 });
  const isFirstLoad = useRef(true);

  // CSS HELPER
  const getCssColor = (varName) => {
      const style = getComputedStyle(document.body);
      return style.getPropertyValue(varName).trim() || '#4ade80'; 
  };

  const containerRef = useCallback(node => { if (node !== null) setContainer(node); }, []);

  // VIEW RESET LOGIC
  const fitImage = useCallback(() => {
      if (!image || dims.w === 0 || dims.h === 0) return;
      const scale = Math.min(dims.w / image.width, dims.h / image.height) * 0.9;
      const cx = (dims.w - image.width * scale) / 2;
      const cy = (dims.h - image.height * scale) / 2;
      setTransform({ x: cx, y: cy, k: scale });
      lastImageSize.current = { w: image.width, h: image.height };
  }, [image, dims.w, dims.h]);

  useImperativeHandle(ref, () => ({ resetView: fitImage }));

  // RESIZE OBSERVER
  useEffect(() => {
    if (!container) return;
    const measure = () => {
        const { clientWidth, clientHeight } = container;
        if (clientWidth > 0 && clientHeight > 0) setDims(prev => (prev.w !== clientWidth || prev.h !== clientHeight) ? { w: clientWidth, h: clientHeight } : prev);
    };
    measure();
    const ro = new ResizeObserver(() => window.requestAnimationFrame(measure));
    ro.observe(container);
    return () => ro.disconnect();
  }, [container]);

  useEffect(() => {
    if (!image || dims.w === 0 || dims.h === 0) return;
    const currentW = image.width;
    const currentH = image.height;
    if (isFirstLoad.current || currentW !== lastImageSize.current.w) {
        fitImage();
        isFirstLoad.current = false;
    }
  }, [image, dims.w, dims.h, fitImage]); 

  // MOUSE & WHEEL HANDLERS
  const handleWheel = (e) => {
     e.evt.preventDefault();
     const scaleBy = 1.1;
     const stage = e.target.getStage();
     const oldScale = transform.k;
     const ptr = stage.getPointerPosition();
     const mousePointTo = { x: (ptr.x - transform.x) / oldScale, y: (ptr.y - transform.y) / oldScale };
     const newScale = e.evt.deltaY < 0 ? oldScale * scaleBy : oldScale / scaleBy;
     setTransform({ x: ptr.x - mousePointTo.x * newScale, y: ptr.y - mousePointTo.y * newScale, k: newScale });
  };

  const getRadiusFromPtr = (ptr) => {
      if (!image) return 0;
      const imgX = (ptr.x - transform.x) / transform.k;
      const imgY = (ptr.y - transform.y) / transform.k;
      if (type === 'polar') return (imgX / image.width) * fieldOfView;
      const cx = image.width / 2; const cy = image.height / 2;
      return Math.sqrt((imgX - cx)**2 + (imgY - cy)**2) * (fieldOfView / image.width);
  };

  const handleStageMouseDown = (e) => {
      if (activeTool === 'inspector') {
          const stage = e.target.getStage();
          const r = getRadiusFromPtr(stage.getPointerPosition());
          setDragStartR(r);
          setDragCurrentR(r);
      }
  };

  const handleStageMouseUp = (e) => {
      if (activeTool === 'inspector' && dragStartR !== null && dragCurrentR !== null) {
          const r1 = Math.min(dragStartR, dragCurrentR);
          const r2 = Math.max(dragStartR, dragCurrentR);
          if (Math.abs(r2 - r1) > 0.05) { if (onUpdateRange) onUpdateRange(r1, r2); } 
          else { if (onUpdateRange) onUpdateRange(0, 0); }
          setDragStartR(null);
          setDragCurrentR(null);
      } else if (isMarkerMode && onPlotClick && image) {
          const stage = e.target.getStage();
          const ptr = stage.getPointerPosition();
          const imgX = (ptr.x - transform.x) / transform.k;
          const imgY = (ptr.y - transform.y) / transform.k;
          if (imgX >= 0 && imgX <= image.width && imgY >= 0 && imgY <= image.height) { onPlotClick({ x: imgX, y: imgY }); }
      }
  };

  const handleMouseMove = (e) => {
      const stage = e.target.getStage();
      const ptr = stage.getPointerPosition();
      if (!ptr || !image) return;
      const r = getRadiusFromPtr(ptr);
      let vVal = "---";
      if (profileData && profileData.radius) {
          const idx = profileData.radius.findIndex(pr => pr >= r);
          if (idx !== -1 && profileData.intensity[idx] !== undefined) vVal = profileData.intensity[idx].toExponential(2);
      }
      setCursorVal({ r, v: vVal });
      if (onHoverRadius) onHoverRadius(r);
      if (activeTool === 'inspector' && dragStartR !== null) { setDragCurrentR(r); }
  };

  // OVERLAYS RENDERING
  const renderRangeOverlay = () => {
      if (!image) return null;
      let rMin, rMax;
      if (activeTool === 'inspector' && dragStartR !== null) { rMin = Math.min(dragStartR, dragCurrentR); rMax = Math.max(dragStartR, dragCurrentR); } 
      else if (currentFitRange && currentFitRange.length === 2 && currentFitRange[1] > currentFitRange[0]) { rMin = currentFitRange[0]; rMax = currentFitRange[1]; } 
      else return null;

      const pxPerArcsec = image.width / fieldOfView;
      const OVERLAY_COLOR = getCssColor('--disco-selection'); 

      if (type === 'polar') {
          return <Rect x={rMin*pxPerArcsec} y={0} width={(rMax-rMin)*pxPerArcsec} height={image.height} fill={OVERLAY_COLOR} opacity={0.2} stroke={OVERLAY_COLOR} strokeWidth={1/transform.k} dash={[5, 5]} listening={false}/>;
      } else {
          return <Ring x={image.width/2} y={image.height/2} innerRadius={rMin*pxPerArcsec} outerRadius={rMax*pxPerArcsec} fill={OVERLAY_COLOR} opacity={0.2} stroke={OVERLAY_COLOR} strokeWidth={1/transform.k} dash={[5, 5]} listening={false}/>;
      }
  };

  const renderSync = () => {
      if (externalHoverRadius === null || !image || activeTool !== 'inspector') return null;
      const pxPerArcsec = image.width / fieldOfView;
      const SYNC_COLOR = getCssColor('--disco-selection');
      if (type === 'polar') { const x = externalHoverRadius * pxPerArcsec; return <Line points={[x, 0, x, image.height]} stroke={SYNC_COLOR} strokeWidth={2/transform.k} dash={[10, 5]} listening={false}/>; }
      return <Circle x={image.width/2} y={image.height/2} radius={externalHoverRadius * pxPerArcsec} stroke={SYNC_COLOR} strokeWidth={2/transform.k} dash={[10, 5]} listening={false}/>;
  };

  const renderMarkers = () => {
      if (!markers || markers.length === 0) return null;
      return markers.map((m, i) => {
          const size = 10 / transform.k; const strokeW = 2 / transform.k;
          let ShapeComp = Circle;
          let shapeProps = { radius: size, fill: 'transparent', stroke: m.color, strokeWidth: strokeW };
          if (m.shape === 'square') { ShapeComp = Rect; shapeProps = { width: size*2, height: size*2, offsetX: size, offsetY: size, stroke: m.color, strokeWidth: strokeW }; }
          else if (m.shape === 'star') { ShapeComp = Star; shapeProps = { numPoints: 5, innerRadius: size/2, outerRadius: size, stroke: m.color, strokeWidth: strokeW }; }
          else if (m.shape === 'cross') {
             return (<Group key={i} x={m.x} y={m.y}><Line points={[-size, -size, size, size]} stroke={m.color} strokeWidth={strokeW} /><Line points={[size, -size, -size, size]} stroke={m.color} strokeWidth={strokeW} /><Text text={m.label} x={size + 5/transform.k} y={-size} fill={m.color} fontSize={12/transform.k} fontStyle="bold" shadowColor="black" shadowBlur={2}/></Group>);
          }
          return (<Group key={i} x={m.x} y={m.y}><ShapeComp {...shapeProps} /><Text text={m.label} x={size + 5/transform.k} y={-size} fill={m.color} fontSize={12/transform.k} fontStyle="bold" shadowColor="black" shadowBlur={2}/></Group>);
      });
  };

  const renderBeamHUD = () => {
      if(!beam || !pixelScale) return null;
      const screenX = (dims.w || 100) - 40;
      const screenY = (dims.h || 100) - 40;
      const majScreen = (beam.major / pixelScale) * transform.k;
      const minScreen = (beam.minor / pixelScale) * transform.k;
      return (
          <Group x={screenX} y={screenY}>
              <Ellipse radiusX={minScreen/2} radiusY={majScreen/2} rotation={-beam.pa} fill="white" stroke="black" strokeWidth={1} opacity={0.8}/>
              <Text x={-15} y={majScreen/2 + 5} text="Beam" fill="#888" fontSize={10}/>
          </Group>
      );
  };

  if (!imageSrc) return <div style={{display:'flex', height:'100%', alignItems:'center', justifyContent:'center', color:'var(--disco-text-muted)'}}>Processing...</div>;

  return (
    <div ref={containerRef} style={{ width: '100%', height: '100%', position: 'relative', background: 'var(--disco-chart-bg)', overflow: 'hidden', cursor: activeTool === 'inspector' ? 'crosshair' : (isMarkerMode ? 'crosshair' : (activeTool === 'pan' ? 'grab' : 'default')) }}>
      <Stage width={dims.w || 1} height={dims.h || 1} onWheel={handleWheel} onMouseMove={handleMouseMove} onMouseDown={handleStageMouseDown} onMouseUp={handleStageMouseUp} onMouseLeave={() => { if(onHoverRadius) onHoverRadius(null); setCursorVal(null); setDragStartR(null); }} draggable={activeTool === 'pan'} x={transform.x} y={transform.y} scaleX={transform.k} scaleY={transform.k} onDragMove={e => setTransform({x: e.target.x(), y: e.target.y(), k: transform.k})} style={{ opacity: dims.w > 0 ? 1 : 0, transition: 'opacity 0.2s' }}>
        <Layer>
            <KonvaImage image={image} listening={false} />
            {renderRangeOverlay()} 
            {renderSync()}
            {renderMarkers()}
        </Layer>
      </Stage>
      <div style={{position:'absolute', top:0, left:0, width:'100%', height:'100%', pointerEvents:'none'}}>
          {dims.w > 0 && showAxes && ( <Stage width={dims.w} height={dims.h}><Layer>{image && (<DynamicAxes width={dims.w} height={dims.h} fieldOfView={fieldOfView} transform={transform} type={type} imgSize={{w: image.width, h: image.height}}/>)}{renderBeamHUD()}</Layer></Stage> )}
      </div>
      {showColorbar && <ColorBar cmap={vizStats ? (vizStats.cmap_used || 'magma') : 'magma'} vizStats={vizStats}/>}
      
      {/* HUD & BADGES */}
      <div style={{position:'absolute', bottom: 10, left: 10, background: 'var(--disco-bg-panel)', border: '1px solid var(--disco-border)', padding: '6px 10px', borderRadius: 4, pointerEvents: 'none', minWidth: 100, boxShadow: '0 2px 5px rgba(0,0,0,0.2)'}}>
          <div style={{color:'var(--disco-accent)', fontSize:10, fontWeight:'bold', marginBottom:2}}>CURSOR</div>
          <div style={{color:'var(--disco-text)', fontSize:11, fontFamily:'monospace'}}>R: {cursorVal ? cursorVal.r.toFixed(3) : "---"}"</div>
          <div style={{color:'var(--disco-text)', fontSize:11, fontFamily:'monospace'}}>V: {cursorVal ? cursorVal.v : "---"}</div>
      </div>
      
      {activeTool === 'inspector' && (
          <div style={{position:'absolute', top:10, left:10, pointerEvents:'none'}}>
             <div style={{background:'var(--disco-selection)', color:'#000', padding:'2px 6px', borderRadius:2, fontSize:10, fontWeight:'800', boxShadow: '0 1px 3px rgba(0,0,0,0.2)'}}>INSPECTOR: DRAG TO SELECT RING</div>
          </div>
      )}
      
      {isMarkerMode && (
          <div style={{position:'absolute', top:10, left:10, pointerEvents:'none'}}>
             <div style={{background:'var(--disco-danger)', color:'#fff', padding:'2px 6px', borderRadius:2, fontSize:10, fontWeight:'800', boxShadow: '0 1px 3px rgba(0,0,0,0.2)'}}>MARKER MODE: CLICK TO ADD</div>
          </div>
      )}
      <div style={{position:'absolute', top:10, right:10, color:'var(--disco-text-muted)', fontSize:10, fontFamily:'monospace'}}>Zoom: {(transform.k * 100).toFixed(0)}%</div>
    </div>
  );
});

export default SimpleImageViewer;