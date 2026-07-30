import React, { useState } from 'react';
import { WIDGET_META, useDockStore } from '../../state/docks';

/**
 * Dock that hosts movable analysis tabs.
 * Drag a tab onto another MovableDock (or its tab bar) to relocate it.
 */
export default function MovableDock({
  slotId,
  children,
  noScroll = false,
  emptyHint = 'Drop a tab here',
}) {
  const tabs = useDockStore((s) => s.slots[slotId] || []);
  const activeId = useDockStore((s) => s.active[slotId]);
  const setActive = useDockStore((s) => s.setActive);
  const moveTab = useDockStore((s) => s.moveTab);
  const [dragOver, setDragOver] = useState(false);

  const onDragStart = (e, tabId) => {
    e.dataTransfer.setData('application/x-disco-tab', JSON.stringify({ tabId, fromSlot: slotId }));
    e.dataTransfer.effectAllowed = 'move';
  };

  const onDragOver = (e) => {
    if (![...e.dataTransfer.types].includes('application/x-disco-tab')) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setDragOver(true);
  };

  const onDragLeave = (e) => {
    if (!e.currentTarget.contains(e.relatedTarget)) setDragOver(false);
  };

  const onDrop = (e, toIndex = null) => {
    e.preventDefault();
    setDragOver(false);
    let payload;
    try {
      payload = JSON.parse(e.dataTransfer.getData('application/x-disco-tab') || '{}');
    } catch {
      return;
    }
    if (!payload?.tabId) return;
    moveTab(payload.tabId, payload.fromSlot, slotId, toIndex);
  };

  return (
    <div
      className={`disco-dock${dragOver ? ' disco-dock-drop' : ''}`}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={(e) => onDrop(e)}
    >
      <div className="disco-dock-tabs" onDragOver={onDragOver}>
        {tabs.map((id, i) => {
          const meta = WIDGET_META[id];
          if (!meta) return null;
          return (
            <button
              key={id}
              type="button"
              className={`disco-dock-tab${activeId === id ? ' active' : ''}`}
              draggable
              title="Drag to move this tab to another panel"
              onDragStart={(e) => onDragStart(e, id)}
              onDragOver={(e) => {
                onDragOver(e);
              }}
              onDrop={(e) => {
                e.stopPropagation();
                onDrop(e, i);
              }}
              onClick={() => setActive(slotId, id)}
            >
              {meta.label}
            </button>
          );
        })}
        {!tabs.length && (
          <span className="disco-dock-empty-tab">{emptyHint}</span>
        )}
      </div>
      <div
        className={`disco-dock-body${noScroll ? '' : ' custom-scroll'}`}
        style={noScroll ? { overflow: 'hidden' } : undefined}
      >
        {tabs.length ? children(activeId) : (
          <div style={{ padding: 16, color: 'var(--disco-text-muted)', fontSize: 11 }}>
            {emptyHint}
          </div>
        )}
      </div>
    </div>
  );
}
