import React, { useState, useEffect } from 'react';
import { 
    Button, HTMLSelect, Slider, Spinner, 
    InputGroup, Switch, Divider, Classes, 
    NumericInput
} from "@blueprintjs/core";

// SMART INPUT COMPONENT
const SmartInput = ({ value, onValueChange, ...props }) => {
    const [str, setStr] = useState(String(value || ""));
    useEffect(() => {
        const num = parseFloat(str);
        if (value !== undefined && (Math.abs(num - value) > 1e-6 || isNaN(num))) {
            setStr(String(value));
        }
    }, [value]);
    const handleChange = (valNum, valStr) => { setStr(valStr); onValueChange(valNum); };
    return <NumericInput {...props} value={str} onValueChange={handleChange} buttonPosition="none"/>;
};

const MatplotlibWidget = ({ defaultType = 'data' }) => {
  const [image, setImage] = useState(null);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  
  const [options, setOptions] = useState({
    type: defaultType,
    cmap: 'magma',
    stretch: 'asinh',
    vmin: null, 
    vmax: null, 
    show_axes: true,
    show_grid: false,
    show_colorbar: true,
    show_beam: true,
    contours: false,
    contour_levels: 5,
    title: "",
    dpi: 150
  });

  // INITIAL LOAD
  useEffect(() => { fetchPlot(); }, [options.type]); 

  // AUTO-UPDATE LOGIC
  useEffect(() => {
      const handler = setTimeout(() => fetchPlot(), 200); 
      return () => clearTimeout(handler);
  }, [
      options.cmap, options.stretch, 
      options.vmin, options.vmax, 
      options.show_axes, options.show_grid, options.show_colorbar, options.show_beam,
      options.contours, options.contour_levels,
      options.dpi
  ]);

  const fetchPlot = async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
        const response = await fetch('http://localhost:8000/render_plot', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(options)
        });
        
        if (response.ok) {
            const data = await response.json();
            setImage(data.image);
            
            // SYNC AUTO-SCALING VALUES
            if (options.vmin === null || options.vmax === null) {
                setOptions(prev => ({
                    ...prev,
                    vmin: options.vmin === null ? data.stats.vmin_used : prev.vmin,
                    vmax: options.vmax === null ? data.stats.vmax_used : prev.vmax
                }));
            }
        } else {
            const err = await response.json();
            setImage(null);
            setErrorMsg(err.detail || "Error loading plot");
        }
    } catch (e) { 
        console.error(e); 
        setImage(null);
        setErrorMsg("Network or Server Error");
    }
    setLoading(false);
  };

  const updateOption = (key, value) => { setOptions(prev => ({ ...prev, [key]: value })); };
  const handleReset = () => { setOptions(prev => ({ ...prev, vmin: null, vmax: null })); };
  
  const isProfile = options.type === 'profile';

  return (
    <div style={{display:'flex', height:'100%', background:'var(--disco-bg-panel)'}}>
        
        {/* CONTROL SIDEBAR */}
        <div className="custom-scroll" style={{ width: 300, padding: 15, borderRight:'1px solid var(--disco-border)', overflowY:'auto', display: 'flex', flexDirection: 'column', gap: 15 }}>
            
            {/* DATA SOURCE SELECTION */}
            <div style={{background:'var(--disco-bg-app)', padding:10, borderRadius:4, border:'1px solid var(--disco-border)'}}>
                <div className="compact-label" style={{color:'var(--disco-accent)'}}>DATA SOURCE</div>
                <HTMLSelect 
                    fill large 
                    value={options.type} 
                    onChange={e => {
                        setOptions(prev => ({ 
                            ...prev, 
                            type: e.target.value, 
                            vmin: null, 
                            vmax: null 
                        }));
                    }} 
                    options={[
                        { label: 'Original Data', value: 'data' },
                        { label: 'Deprojected', value: 'deproj' },
                        { label: 'Polar Map', value: 'polar' },
                        { label: 'Radial Profile (1D)', value: 'profile' },
                        { label: 'Model', value: 'model' },
                        { label: 'Residuals', value: 'residuals' }
                    ]} 
                />
            </div>

            {/* COLOR OPTIONS */}
            {!isProfile && (
                <>
                    <div>
                        <div className="compact-label">Colormap</div>
                        <HTMLSelect 
                            fill 
                            value={options.cmap} 
                            onChange={e => updateOption('cmap', e.target.value)} 
                            options={['magma', 'inferno', 'viridis', 'gray', 'seismic', 'jet', 'twilight']} 
                        />
                    </div>
                    
                    <div>
                        <div className="compact-label">Stretch</div>
                        <HTMLSelect 
                            fill
                            value={options.stretch} 
                            onChange={e => updateOption('stretch', e.target.value)} 
                            options={['asinh', 'log', 'linear', 'sqrt']} 
                        />
                    </div>
                </>
            )}

            {/* INTENSITY LIMITS */}
            <div style={{background:'var(--disco-bg-app)', padding:8, borderRadius:4, border:'1px solid var(--disco-border)'}}>
                <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:5}}>
                    <div className="compact-label">Intensity Limits {isProfile ? '(Log Y)' : ''}</div>
                    <Button small minimal icon="undo" text="Auto" onClick={handleReset} />
                </div>
                <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:10}}>
                    <SmartInput fill value={options.vmin} onValueChange={v => updateOption('vmin', v)} />
                    <SmartInput fill value={options.vmax} onValueChange={v => updateOption('vmax', v)} />
                </div>
            </div>

            <Divider />

            {/* OVERLAYS */}
            <div className="compact-label">Overlays</div>
            <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:8}}>
                <Switch label="Axes" checked={options.show_axes} onChange={e => updateOption('show_axes', e.target.checked)} />
                <Switch label="Grid" checked={options.show_grid} onChange={e => updateOption('show_grid', e.target.checked)} />
                {!isProfile && <Switch label="Colorbar" checked={options.show_colorbar} onChange={e => updateOption('show_colorbar', e.target.checked)} />}
                {!isProfile && <Switch label="Beam" checked={options.show_beam} onChange={e => updateOption('show_beam', e.target.checked)} disabled={options.type==='polar'}/>}
            </div>

            {/* CONTOURS */}
            {!isProfile && (
                <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginTop:5}}>
                    <Switch label="Contours" checked={options.contours} onChange={e => updateOption('contours', e.target.checked)} style={{marginBottom:0}}/>
                    {options.contours && (
                        <div style={{display:'flex', alignItems:'center', gap:5}}>
                            <span style={{fontSize:10, color:'var(--disco-text-muted)'}}>Lvls:</span>
                            <NumericInput style={{width: 50}} buttonPosition="none" min={1} max={50} value={options.contour_levels} onValueChange={(v) => updateOption('contour_levels', v)} small/>
                        </div>
                    )}
                </div>
            )}

            <Divider />

            {/* EXPORT */}
            <div className="compact-label">Export</div>
            <InputGroup placeholder="Plot Title..." value={options.title} onChange={e => updateOption('title', e.target.value)} />
            
            <div style={{display:'flex', alignItems:'center', gap:10, marginTop:5}}>
                <div style={{flex:1}}>
                    <span style={{fontSize:10, opacity:0.7, color:'var(--disco-text-muted)'}}>DPI:</span>
                    <NumericInput value={options.dpi} onValueChange={v => updateOption('dpi', v)} min={72} max={600} fill buttonPosition="none"/>
                </div>
                <Button icon="download" text="Save PNG" onClick={() => {
                        if (!image) return;
                        const link = document.createElement('a');
                        link.href = image;
                        link.download = `plot_${options.type}.png`;
                        document.body.appendChild(link);
                        link.click();
                        document.body.removeChild(link);
                    }} 
                    disabled={!image}
                />
            </div>
            
            <div style={{marginTop:'auto', paddingTop:10}}>
                <Button intent="primary" icon="refresh" text="Force Update" fill loading={loading} onClick={fetchPlot} />
            </div>
        </div>

        {/* VISUALIZATION AREA */}
        <div style={{flex:1, display:'flex', alignItems:'center', justifyContent:'center', background:'var(--disco-chart-bg)', overflow: 'hidden', position:'relative', padding:20}}>
            {loading && <Spinner style={{position:'absolute'}} size={60} intent="primary"/>}
            
            {errorMsg ? (
                <div style={{color:'var(--disco-danger)', textAlign:'center'}}>
                    <div style={{fontSize:16, fontWeight:'bold', marginBottom:5}}>⚠️ Plot Error</div>
                    <div>{errorMsg}</div>
                </div>
            ) : image ? (
                <img src={image} style={{maxWidth:'100%', maxHeight:'100%', objectFit:'contain', boxShadow:'0 0 20px rgba(0,0,0,0.1)', background:'white'}} />
            ) : (
                <div style={{color:'var(--disco-text-muted)'}}>Ready to render.</div>
            )}
        </div>
    </div>
  );
};

export default MatplotlibWidget;