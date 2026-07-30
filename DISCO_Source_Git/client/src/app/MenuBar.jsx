import React, { useEffect, useState } from 'react';
import {
  Button, Menu, MenuItem, MenuDivider, Popover, Position, Switch,
} from '@blueprintjs/core';
import useSessionStore from '../state/session';
import { invalidateThemeColors } from '../theme/colors';
import { api } from '../api/client';

export default function MenuBar({ onOpenFile, onSaveSession, onRestoreSession, onReset }) {
  const darkMode = useSessionStore((s) => s.darkMode);
  const setDarkMode = useSessionStore((s) => s.setDarkMode);
  const connected = useSessionStore((s) => s.connected);
  const setConnected = useSessionStore((s) => s.setConnected);
  const setViewMode = useSessionStore((s) => s.setViewMode);
  const resetLayout = useSessionStore((s) => s.resetLayout);
  const loading = useSessionStore((s) => s.loading);
  const [helpOpen, setHelpOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const ping = async () => {
      try {
        await api.listImages();
        if (!cancelled) setConnected(true);
      } catch {
        if (!cancelled) setConnected(false);
      }
    };
    ping();
    const id = setInterval(ping, 15000);
    return () => { cancelled = true; clearInterval(id); };
  }, [setConnected]);

  const toggleTheme = (v) => {
    setDarkMode(v);
    document.body.classList.toggle('bp6-dark', v);
    invalidateThemeColors();
  };

  let status = 'Idle';
  let busy = false;
  if (!connected) status = 'Offline';
  else if (loading.image) { status = 'Loading image…'; busy = true; }
  else if (loading.pipeline) { status = 'Running pipeline…'; busy = true; }
  else if (loading.autoTune) { status = 'Optimizing…'; busy = true; }
  else if (loading.simbad) { status = 'Querying catalog…'; busy = true; }

  const fileMenu = (
    <Menu>
      <MenuItem icon="document-open" text="Open FITS…" onClick={onOpenFile} />
      <MenuItem icon="floppy-disk" text="Save Session…" onClick={onSaveSession} />
      <MenuItem icon="import" text="Restore Session…" onClick={onRestoreSession} />
      <MenuDivider />
      <MenuItem icon="trash" text="Reset Session" intent="danger" onClick={onReset} />
    </Menu>
  );

  const viewMenu = (
    <Menu>
      <MenuItem text="Individual Mode" onClick={() => setViewMode('single')} />
      <MenuItem text="Mosaic Mode" onClick={() => setViewMode('mosaic')} />
      <MenuDivider />
      <MenuItem icon="zoom-to-fit" text="Reset window sizes" onClick={resetLayout} />
      <MenuDivider />
      <MenuItem
        text={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            Dark theme
            <Switch checked={darkMode} onChange={(e) => toggleTheme(e.target.checked)} style={{ margin: 0 }} />
          </div>
        }
      />
    </Menu>
  );

  const helpMenu = (
    <Menu>
      <MenuItem text="About DISCO" onClick={() => setHelpOpen(true)} />
    </Menu>
  );

  return (
    <div className="disco-menubar">
      <strong style={{ marginRight: 8, color: 'var(--disco-accent)' }}>DISCO</strong>
      <Popover content={fileMenu} position={Position.BOTTOM_LEFT} minimal>
        <Button minimal small text="File" />
      </Popover>
      <Popover content={viewMenu} position={Position.BOTTOM_LEFT} minimal>
        <Button minimal small text="View" />
      </Popover>
      <Popover content={helpMenu} position={Position.BOTTOM_LEFT} minimal>
        <Button minimal small text="Help" />
      </Popover>
      <div style={{ flex: 1 }} />
      <span style={{ fontSize: 11, color: 'var(--disco-text-muted)', marginRight: 6 }}>
        {status}
      </span>
      <div
        className={`disco-conn-dot${connected ? '' : ' offline'}${busy ? ' busy' : ''}`}
        title={status}
        style={busy ? { background: 'var(--disco-warning)', animation: 'pulse 1s infinite' } : undefined}
      />
      {helpOpen && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.3)', zIndex: 1000,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}
          onClick={() => setHelpOpen(false)}
        >
          <div className="disco-dock" style={{ width: 360, padding: 16 }} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ marginTop: 0 }}>DISCO</h3>
            <p style={{ color: 'var(--disco-text-muted)' }}>
              Protoplanetary-disk FITS analysis. Load a FITS, set geometry in Render Configuration, then Run.
            </p>
            <Button intent="primary" text="Close" onClick={() => setHelpOpen(false)} />
          </div>
        </div>
      )}
    </div>
  );
}
