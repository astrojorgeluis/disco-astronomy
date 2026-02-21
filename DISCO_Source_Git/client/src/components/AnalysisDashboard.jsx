import React, { useState, useEffect, useMemo, useRef } from 'react';
import { 
    Button, ButtonGroup, Icon, Popover, 
    HTMLSelect, NumericInput, Switch, Divider,
    Dialog, Classes, InputGroup, Label
} from "@blueprintjs/core";
import { 
    LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, 
    ResponsiveContainer, ReferenceLine, AreaChart, Area, ReferenceArea 
} from 'recharts';
import Split from 'react-split';
import SimpleImageViewer from '../SimpleImageViewer';

const AnalysisDashboard = ({ 
    results, profileData, fitStats, geometry, 
    onOpenMatplotlib, onAutoTune, onUpdateRange, activeTool, currentFitRange,
    isAutoTuning 
}) => {
    const [viewType, setViewType] = useState('deproj'); 
    const [currentImages, setCurrentImages] = useState(results || {});
    const [vizStats, setVizStats] = useState(null);
    const viewerRef = useRef(null); 

    // INTERACTION STATE
    const [dragStart, setDragStart] = useState(null);
    const [dragEnd, setDragEnd] = useState(null);
    const [isDragging, setIsDragging] = useState(false);

    // VISUAL STATE
    const [showAxes, setShowAxes] = useState(true);
    const [showColorbar, setShowColorbar] = useState(true);
    const [invertCmap, setInvertCmap] = useState(false);

    const [vizParams, setVizParams] = useState({ cmap: 'magma', stretch: 'asinh', vmin: 0, vmax: 4, vmax_percentile: null, contours: false, contour_levels: 5 });
    const [manualMinStr, setManualMinStr] = useState("0");
    const [manualMaxStr, setManualMaxStr] = useState("4");
    
    const [useLogScale, setUseLogScale] = useState(true);
    const [syncedRadius, setSyncedRadius] = useState(null);
    
    // MARKER STATE
    const [markers, setMarkers] = useState([]);
    const [isMarkerMode, setIsMarkerMode] = useState(false);
    const [markerDialogOpen, setMarkerDialogOpen] = useState(false);
    const [tempMarkerPos, setTempMarkerPos] = useState(null);
    const [newMarkerName, setNewMarkerName] = useState("Feature 1");
    const [newMarkerShape, setNewMarkerShape] = useState("circle");
    const [newMarkerColor, setNewMarkerColor] = useState("#00ff00");

    const beamInfo = geometry ? geometry.beam : null;

    useEffect(() => { if(results) setCurrentImages(results); }, [results]);

    // EVENT HANDLERS
    const handlePlotClick = (pos) => { if (isMarkerMode) { setTempMarkerPos(pos); setNewMarkerName(`Point ${markers.length + 1}`); setMarkerDialogOpen(true); setIsMarkerMode(false); } };
    const handleSaveMarker = () => { if (tempMarkerPos) { setMarkers(prev => [...prev, { x: tempMarkerPos.x, y: tempMarkerPos.y, label: newMarkerName, shape: newMarkerShape, color: newMarkerColor, view: viewType }]); } setMarkerDialogOpen(false); setTempMarkerPos(null); };
    const handleDeleteMarker = (index) => { setMarkers(prev => prev.filter((_, i) => i !== index)); };

    const handleDownloadCSV = () => {
        if (!profileData || !profileData.radius) return;
        const { radius, intensity, raw_intensity } = profileData;
        const rows = [["Radius [arcsec]", "Intensity [Jy/beam]", "Brightness Temp [K]"]];
        radius.forEach((r, i) => {const rawVal = raw_intensity ? raw_intensity[i] : 0; const tbVal = intensity[i]; rows.push([r, intensity[i], tbVal]);});
        const csvContent = rows.map(e => e.join(",")).join("\n");
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.setAttribute("href", url);
        link.setAttribute("download", "radial_profile.csv");
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    };


    const handleMouseDown = (e) => { 
        if (activeTool !== 'inspector' || !e) return; 
        setIsDragging(true); 
        if (e.activeLabel) setDragStart(Number(e.activeLabel)); 
        setDragEnd(null); 
    };
    
    const handleMouseMove = (e) => { 
        if (activeTool === 'inspector' && e && e.activePayload) { 
            setSyncedRadius(e.activePayload[0].payload.radius); 
        } else if (activeTool === 'inspector') { 
            setSyncedRadius(null); 
        } 
        if (isDragging && e && e.activeLabel) { 
            setDragEnd(Number(e.activeLabel)); 
        } 
    };
    
    const handleMouseUp = () => { 
        if (isDragging && dragStart !== null) { 
            if (dragEnd !== null && Math.abs(dragEnd - dragStart) > 0.05) { 
                const r1 = Math.min(dragStart, dragEnd); 
                const r2 = Math.max(dragStart, dragEnd); 
                if (onUpdateRange) onUpdateRange(r1, r2); 
            } else { 
                if (onUpdateRange) onUpdateRange(0, 0); 
            } 
        } 
        setIsDragging(false); 
        setDragStart(null); 
        setDragEnd(null); 
    };

    // VISUALIZATION LOGIC
    const updateVisualization = async (overrideParams = {}) => {
        const nextParams = { ...vizParams, ...overrideParams };
        let baseCmap = overrideParams.cmap || vizParams.cmap;
        baseCmap = baseCmap.replace('_r', '');
        let finalCmap = invertCmap ? `${baseCmap}_r` : baseCmap;
        const finalStretch = overrideParams.stretch || vizParams.stretch;
        let payload = { type: viewType, cmap: finalCmap, stretch: finalStretch, contours: nextParams.contours, contour_levels: nextParams.contour_levels, show_axes: false, show_grid: false, show_colorbar: false, show_beam: false, title: "", dpi: 100 };
        if (overrideParams.hasOwnProperty('vmax_percentile')) { payload.vmax_percentile = overrideParams.vmax_percentile; payload.vmin = null; payload.vmax = null; } 
        else { let valMin = parseFloat(manualMinStr); let valMax = parseFloat(manualMaxStr); if (isNaN(valMin)) valMin = 0.0; if (isNaN(valMax)) valMax = 4.0; payload.vmin = valMin; payload.vmax = valMax; payload.vmax_percentile = null; }
        setVizParams(prev => ({ ...prev, cmap: baseCmap, stretch: finalStretch, vmax_percentile: payload.vmax_percentile || prev.vmax_percentile, contours: payload.contours, contour_levels: payload.contour_levels }));
        try { const response = await fetch('http://localhost:8000/render_plot', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); if (!response.ok) return; const data = await response.json(); if (data.image) setCurrentImages(prev => ({ ...prev, [viewType]: data.image })); if (data.stats) { data.stats.cmap_used = finalCmap; setVizStats(data.stats); setManualMinStr(String(data.stats.vmin_used)); setManualMaxStr(String(data.stats.vmax_used)); } } catch (e) { console.error("Viz Error:", e); }
    };

    useEffect(() => { updateVisualization(); }, [invertCmap]);
    useEffect(() => { if (vizStats) { setManualMinStr(String(vizStats.vmin_used)); setManualMaxStr(String(vizStats.vmax_used)); } }, [vizStats]);

    // UI COMPONENTS: SETTINGS PANEL
    const vizSettingsContent = (
        <div style={{padding: 15, width: 300, background:'var(--disco-bg-panel)', border:'1px solid var(--disco-border)'}}>
            <h5 style={{marginBottom:15, color:'var(--disco-text)', borderBottom:'1px solid var(--disco-border)', paddingBottom:5}}>Display Configuration</h5>
            <div className="compact-label">Intensity Limits</div>
            <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:10, marginBottom:10}}>
                <NumericInput fill value={manualMinStr} onValueChange={(_, vStr) => setManualMinStr(vStr)} buttonPosition="none" placeholder="Min"/>
                <NumericInput fill value={manualMaxStr} onValueChange={(_, vStr) => setManualMaxStr(vStr)} buttonPosition="none" placeholder="Max"/>
            </div>
            <div style={{display:'flex', gap:5, marginBottom:15}}>
                <Button fill small text="Apply" icon="refresh" onClick={() => updateVisualization({})}/>
                <Button fill small text="Auto" onClick={() => updateVisualization({ vmax_percentile: 100 })}/>
            </div>
            <Divider style={{marginBottom:15}}/>
            <div className="compact-label">Color & Stretch</div>
            <div style={{display:'flex', gap:10, marginBottom:10}}>
                <HTMLSelect fill value={vizParams.cmap} onChange={e => updateVisualization({cmap: e.target.value})} options={['magma', 'inferno', 'viridis', 'seismic', 'gray', 'jet']} />
                <HTMLSelect fill value={vizParams.stretch} onChange={e => updateVisualization({stretch: e.target.value})} options={['asinh', 'linear', 'log', 'sqrt']} />
            </div>
            <Switch label="Invert Colormap" checked={invertCmap} onChange={() => setInvertCmap(!invertCmap)} style={{marginBottom:15}}/>
            <Divider style={{marginBottom:15}}/>
            <div className="compact-label">Overlays</div>
            <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:5}}>
                <Switch label="Contours" checked={vizParams.contours} onChange={() => updateVisualization({ contours: !vizParams.contours })} style={{marginBottom:0}}/>
                {vizParams.contours && (<div style={{display:'flex', alignItems:'center', gap:5}}><span style={{fontSize:10}}>Lvls:</span><NumericInput style={{width: 50}} buttonPosition="none" min={1} max={50} value={vizParams.contour_levels} onValueChange={(v) => updateVisualization({ contour_levels: v })} small/></div>)}
            </div>
            <Switch label="Axes & Labels" checked={showAxes} onChange={() => setShowAxes(!showAxes)} />
            <Switch label="Colorbar" checked={showColorbar} onChange={() => setShowColorbar(!showColorbar)} />
            <Divider style={{marginBottom:15}}/>
            <Button small fill text="Clear Markers" icon="trash" intent="danger" onClick={() => setMarkers(prev => prev.filter(m => m.view !== viewType))} disabled={markers.filter(m => m.view === viewType).length === 0} />
        </div>
    );

    // DATA PROCESSING MEMOS
    const chartData = useMemo(() => {
        if (!profileData) return [];
        return profileData.radius.map((r, i) => { let val = profileData.intensity[i]; if (useLogScale && val <= 0) val = 0.001; return { radius: r, intensity: val }; });
    }, [profileData, useLogScale]);

    const cumulativeData = useMemo(() => {
        if (!profileData || !profileData.radius) return [];
        let cumSum = 0; const data = []; const radii = profileData.radius; const intensities = profileData.intensity;
        for (let i = 0; i < radii.length; i++) { const r = radii[i]; const val = Math.max(0, intensities[i] || 0); cumSum += val * r; data.push({ radius: r, cumulative: cumSum }); }
        const total = cumSum > 0 ? cumSum : 1; return data.map(d => ({ radius: d.radius, cumulative: (d.cumulative / total) * 100 }));
    }, [profileData]);

    const getSafeRange = () => {
        let x1 = 0, x2 = 0;
        if (isDragging && dragStart !== null && dragEnd !== null) {
            x1 = Math.min(dragStart, dragEnd);
            x2 = Math.max(dragStart, dragEnd);
        } else if (currentFitRange && currentFitRange.length === 2 && currentFitRange[1] > currentFitRange[0]) {
            x1 = currentFitRange[0];
            x2 = currentFitRange[1];
        }
        if (!Number.isFinite(x1) || !Number.isFinite(x2) || x2 <= x1) return null;
        return { x1, x2 };
    };

    const safeRange = getSafeRange();

    // STATS WIDGET RENDERER
    const renderStatsWidget = () => (
        <div className="chart-container" style={{padding:10, flex:1, display:'flex', flexDirection:'column', overflow:'auto', minHeight: 120}}>
             <div className="compact-label" style={{color:'var(--disco-selection)', display:'flex', alignItems:'center', gap:5}}><Icon icon="locate" size={12}/> CURSOR PROBE</div>
             {activeTool === 'inspector' && syncedRadius !== null ? (
                 <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:8}}>
                     <div className="stats-card"><div className="stats-label">RADIUS</div><div className="stats-value">{syncedRadius.toFixed(4)}"</div></div>
                     <div className="stats-card" style={{border:'1px solid var(--disco-warning)'}}><div className="stats-label" style={{color:'var(--disco-warning)'}}>INTENSITY</div><div className="stats-value">{(() => { const point = chartData.find(p => Math.abs(p.radius - syncedRadius) < 0.05); return point ? point.intensity.toExponential(3) : "---"; })()} K</div></div>
                     <div className="stats-card"><div className="stats-label">OFFSET X</div><div className="stats-value">+{(syncedRadius/Math.sqrt(2)).toFixed(2)}"</div></div>
                     <div className="stats-card"><div className="stats-label">OFFSET Y</div><div className="stats-value">-{(syncedRadius/Math.sqrt(2)).toFixed(2)}"</div></div>
                 </div>
             ) : (
                 <div style={{flex:1, display:'flex', alignItems:'center', justifyContent:'center', textAlign:'center', color:'var(--disco-text-muted)', fontStyle:'italic', background:'rgba(125,125,125,0.05)', borderRadius:4}}><div><Icon icon="locate" style={{marginBottom:5}}/><br/>Use <b>Inspector</b> to probe.</div></div>
             )}
             {fitStats && (
                 <div style={{marginTop: 15, paddingTop:10, borderTop:'1px solid var(--disco-border)'}}>
                     <div className="compact-label" style={{marginBottom:5, color:'var(--disco-warning)', display:'flex', alignItems:'center', gap:5}}><Icon icon="pulse" size={12}/> RING FIT (Gaussian)</div>
                     <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:8}}>
                         <div className="stats-card"><div className="stats-label">PEAK RADIUS</div><div className="stats-value">{fitStats.peak_radius.toFixed(3)}"</div></div>
                         <div className="stats-card"><div className="stats-label">WIDTH (FWHM)</div><div className="stats-value">{fitStats.fwhm.toFixed(3)}"</div></div>
                     </div>
                 </div>
             )}
        </div>
    );

    if (!results) return <div className="bp5-non-ideal-state" style={{color:'var(--disco-text-muted)'}}>Run pipeline...</div>;

    return (
        <div style={{ width:'100%', height:'100%', display:'flex', flexDirection:'column', background:'var(--disco-bg-panel)', overflow:'hidden' }}>
            {/* TOOLBAR */}
            <div className="dashboard-toolbar">
                <ButtonGroup minimal>
                    {['deproj', 'model', 'residuals', 'polar'].map(type => (
                        <Button key={type} className={`view-selector-btn ${viewType === type ? 'bp5-active' : ''}`} text={type.charAt(0).toUpperCase() + type.slice(1)} onClick={() => setViewType(type)}/>
                    ))}
                </ButtonGroup>
                <div style={{width:1, height:16, background:'var(--disco-border)'}} />
                <ButtonGroup minimal>
                    <Popover content={vizSettingsContent} position="bottom"><Button icon="settings" small text="Settings" /></Popover>
                    <Button icon="zoom-to-fit" small text="Reset View" onClick={() => viewerRef.current && viewerRef.current.resetView()}/>
                    <Button icon="clean" small intent="success" text="Auto-Tune Geometry" onClick={onAutoTune} loading={isAutoTuning} />
                    <Divider />
                    <Button icon="map-marker" active={isMarkerMode} intent={isMarkerMode ? "danger" : "none"} text={isMarkerMode ? "Cancel" : "Add Marker"} onClick={() => setIsMarkerMode(!isMarkerMode)}/>
                </ButtonGroup>
                <div style={{flex:1}} />
                <ButtonGroup minimal>
                    <Button icon="chart" small text="Matplotlib" onClick={() => onOpenMatplotlib(viewType)} />
                    <Button icon="download" small title="Save FITS" onClick={() => window.open(`http://localhost:8000/download_fits?type=${viewType}`, '_blank')}/>
                </ButtonGroup>
            </div>
            
            {/* MAIN SPLIT VIEW */}
            <Split sizes={[60, 40]} minSize={300} gutterSize={4} className="split-flex">
                <div style={{position:'relative', overflow:'hidden', background:'var(--disco-chart-bg)', width:'100%', height:'100%'}}>
                    <SimpleImageViewer 
                        ref={viewerRef} 
                        imageSrc={currentImages[viewType]} 
                        type={viewType} 
                        fieldOfView={geometry ? (viewType === 'polar' ? geometry.fov_polar : geometry.fov_cartesian) : 10} 
                        beam={geometry ? geometry.beam : null} 
                        activeTool={activeTool} 
                        onHoverRadius={(r) => activeTool === 'inspector' && setSyncedRadius(r)} 
                        onUpdateRange={onUpdateRange} 
                        currentFitRange={currentFitRange}
                        externalHoverRadius={syncedRadius} 
                        vizStats={vizStats} 
                        profileData={profileData} 
                        showAxes={showAxes} 
                        showColorbar={showColorbar}
                        markers={markers.filter(m => m.view === viewType)} 
                        onPlotClick={handlePlotClick}
                        isMarkerMode={isMarkerMode}
                    />
                </div>
                <div style={{display:'flex', flexDirection:'column', background:'var(--disco-bg-panel)', width:'100%', height:'100%', borderLeft:'1px solid var(--disco-border)'}}>
                    
                    {/* RADIAL PROFILE CHART */}
                    <div className="chart-container" style={{flex: 1, padding:10, minHeight:0, display:'flex', flexDirection:'column'}}>
                         <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:5}}>
                             <div className="compact-label" style={{color:'var(--disco-warning)', display:'flex', alignItems:'center', gap:5}}>
                                <Icon icon="series-derived" size={12}/> RADIAL PROFILE
                             </div>
                             
                             <div style={{display:'flex', gap: 5}}>
                                <Button 
                                    icon="download" 
                                    text="CSV" 
                                    intent="success" 
                                    minimal={true} 
                                    small={true}
                                    title="Download data as CSV"
                                    disabled={!profileData} 
                                    onClick={handleDownloadCSV} 
                                />
                                <HTMLSelect 
                                    className="bp5-small" 
                                    minimal 
                                    value={useLogScale ? "log" : "lin"} 
                                    onChange={(e) => setUseLogScale(e.target.value === "log")} 
                                    options={[{label: "Linear", value: "lin"}, {label: "Log", value: "log"}]}
                                />
                             </div>
                         </div>
                         <div style={{flex:1, minHeight:0}}>
                             <ResponsiveContainer width="100%" height="100%">
                                <LineChart 
                                    data={chartData} 
                                    onMouseMove={handleMouseMove} onMouseDown={handleMouseDown} onMouseUp={handleMouseUp}
                                    onMouseLeave={()=> { if(activeTool === 'inspector') setSyncedRadius(null); setIsDragging(false); }}
                                    style={{cursor: activeTool === 'inspector' ? 'crosshair' : 'default'}}
                                >
                                    <CartesianGrid strokeDasharray="3 3" stroke="var(--disco-grid)" vertical={false} />
                                    <XAxis dataKey="radius" type="number" domain={['dataMin', 'dataMax']} tick={{fill:'var(--disco-text-muted)', fontSize:9}} />
                                    <YAxis scale={useLogScale ? 'log' : 'linear'} domain={['auto', 'auto']} allowDataOverflow={true} tick={{fill:'var(--disco-text-muted)', fontSize:9}} width={35} />
                                    <Tooltip contentStyle={{backgroundColor:'var(--disco-bg-panel)', borderColor:'var(--disco-border)', color:'var(--disco-text)'}} itemStyle={{color:'var(--disco-text)'}} labelStyle={{color:'var(--disco-text-muted)'}} />
                                    <Line type="monotone" dataKey="intensity" stroke="var(--disco-warning)" dot={false} strokeWidth={1.5} isAnimationActive={false} />
                                    {syncedRadius !== null && <ReferenceLine x={syncedRadius} stroke="var(--disco-selection)" strokeDasharray="3 3" isFront={true}/>}
                                    
                                    {safeRange && (
                                        <ReferenceArea x1={safeRange.x1} x2={safeRange.x2} strokeOpacity={0.3} fill="var(--disco-selection)" fillOpacity={0.1} />
                                    )}
                                </LineChart>
                            </ResponsiveContainer>
                         </div>
                    </div>
                    <div style={{height:1, background:'var(--disco-border)'}} />
                    
                    {/* CUMULATIVE FLUX CHART */}
                    <div className="chart-container" style={{flex: 1, padding:10, minHeight:0, display:'flex', flexDirection:'column'}}>
                        <div className="compact-label" style={{marginBottom:5, color:'var(--disco-info)', display:'flex', alignItems:'center', gap:5}}><Icon icon="chart" size={12}/> CUMULATIVE FLUX</div>
                        <div style={{flex:1, minHeight:0}}>
                            <ResponsiveContainer width="100%" height="100%">
                                <AreaChart 
                                    data={cumulativeData}
                                    onMouseMove={handleMouseMove} onMouseDown={handleMouseDown} onMouseUp={handleMouseUp}
                                    onMouseLeave={()=> { if(activeTool === 'inspector') setSyncedRadius(null); setIsDragging(false); }}
                                    style={{cursor: activeTool === 'inspector' ? 'crosshair' : 'default'}}
                                >
                                    <defs><linearGradient id="colorCum" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="var(--disco-info)" stopOpacity={0.3}/><stop offset="95%" stopColor="var(--disco-info)" stopOpacity={0}/></linearGradient></defs>
                                    <CartesianGrid strokeDasharray="3 3" stroke="var(--disco-grid)" vertical={false} />
                                    
                                    <XAxis dataKey="radius" type="number" domain={['dataMin', 'dataMax']} hide />
                                    <YAxis tick={{fill:'var(--disco-text-muted)', fontSize:9}} domain={[0, 100]} unit="%" width={35}/>
                                    
                                    <Tooltip contentStyle={{backgroundColor:'var(--disco-bg-panel)', borderColor:'var(--disco-border)'}} itemStyle={{color:'var(--disco-text)'}} labelStyle={{color:'var(--disco-text-muted)'}} />
                                    <Area type="monotone" dataKey="cumulative" stroke="var(--disco-info)" fill="url(#colorCum)" strokeWidth={2} isAnimationActive={false} />
                                    
                                    {syncedRadius !== null && <ReferenceLine x={syncedRadius} stroke="var(--disco-selection)" strokeDasharray="3 3" isFront={true} />}
                                    
                                    {safeRange && (
                                        <ReferenceArea x1={safeRange.x1} x2={safeRange.x2} strokeOpacity={0.3} fill="var(--disco-selection)" fillOpacity={0.1} />
                                    )}
                                </AreaChart>
                            </ResponsiveContainer>
                        </div>
                    </div>
                    <div style={{height:1, background:'var(--disco-border)'}} />
                    {renderStatsWidget()}
                </div>
            </Split>
            <Dialog isOpen={markerDialogOpen} onClose={() => setMarkerDialogOpen(false)} title="Add New Marker" className={document.body.classList.contains('bp5-dark') ? 'bp5-dark' : ''} style={{width: 300}}>
                <div className={Classes.DIALOG_BODY}>
                    <Label>Marker Name <InputGroup value={newMarkerName} onChange={e => setNewMarkerName(e.target.value)} /></Label>
                    <Label style={{marginTop:10}}>Shape <HTMLSelect fill value={newMarkerShape} onChange={e => setNewMarkerShape(e.target.value)} options={[{label:'Circle',value:'circle'},{label:'Square',value:'square'},{label:'Cross',value:'cross'},{label:'Star',value:'star'}]} /></Label>
                    <Label style={{marginTop:10}}>Color <HTMLSelect fill value={newMarkerColor} onChange={e => setNewMarkerColor(e.target.value)} options={[{label:'Green',value:'#00ff00'},{label:'Red',value:'#ff0000'},{label:'Cyan',value:'#00ffff'},{label:'Magenta',value:'#ff00ff'},{label:'Yellow',value:'#ffff00'},{label:'White',value:'#ffffff'}]} /></Label>
                </div>
                <div className={Classes.DIALOG_FOOTER}><div className={Classes.DIALOG_FOOTER_ACTIONS}><Button onClick={() => setMarkerDialogOpen(false)}>Cancel</Button><Button intent="primary" onClick={handleSaveMarker}>Add</Button></div></div>
            </Dialog>
        </div>
    );
};

export default AnalysisDashboard;
