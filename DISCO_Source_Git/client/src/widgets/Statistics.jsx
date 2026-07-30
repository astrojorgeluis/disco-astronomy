import React, { useEffect, useMemo, useState } from 'react';
import { HTMLTable, Spinner } from '@blueprintjs/core';
import useRegionsStore from '../state/regions';
import useSessionStore from '../state/session';
import { api } from '../api/client';

/** Strip UI-only fields; regions are always in full-data array coords. */
function regionPayload(region) {
  if (!region || typeof region !== 'object') return null;
  const {
    id: _id,
    name: _name,
    color: _color,
    locked: _locked,
    product: _product,
    ...geom
  } = region;
  if (!geom.type) return null;
  return geom;
}

function statsKey(region) {
  if (!region) return '';
  // Stable key so we refetch when geometry changes, not on every store tick
  try {
    return `${region.id}:${region.type}:${JSON.stringify(regionPayload(region))}`;
  } catch {
    return String(region.id || '');
  }
}

export default function Statistics() {
  const selectedId = useRegionsStore((s) => s.selectedRegionId);
  const regions = useRegionsStore((s) => s.regions);
  const activeImageId = useSessionStore((s) => s.activeImageId);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [stats, setStats] = useState(null);

  const region = useMemo(
    () => regions.find((r) => r.id === selectedId) || null,
    [regions, selectedId],
  );
  const key = statsKey(region);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!region || !activeImageId) {
        setStats(null);
        setError(null);
        return;
      }
      const payload = regionPayload(region);
      if (!payload) {
        setStats(null);
        setError('Region is missing a type.');
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const res = await api.regionStats({
          image_id: activeImageId,
          region: payload,
          product: 'data',
        });
        if (cancelled) return;
        const next = res?.stats || res;
        setStats(next && typeof next === 'object' ? next : null);
        if (!next || (next.npix === 0 && next.sum === 0)) {
          // Still show zeros — but hint if completely empty
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setStats(null);
          setError(String(err?.detail || err?.message || err));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [key, activeImageId, region]);

  if (!region) {
    return (
      <div style={{ padding: 12, color: 'var(--disco-text-muted)' }}>
        Select a region (ellipse, box, annulus, …) to view its statistics.
      </div>
    );
  }

  if (!activeImageId) {
    return (
      <div style={{ padding: 12, color: 'var(--disco-text-muted)' }}>
        Load an image first.
      </div>
    );
  }

  if (loading) {
    return <div style={{ padding: 24, textAlign: 'center' }}><Spinner size={24} /></div>;
  }

  if (error) {
    return (
      <div style={{ padding: 12, color: 'var(--disco-danger)', fontSize: 11 }}>
        Could not compute statistics: {error}
      </div>
    );
  }

  const rows = stats
    ? Object.entries(stats).map(([k, v]) => [
      k,
      typeof v === 'number' ? (Number.isFinite(v) ? v.toExponential(6) : String(v)) : String(v),
    ])
    : [];

  return (
    <div style={{ padding: 8 }}>
      <div className="compact-label">Statistics: {region.name}</div>
      {rows.length ? (
        <HTMLTable compact striped style={{ width: '100%', fontSize: 11 }}>
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k}>
                <td>{k}</td>
                <td className="disco-numeric">{v}</td>
              </tr>
            ))}
          </tbody>
        </HTMLTable>
      ) : (
        <div style={{ color: 'var(--disco-text-muted)', fontSize: 11, paddingTop: 8 }}>
          No statistics returned for this region.
        </div>
      )}
    </div>
  );
}
