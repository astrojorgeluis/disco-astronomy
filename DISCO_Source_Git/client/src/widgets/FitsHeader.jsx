import React from 'react';
import { HTMLTable } from '@blueprintjs/core';
import useSessionStore from '../state/session';

export default function FitsHeader() {
  const headerInfo = useSessionStore((s) => s.headerInfo);
  const rows = (headerInfo || []).slice(0, 200);

  return (
    <div style={{ padding: 8, height: '100%', overflow: 'auto' }} className="custom-scroll">
      <div className="compact-label">FITS Header</div>
      <HTMLTable compact striped style={{ width: '100%', fontSize: 10 }}>
        <thead>
          <tr><th>Key</th><th>Value</th><th>Comment</th></tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.key}-${i}`}>
              <td className="disco-numeric">{r.key}</td>
              <td className="disco-numeric">{String(r.value)}</td>
              <td style={{ color: 'var(--disco-text-muted)' }}>{r.comment}</td>
            </tr>
          ))}
        </tbody>
      </HTMLTable>
    </div>
  );
}
