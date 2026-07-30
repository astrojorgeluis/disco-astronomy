import React from 'react';

/** Tabbed dock container. */
export default function Dock({ tabs, activeId, onChange, children, extra = null, noScroll = false }) {
  return (
    <div className="disco-dock">
      <div className="disco-dock-tabs">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`disco-dock-tab${activeId === t.id ? ' active' : ''}`}
            onClick={() => onChange(t.id)}
          >
            {t.label}
          </button>
        ))}
        {extra && <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', paddingRight: 6 }}>{extra}</div>}
      </div>
      <div
        className={`disco-dock-body${noScroll ? '' : ' custom-scroll'}`}
        style={noScroll ? { overflow: 'hidden' } : undefined}
      >
        {children}
      </div>
    </div>
  );
}
