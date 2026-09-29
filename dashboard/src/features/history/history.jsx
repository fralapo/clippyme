// ClippyMe — HistoryView, wired to the real backend (history list/restore/delete).
import { Icon, Btn, Badge, Panel } from '../../components/primitives';
import { Hero } from '../../components/headers';
import { relTime } from '../../lib/relTime';

export function HistoryView({ history, availableIds, onOpen, onDelete, onClear }) {
  if (!history.length) {
    return (
      <div className="container narrow fade-in">
        <Hero eyebrow="History" line1="Nothing here yet." sub="Every job you run lands here, ready to reopen, re-export, or publish again." />
        <div className="empty">
          <div className="ei"><Icon n="clock" /></div>
          <h3>No jobs yet</h3>
          <p>Head to Create, paste a link, and your finished clips will land here.</p>
        </div>
      </div>
    );
  }
  return (
    <div className="container narrow fade-in">
      <div className="results-head" style={{ marginBottom: 18 }}>
        <h2>History</h2>
        <Badge tone="out">{history.length} jobs</Badge>
        <div className="rh-right">
          <Btn variant="ghost" size="sm" icon="trash-2" onClick={onClear}>Clear all</Btn>
        </div>
      </div>
      <Panel pad={false} className="hlist">
        {history.map((h) => {
          // `availableIds` is the set of jobs whose files still exist on disk
          // (null = backend not reached yet → assume available, don't disable).
          // An entry whose files were wiped by a rebuild is shown muted + flagged
          // "files removed" instead of looking clickable and dead-ending.
          const onDisk = !availableIds || availableIds.has(h.jobId);
          const ok = h.status === 'complete' && onDisk;
          const removed = !!availableIds && !availableIds.has(h.jobId);
          return (
            <div className="hrow" key={h.jobId}
              role={ok ? 'button' : undefined} tabIndex={ok ? 0 : undefined}
              aria-label={ok ? `Open job ${h.title || h.source || h.jobId}` : undefined}
              onClick={() => ok && onOpen(h)}
              onKeyDown={(e) => { if (ok && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onOpen(h); } }}
              style={{ cursor: ok ? 'pointer' : 'default', opacity: removed ? 0.55 : 1 }}>
              <div className="hthumb" style={{ background: removed ? 'var(--bg-4)' : 'var(--grad-viral)' }}>{h.clipCount ?? 0}</div>
              <div style={{ minWidth: 0 }}>
                <div className="ht" title={h.title || h.source || h.jobId}
                  style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{h.title || h.source || h.jobId}</div>
                <div className="hm">
                  <Icon n={h.sourceType === 'url' ? 'globe' : 'file-video'} style={{ width: 11, height: 11, verticalAlign: '-1px', marginRight: 5 }} />
                  {removed ? 'Files removed (rebuild/cleanup) · delete to dismiss'
                    : `${h.clipCount || 0} clips${h.cost != null ? ` · $${Number(h.cost).toFixed(2)}` : ''} · ${relTime(h.timestamp)}`}
                </div>
              </div>
              <div className="hr">
                {!removed && h.publishedCount > 0 && (
                  <Badge tone="teal" icon="send">{h.publishedCount} published</Badge>
                )}
                {removed ? <Badge tone="out" icon="triangle-alert">unavailable</Badge>
                  : h.status === 'complete' ? <Badge tone="teal" icon="check">complete</Badge>
                    : h.status === 'error' ? <Badge tone="danger" icon="triangle-alert">error</Badge>
                      : <Badge tone="amber" icon="clock">{h.status || 'pending'}</Badge>}
                <button type="button" className="mini" title="Delete" aria-label="Delete job" onClick={(e) => { e.stopPropagation(); onDelete(h.jobId); }}><Icon n="trash-2" /></button>
                {ok && <Icon n="chevron-right" style={{ width: 18, height: 18, color: 'var(--fg-4)' }} />}
              </div>
            </div>
          );
        })}
      </Panel>
    </div>
  );
}
