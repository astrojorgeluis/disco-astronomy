import React, { useState, useCallback, useEffect, useRef } from 'react';
import { Mosaic, MosaicWindow, MosaicContext, getLeaves } from 'react-mosaic-component';
import { 
  Button, Classes, Slider, NumericInput, HTMLTable, Icon, 
  ButtonGroup, Divider, Menu, MenuItem, Popover, Position,
  Dialog, OverlayToaster, Spinner
} from "@blueprintjs/core";
import InteractiveViewer from './InteractiveViewer';
import MatplotlibWidget from './MatplotlibWidget';
import AnalysisDashboard from './components/AnalysisDashboard'; 

// TOASTER UTILITIES
let toasterInstance = null;
const showToast = async (props) => {
    if (!toasterInstance) {
        toasterInstance = await OverlayToaster.createAsync({ position: Position.BOTTOM_RIGHT });
    }
    toasterInstance.show(props);
};

// LAYOUT CONSTANTS
const WINDOWS = {
  CONTROLS: 'Render Configuration',
  VIEWER: 'Image Viewer',
  CATALOG: 'File Browser',
  ANALYSIS: 'Analysis Results'
};

const INITIAL_LAYOUT = {
    direction: 'row',
    splitPercentage: 20,
    first: {
        direction: 'column',
        first: WINDOWS.CONTROLS, 
        splitPercentage: 38,     
        second: WINDOWS.VIEWER   
    },
    second: {
            direction: 'row',
            first: WINDOWS.CATALOG,  
            splitPercentage: 15,     
            second: WINDOWS.ANALYSIS  
        }
};

// UI HELPERS
const SmartNumericInput = ({ value, onValueChange, ...props }) => {
    const [strVal, setStrVal] = useState(String(value || 0));
    useEffect(() => {
        const num = parseFloat(strVal);
        if (Math.abs(num - value) > 1e-6 || (isNaN(num) && !isNaN(value))) {
             const display = Math.round(value * 1000) / 1000;
             setStrVal(String(display));
        }
    }, [value]);
    const handleChange = (vNum, vStr) => { setStrVal(vStr); onValueChange(vNum); };
    return <NumericInput {...props} value={strVal} onValueChange={handleChange} />;
};

const ControlRow = ({ label, value, onChange, min, max, unit }) => {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '80px 1fr 65px', gap: 8, alignItems: 'center', marginBottom: 6 }}>
        <div className="compact-label">{label}</div>
        <Slider min={min} max={max} stepSize={0.1} labelRenderer={false} value={value} onChange={onChange} className="compact-slider"/>
        <SmartNumericInput fill={true} value={value} onValueChange={onChange} buttonPosition="none" min={min} max={max} small rightElement={unit ? <span style={{lineHeight:'20px', paddingRight:4, opacity:0.6, fontSize:11}}>{unit}</span> : null} />
    </div>
  );
};

const WindowControls = ({ path }) => {
  const { mosaicActions } = React.useContext(MosaicContext);
  return (
    <ButtonGroup minimal style={{ marginRight: 4 }}>
      <Button icon="maximize" small title="Expand/Restore" onClick={() => mosaicActions.expand(path)} />
      <Button icon="cross" small title="Close Window" intent="danger" onClick={() => mosaicActions.remove(path)} />
    </ButtonGroup>
  );
};

const removeWindowNode = (tree, windowId) => {
    if (!tree) return null;
    if (typeof tree === 'string') return tree === windowId ? null : tree;
    const first = removeWindowNode(tree.first, windowId);
    const second = removeWindowNode(tree.second, windowId);
    if (first && second) return { ...tree, first, second }; 
    return first || second;
};

