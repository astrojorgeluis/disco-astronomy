import React, { useCallback, useEffect, useRef } from 'react';
import MenuBar from './app/MenuBar';
import Toolbar from './app/Toolbar';
import SingleLayout from './app/layout/SingleLayout';
import useSessionStore from './state/session';
import useVizStore from './state/viz';
import { api } from './api/client';
import { invalidateThemeColors } from './theme/colors';

function ErrorBoundary({ children }) {
  const [err, setErr] = React.useState(null);
  if (err) {
    return (
      <div style={{ padding: 24 }}>
        <h3>Something went wrong</h3>
        <pre style={{ whiteSpace: 'pre-wrap' }}>{String(err?.message || err)}</pre>
        <button type="button" onClick={() => { setErr(null); window.location.reload(); }}>Reload</button>
      </div>
    );
  }
  return <ErrorCatch onError={setErr}>{children}</ErrorCatch>;
}

class ErrorCatch extends React.Component {
  componentDidCatch(error) {
    this.props.onError(error);
  }
  render() {
    return this.props.children;
  }
}

export default function App() {
  const fileRef = useRef(null);
  const sessionRef = useRef(null);
  const darkMode = useSessionStore((s) => s.darkMode);
  const params = useSessionStore((s) => s.params);
  const activeImageId = useSessionStore((s) => s.activeImageId);
  const loading = useSessionStore((s) => s.loading);
  const applyUpload = useSessionStore((s) => s.applyUpload);
  const applyPipeline = useSessionStore((s) => s.applyPipeline);
  const setLoading = useSessionStore((s) => s.setLoading);
  const setParams = useSessionStore((s) => s.setParams);
  const resetWorkspace = useSessionStore((s) => s.resetWorkspace);
  const exportSession = useSessionStore((s) => s.exportSession);
  const applyStats = useVizStore((s) => s.applyStats);

  useEffect(() => {
    document.body.classList.toggle('bp6-dark', darkMode);
    invalidateThemeColors();
  }, [darkMode]);

  const handleOpenFile = () => fileRef.current?.click();

  const onFileChange = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setLoading('image', true);
    try {
      const payload = await api.upload(file);
      const header = await api.getHeader(payload.id);
      applyUpload(payload, header);
      try {
        const meta = await api.rasterMeta('data', payload.id);
        useSessionStore.setState({ rasterMeta: meta });
        if (meta?.stats) {
          useVizStore.getState().setViz({ stretch: 'linear' });
          applyStats(meta.stats, 'minmax');
        }
      } catch {
        /* ignore */
      }
    } catch (err) {
      window.alert(String(err?.detail || err.message || err));
    } finally {
      setLoading('image', false);
    }
  };

  const handleRun = useCallback(async () => {
    if (!activeImageId) {
      window.alert('Open a FITS file first');
      return;
    }
    setLoading('pipeline', true);
    try {
      const data = await api.runPipeline({
        image_id: activeImageId,
        cx: params.cx,
        cy: params.cy,
        pa: params.pa,
        incl: params.incl,
        rout: params.rout,
        fit_rmin: params.fit_rmin,
        fit_rmax: params.fit_rmax,
      });
      applyPipeline(data);
    } catch (err) {
      window.alert(String(err?.detail || err.message || err));
    } finally {
      setLoading('pipeline', false);
    }
  }, [activeImageId, params, applyPipeline, setLoading]);

  const handleOptimize = useCallback(async () => {
    if (!activeImageId) {
      window.alert('Open a FITS file first');
      return;
    }
    setLoading('autoTune', true);
    try {
      const data = await api.optimizeGeometry({
        image_id: activeImageId,
        cx: params.cx,
        cy: params.cy,
        pa: params.pa,
        incl: params.incl,
        rout: params.rout,
        fit_rmin: params.fit_rmin,
        fit_rmax: params.fit_rmax,
      });
      const next = {
        incl: data.optimized_incl,
        pa: data.optimized_pa,
        ...(Number.isFinite(data.optimized_cx) ? { cx: data.optimized_cx } : {}),
        ...(Number.isFinite(data.optimized_cy) ? { cy: data.optimized_cy } : {}),
      };
      setParams(next);
      setLoading('autoTune', false);
      setLoading('pipeline', true);
      const run = await api.runPipeline({
        image_id: activeImageId,
        cx: next.cx ?? params.cx,
        cy: next.cy ?? params.cy,
        pa: next.pa,
        incl: next.incl,
        rout: params.rout,
        fit_rmin: params.fit_rmin,
        fit_rmax: params.fit_rmax,
      });
      applyPipeline(run);
    } catch (err) {
      window.alert(String(err?.detail || err.message || err));
    } finally {
      setLoading('autoTune', false);
      setLoading('pipeline', false);
    }
  }, [activeImageId, params, setParams, setLoading, applyPipeline]);

  const handleSaveSession = () => {
    const blob = new Blob([JSON.stringify(exportSession(), null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'disco-session.json';
    a.click();
  };

  const handleRestoreSession = () => sessionRef.current?.click();

  const onSessionFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    try {
      const text = await file.text();
      const state = JSON.parse(text);
      await api.restoreSession(state);
      window.location.reload();
    } catch (err) {
      window.alert(String(err?.detail || err.message || err));
    }
  };

  const handleReset = async () => {
    await resetWorkspace(false);
  };

  return (
    <ErrorBoundary>
      <div className={`disco-shell${darkMode ? ' bp6-dark' : ''}`}>
        <input ref={fileRef} type="file" accept=".fits,.fit,.fts,.FITS" style={{ display: 'none' }} onChange={onFileChange} />
        <input ref={sessionRef} type="file" accept=".json" style={{ display: 'none' }} onChange={onSessionFile} />
        <MenuBar
          onOpenFile={handleOpenFile}
          onSaveSession={handleSaveSession}
          onRestoreSession={handleRestoreSession}
          onReset={handleReset}
        />
        <Toolbar
          onOptimize={handleOptimize}
          running={loading.pipeline || loading.autoTune}
        />
        <div style={{ flex: 1, minHeight: 0, display: 'flex', padding: 4, gap: 0 }}>
          <SingleLayout
            onRun={handleRun}
            running={loading.pipeline || loading.autoTune}
          />
        </div>
      </div>
    </ErrorBoundary>
  );
}