function App() {
  const [darkMode, setDarkMode] = useState(true);
  const [layout, setLayout] = useState(INITIAL_LAYOUT);
  
  // UI STATE
  const [isSimbadLoading, setIsSimbadLoading] = useState(false);
  const [isPipelineLoading, setIsPipelineLoading] = useState(false);
  const [isAutoTuning, setIsAutoTuning] = useState(false);
  const [simbadResults, setSimbadResults] = useState(null);
  const [isSimbadModalOpen, setIsSimbadModalOpen] = useState(false);
  const [isMatplotlibModalOpen, setIsMatplotlibModalOpen] = useState(false);
  const [matplotlibInitialType, setMatplotlibInitialType] = useState('data');
  
  // DATA STATE
  const [filename, setFilename] = useState("No Data Loaded");
  const [activeTool, setActiveTool] = useState('pan'); 
  const [imageSrc, setImageSrc] = useState(null);
  const [simbadInfo, setSimbadInfo] = useState([]); 
  const [inlinePlots, setInlinePlots] = useState({});

  const [params, setParams] = useState({ incl: 0, pa: 0, cx: 300, cy: 300, rout: 1.2, fit_rmin: 0.0, fit_rmax: 0.0 });
  const [results, setResults] = useState(null); 
  const [profileData, setProfileData] = useState(null); 
  const [fitStats, setFitStats] = useState(null); 
  const [imgDimensions, setImgDimensions] = useState(null);
  const [pixelScale, setPixelScale] = useState(0.03); 
  const [headerInfo, setHeaderInfo] = useState([]); 
  const [geometry, setGeometry] = useState(null);
  
  const fileInputRef = useRef(null);

  // WINDOW MANAGEMENT
  const toggleWindow = (windowId) => {
      setLayout(currentLayout => {
          const openWindows = getLeaves(currentLayout) || [];
          if (openWindows.includes(windowId)) return removeWindowNode(currentLayout, windowId);
          if (!currentLayout) return windowId;
          return { direction: 'row', first: currentLayout, second: windowId, splitPercentage: 70 };
      });
  };

  const ViewMenu = (
      <Menu>
          <MenuItem text="Reset Layout" icon="reset" onClick={() => setLayout(INITIAL_LAYOUT)} />
          <Divider />
          <div className="compact-label" style={{paddingLeft:10, marginBottom:5, marginTop:5}}>WINDOWS</div>
          {Object.values(WINDOWS).map(id => {
             const isOpen = getLeaves(layout)?.includes(id);
             return ( <MenuItem key={id} text={id} icon={isOpen ? "tick" : "blank"} onClick={() => toggleWindow(id)} shouldDismissPopover={false} /> );
          })}
      </Menu>
  );

  const SettingsMenu = ( <Menu> <MenuItem icon={darkMode ? "flash" : "moon"} text={darkMode ? "Switch to Light Mode" : "Switch to Dark Mode"} onClick={() => setDarkMode(!darkMode)} /> </Menu> );

  // LIFECYCLE & SESSION
  const handleExit = async () => {
      if (!window.confirm("Close session? Unsaved data will be lost.")) return;
      try {
          await fetch('http://localhost:8000/reset_session', { method: 'POST' });
          setFilename("No Data Loaded"); setImageSrc(null); setResults(null); setProfileData(null); setFitStats(null); setHeaderInfo([]); setSimbadResults(null); setGeometry(null); setImgDimensions(null);
          setParams({ incl: 0, pa: 0, cx: 300, cy: 300, rout: 1.2, fit_rmin: 0.0, fit_rmax: 0.0 });
          showToast({ message: "Session closed.", intent: "success", icon: "trash" });
      } catch (e) { console.error("Exit failed", e); }
  };

  useEffect(() => {
      fetch('http://localhost:8000/reset_session', { method: 'POST' }).catch(e => console.warn("Cleanup failed", e));
      const handleTabClose = () => { navigator.sendBeacon('http://localhost:8000/reset_session'); };
      window.addEventListener('beforeunload', handleTabClose);
      return () => window.removeEventListener('beforeunload', handleTabClose);
  }, []); 
  
  useEffect(() => {
    const body = document.body;
    if (darkMode) { body.classList.add('bp5-dark'); body.style.backgroundColor = 'var(--disco-bg-app)'; } 
    else { body.classList.remove('bp5-dark'); body.style.backgroundColor = 'var(--disco-bg-app)'; }
  }, [darkMode]);

  const handleOpenMatplotlibModal = (type = 'data') => {
      setMatplotlibInitialType(type);
      setIsMatplotlibModalOpen(true);
  };
  
  const toggleFullscreen = () => {
      if (!document.fullscreenElement) { document.documentElement.requestFullscreen().catch((e) => { console.error(`FS Error: ${e.message}`); }); } 
      else { if (document.exitFullscreen) { document.exitFullscreen(); } }
  };
  
  // SIMBAD HANDLER
  const handleRunSimbad = async () => {
      setIsSimbadLoading(true);
      try {
          const response = await fetch('http://localhost:8000/query_simbad');
          if (!response.ok) throw new Error("Error querying Simbad");
          const data = await response.json();
          if (data.found) {
              setSimbadResults(data.data);
              setIsSimbadModalOpen(true);
              showToast({ message: "Simbad data retrieved.", intent: "success", icon: "tick", timeout: 3000 });
          } else {
              showToast({ message: "No objects found in Simbad.", intent: "warning", icon: "search", timeout: 3000 });
          }
      } catch (e) {
          console.error(e);
          showToast({ message: "Simbad Error", intent: "danger", icon: "error" });
      } finally {
          setIsSimbadLoading(false);
      }
  };

  // FILE HANDLERS
  const handleFileUpload = async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    const extension = file.name.split('.').pop().toLowerCase();

    if (extension === 'json') {
        const reader = new FileReader();
        reader.onload = async (e) => { 
            try {
                const session = JSON.parse(e.target.result);
                if (session.params) setParams(session.params);
                const targetFile = session.filename || session.file_path; 
                if (targetFile) {
                    try {
                        const response = await fetch('http://localhost:8000/load_local', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ filename: targetFile })
                        });
                        if (response.ok) {
                            const data = await response.json();
                            const previewRes = await fetch('http://localhost:8000/preview');
                            const previewData = await previewRes.json();
                            setImageSrc(previewData.image);
                            setImgDimensions({ width: data.shape[1], height: data.shape[0] });
                            setFilename(data.filename);
                            setPixelScale(data.pixel_scale); 
                            const headerRes = await fetch('http://localhost:8000/get_header');
                            const headerData = await headerRes.json();
                            setHeaderInfo(headerData.header || []);
                        }
                    } catch (e) { console.warn("Auto-load failed", e); }
                }
                showToast({ message: "Session Restored", intent: "success", icon: "tick", timeout: 2000 });
            } catch (err) {
                console.error(err);
                showToast({ message: "Invalid session file.", intent: "danger" });
            }
        };
        reader.readAsText(file);
        return;
    }

    const formData = new FormData();
    formData.append("file", file);

    try {
        const uploadResponse = await fetch('http://localhost:8000/upload', { method: 'POST', body: formData });
        if (!uploadResponse.ok) throw new Error("Upload failed");
        const uploadData = await uploadResponse.json();
        const previewResponse = await fetch('http://localhost:8000/preview');
        if (!previewResponse.ok) throw new Error("Preview failed");
        const previewData = await previewResponse.json();
        setImageSrc(previewData.image);
        setImgDimensions({ width: uploadData.shape[1], height: uploadData.shape[0] });
        setFilename(file.name);
        const realWidth = uploadData.shape[1];
        const realHeight = uploadData.shape[0];
        const scale = uploadData.pixel_scale || 0.03;
        setPixelScale(scale);
        try {
            const headerRes = await fetch('http://localhost:8000/get_header');
            const headerData = await headerRes.json();
            setHeaderInfo(headerData.header || []);
        } catch(e) { console.error("Header fetch error", e); }
        setParams(prev => ({ ...prev, cx: realWidth / 2, cy: realHeight / 2 }));
        showToast({ message: "FITS loaded", intent: "success", timeout: 2000 });
    } catch (error) {
        console.error("Error loading file:", error);
        showToast({ message: "Error loading file.", intent: "danger" });
    }
  };

  const handleSaveSession = () => {
      const sessionData = { filename, params, timestamp: new Date().toISOString(), pixelScale };
      const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(sessionData, null, 2));
      const downloadAnchorNode = document.createElement('a');
      downloadAnchorNode.setAttribute("href", dataStr);
      downloadAnchorNode.setAttribute("download", `session_${filename.split('.')[0]}.json`);
      document.body.appendChild(downloadAnchorNode);
      downloadAnchorNode.click();
      downloadAnchorNode.remove();
      showToast({ message: "Session saved.", intent: "success", icon: "floppy-disk", timeout: 2000 });
  };

  // PIPELINE HANDLERS
  const handleAutoTune = async () => {
      if (!imageSrc) return;
      setIsAutoTuning(true);
      try {
          const response = await fetch('http://localhost:8000/optimize_geometry', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ cx: params.cx, cy: params.cy, pa: params.pa, incl: params.incl, rout: params.rout, fit_rmin: params.fit_rmin, fit_rmax: params.fit_rmax })
          });
          if (!response.ok) throw new Error("Optimization failed");
          const data = await response.json();
          setParams(prev => ({ ...prev, incl: data.optimized_incl, pa: data.optimized_pa }));
          showToast({ message: `Optimized: Incl ${data.optimized_incl.toFixed(1)}°, PA ${data.optimized_pa.toFixed(1)}°`, intent: "success", icon: "tick-circle", timeout: 3000 });
          handleRunPipeline(true, { incl: data.optimized_incl, pa: data.optimized_pa });
      } catch (e) {
          console.error(e);
          showToast({ message: "Optimization Failed", intent: "danger" });
      } finally {
          setIsAutoTuning(false);
      }
  };

  const handleRunPipeline = async (isAuto = false, overrideParams = null) => {
    if (!imageSrc) {
        showToast({ message: "Load an image first.", intent: "warning", timeout: 2000 });
        return;
    }
    if (!isAuto) setIsPipelineLoading(true);
    const activeParams = overrideParams ? { ...params, ...overrideParams } : params;
    try {
        const response = await fetch('http://localhost:8000/run_pipeline', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filepath: "", cx: activeParams.cx, cy: activeParams.cy, pa: activeParams.pa, incl: activeParams.incl, rout: activeParams.rout, contrast: 2.0, fit_rmin: activeParams.fit_rmin, fit_rmax: activeParams.fit_rmax })
        });
        if (!response.ok) throw new Error("Pipeline error");
        const data = await response.json();
        if (data.images) {
            setResults(data.images);
            setProfileData(data.profile);
            setGeometry(data.geometry);
            setFitStats(data.fit); 
            if (!isAuto) showToast({ message: "Pipeline Finished", intent: "success", icon:"tick", timeout: 2000 });
            setLayout(currentLayout => {
                const leaves = getLeaves(currentLayout);
                if (!leaves.includes(WINDOWS.ANALYSIS)) {
                    return { direction: 'column', first: currentLayout, second: WINDOWS.ANALYSIS, splitPercentage: 60 };
                }
                return currentLayout;
            });
        }
    } catch (error) {
        console.error("Pipeline error:", error);
        showToast({ message: "Pipeline Error", intent: "danger" });
    } finally {
        setIsPipelineLoading(false);
    }
  };

  const handleRangeUpdate = useCallback((newMin, newMax) => {
      setParams(prev => ({ ...prev, fit_rmin: newMin, fit_rmax: newMax }));
      handleRunPipeline(true, { fit_rmin: newMin, fit_rmax: newMax });
  }, [imageSrc, params]); 

  // MOSAIC RENDERER
  const renderTile = useCallback((id, path) => {
    const windowProps = { title: id, path: path, toolbarControls: [<WindowControls key="controls" path={path} />], draggable: true, renderPreview: () => <div className="mosaic-preview" /> };
    if (id === WINDOWS.CONTROLS) {
        return (
            <MosaicWindow {...windowProps}>
                <div className="config-panel" style={{height:'100%', padding:15, overflowY:'auto'}}>
                    <div className="compact-label">Active Data</div>
                    <div className="data-box">
                        <Icon icon="document" size={12} color="var(--disco-accent)"/>
                        <div className="data-box-text" title={filename}>{filename}</div>
                    </div>
                    <div className="compact-label">Geometry Fit</div>
                    <ControlRow label="Inclination" value={params.incl} onChange={v=>setParams(p => ({...p, incl:v}))} min={0} max={90} unit="°" />
                    <ControlRow label="Pos Angle" value={params.pa} onChange={v=>setParams(p => ({...p, pa:v}))} min={0} max={180} unit="°" />
                    <ControlRow label="Radius Out" value={params.rout} onChange={v=>setParams(p => ({...p, rout:v}))} min={0.1} max={10} unit='"' />
                    <div style={{marginTop: 10, display:'grid', gridTemplateColumns:'1fr 1fr', gap:10, marginBottom:15}}>
                        <div> <div className="compact-label">Center X</div> <SmartNumericInput fill value={params.cx} onValueChange={v=>setParams(p => ({...p, cx:v}))} buttonPosition="none" small/> </div>
                        <div> <div className="compact-label">Center Y</div> <SmartNumericInput fill value={params.cy} onValueChange={v=>setParams(p => ({...p, cy:v}))} buttonPosition="none" small/> </div>
                    </div>
                    <div style={{flex:1}} />
                    <Button className="btn-yellow" fill text={isPipelineLoading ? "Processing..." : "RUN PIPELINE"} icon={isPipelineLoading ? <Spinner size={16} className="bp5-icon-standard"/> : "play"} disabled={isPipelineLoading} onClick={() => handleRunPipeline(false)} style={{height:30}}/>
                </div>
            </MosaicWindow>
        );
    }
    if (id === WINDOWS.VIEWER) {
        return ( <MosaicWindow {...windowProps}> <div style={{background:'var(--disco-bg-app)', width:'100%', height:'100%', display:'flex', alignItems:'center', justifyContent:'center'}}> <InteractiveViewer imageSrc={imageSrc} params={params} setParams={setParams} activeTool={activeTool} imgDimensions={imgDimensions} pixelScale={pixelScale} /> </div> </MosaicWindow> );
    }
    if (id === WINDOWS.CATALOG) {
        return (
            <MosaicWindow {...windowProps} title="File Header (Metadata)">
                 <div className="custom-scroll" style={{ height: '100%', display:'flex', flexDirection:'column', background:'var(--disco-bg-panel)' }}>
                    <div style={{padding:'6px 10px', borderBottom:'1px solid var(--disco-border)', background:'var(--disco-header)', display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                        <div style={{fontSize:11, color:'var(--disco-text-muted)', fontWeight:600}}> <Icon icon="th" size={12} style={{marginRight:5}}/> Keywords: <span style={{color:'var(--disco-text)'}}>{headerInfo.length}</span> </div>
                        <Button className="btn-yellow" small text={isSimbadLoading ? "Querying..." : "SIMBAD"} icon={isSimbadLoading ? <Spinner size={12} /> : "globe-network"} disabled={isSimbadLoading} onClick={handleRunSimbad} style={{ minHeight: 20, fontSize: 10, padding: '0 8px' }} />
                    </div>
                    <div style={{flex:1, overflow:'auto', padding:0}}>
                        <HTMLTable className="bp5-html-table-striped bp5-interactive" style={{width:'100%', tableLayout:'fixed'}}>
                            <colgroup><col style={{width:'25%'}}/><col style={{width:'35%'}}/><col style={{width:'40%'}}/></colgroup>
                            <thead><tr><th>Key</th><th>Value</th><th>Comment</th></tr></thead>
                            <tbody>
                                {headerInfo.length === 0 ? <tr><td colSpan={3} style={{textAlign:'center', padding:40, color:'var(--disco-text-muted)'}}>No file loaded</td></tr> : headerInfo.map((row, i) => (<tr key={i}><td style={{fontWeight:'700'}}>{row.key}</td><td style={{overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}} title={row.value}>{row.value}</td><td style={{color:'var(--disco-text-muted)', fontStyle:'italic', fontSize:'10px'}}>{row.comment}</td></tr>))}
                            </tbody>
                        </HTMLTable>
                    </div>
                </div>
            </MosaicWindow>
        );
    }
    if (id === WINDOWS.ANALYSIS) { 
        return ( 
            <MosaicWindow {...windowProps} title="Scientific Analysis"> 
                <AnalysisDashboard 
                    results={results} 
                    profileData={profileData} 
                    fitStats={fitStats} 
                    geometry={geometry} 
                    onOpenMatplotlib={handleOpenMatplotlibModal} 
                    onAutoTune={handleAutoTune}
                    onUpdateRange={handleRangeUpdate} 
                    activeTool={activeTool}
                    currentFitRange={[params.fit_rmin, params.fit_rmax]}
                    isAutoTuning={isAutoTuning}
                /> 
            </MosaicWindow> 
        ); 
    }
    return <MosaicWindow {...windowProps}><div/></MosaicWindow>;
  }, [headerInfo, filename, params, imageSrc, activeTool, results, isSimbadLoading, isPipelineLoading, fitStats, isAutoTuning]);

  return (
    <div className={darkMode ? "bp5-dark" : ""} style={{height:'100vh', display:'flex', flexDirection:'column', background:'var(--disco-bg-app)'}}>
        <input type="file" ref={fileInputRef} style={{display:'none'}} onChange={handleFileUpload} accept=".fits,.fit,.json"/>
        
        {/* HEADER & TOOLBAR */}
        <div style={{ height: '30px', background: 'var(--disco-header)', display:'flex', alignItems:'center', padding:'0 8px', borderBottom:'1px solid var(--disco-border)' }}>
            <div style={{ fontWeight:'800', marginRight: 15, color: 'var(--disco-accent)', fontSize:12, letterSpacing:1 }}>DISCO<span style={{color:'var(--disco-text)', fontWeight:400}}></span></div>
            <Popover content={ViewMenu} position={Position.BOTTOM_LEFT} minimal><Button minimal small text="View" className="header-btn" style={{ fontSize:11 }}/></Popover>
            <div style={{flex:1}} />
            <Popover content={SettingsMenu} position={Position.BOTTOM_RIGHT} minimal><Button minimal small text="Settings" className="header-btn" style={{ fontSize: 11 }} /></Popover>
            <Button minimal small text="Help" className="header-btn" style={{ fontSize: 11 }} />
        </div>

        <div style={{ height: '32px', background: 'var(--disco-header)', display:'flex', alignItems:'center', padding:'0 4px', borderBottom:'1px solid var(--disco-border)' }}>
            <ButtonGroup minimal>
                <Button icon="folder-close" onClick={() => fileInputRef.current.click()} title="Open File"/>
                <Button icon="floppy-disk" onClick={handleSaveSession} title="Save Session"/>
                <Button icon="fullscreen" onClick={toggleFullscreen} title="Fullscreen"/>
                <Divider />
                <Button icon="cross" intent="danger" onClick={handleExit} title="Exit"/>
            </ButtonGroup>
            <Divider style={{height:16, borderColor:'var(--disco-border)', margin:'0 8px'}}/>
            <ButtonGroup minimal>
                <Button icon="selection" active={activeTool === 'select'} intent={activeTool === 'select' ? "primary" : "none"} onClick={() => setActiveTool('select')} title="Edit Geometry"/>
                <Button icon="hand" active={activeTool === 'pan'} intent={activeTool === 'pan' ? "primary" : "none"} onClick={() => setActiveTool('pan')} title="Pan Image"/>
                <Button icon="locate" active={activeTool === 'inspector'} intent={activeTool === 'inspector' ? "primary" : "none"} onClick={() => setActiveTool('inspector')} title="Spectral Inspector / Range Selector"/>
            </ButtonGroup>
        </div>

        <div className="mosaic-container" style={{flex: 1, overflow:'hidden', position: 'relative', background:'var(--disco-bg-app)'}}>
            <Mosaic renderTile={renderTile} value={layout} onChange={setLayout} className={darkMode ? "mosaic-blueprint-theme bp5-dark" : "mosaic-blueprint-theme"} resize={{ minimumPaneSizePercentage: 5 }}/>
        </div>

        {/* DIALOGS */}
        <Dialog isOpen={isMatplotlibModalOpen} onClose={() => setIsMatplotlibModalOpen(false)} title="Scientific Plotter" icon="chart" style={{width:'90vw', height:'90vh', maxWidth:'1400px'}} className="bp5-dark">
            <div className={Classes.DIALOG_BODY} style={{flex:1, height:'100%', padding:0, margin:0, background:'var(--disco-bg-panel)'}}> 
               {isMatplotlibModalOpen && <MatplotlibWidget defaultType={matplotlibInitialType} />}
            </div>
        </Dialog>

        <Dialog className={darkMode ? "bp5-dark" : ""} isOpen={isSimbadModalOpen} onClose={() => setIsSimbadModalOpen(false)} title="Simbad Query Results" icon="globe-network" style={{width:'1000px', maxWidth:'90vw', height:'auto', maxHeight:'80vh', background: 'var(--disco-bg-panel)'}} >
            <div className={Classes.DIALOG_BODY} style={{padding:0, margin:0, height:'100%', background:'var(--disco-bg-panel)'}}>
                {simbadResults && (
                    <div className="custom-scroll" style={{maxHeight:'60vh', overflow:'auto'}}>
                        <HTMLTable className="bp5-html-table-striped bp5-interactive bp5-compact" style={{width:'100%'}}>
                            <thead><tr>{Object.keys(simbadResults[0] || {}).map(key => (<th key={key} style={{position:'sticky', top:0, background:'var(--disco-header)', zIndex: 2}}>{key.toUpperCase()}</th>))}</tr></thead>
                            <tbody>{simbadResults.map((row, i) => (<tr key={i}>{Object.values(row).map((val, j) => (<td key={j}>{val}</td>))}</tr>))}</tbody>
                        </HTMLTable>
                    </div>
                )}
            </div>
            <div className={Classes.DIALOG_FOOTER} style={{background:'var(--disco-header)', borderTop:'1px solid var(--disco-border)'}}>
                <div className={Classes.DIALOG_FOOTER_ACTIONS}> <Button onClick={() => setIsSimbadModalOpen(false)}>Close</Button> </div>
            </div>
        </Dialog>
    </div>
  );
}

export default App;