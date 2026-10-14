import { test, expect, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { HistoryView } from './history.jsx';

// HistoryView — title + per-job "published" badge (derived from
// history_service.scan_history's additive `title`/`publishedCount` fields).
test('history row shows the video title and a published-count badge when clips were published', () => {
  const history = [
    { jobId: 'job-1', status: 'complete', clipCount: 2, source: 'my video', title: 'my video', publishedCount: 1, cost: 0.004, timestamp: Date.now() },
    { jobId: 'job-2', status: 'complete', clipCount: 3, source: 'other video', title: 'other video', publishedCount: 0, timestamp: Date.now() },
  ];
  render(<HistoryView history={history} availableIds={null} onOpen={vi.fn()} onDelete={vi.fn()} onClear={vi.fn()} />);

  expect(screen.getByText('my video')).toBeInTheDocument();
  expect(screen.getByTitle(/Gemini API usage only/)).toHaveTextContent('Gemini $0.00');
  expect(screen.getByText('1 published')).toBeInTheDocument();
  expect(screen.getByText('other video')).toBeInTheDocument();
  expect(screen.queryByText('0 published')).toBeNull();
});


test('stopped job with retained clips opens from History', () => {
  const onOpen = vi.fn();
  const item = { jobId: 'stopped-1', status: 'stopped', clipCount: 1,
    title: 'Partial render', timestamp: Date.now() };
  render(<HistoryView history={[item]} availableIds={new Set([item.jobId])}
    onOpen={onOpen} onDelete={vi.fn()} onClear={vi.fn()} />);
  expect(screen.getByText('stopped')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Open job Partial render' }));
  expect(onOpen).toHaveBeenCalledWith(item);
});

test('stopped job without rendered clips cannot be reopened', () => {
  render(<HistoryView history={[{ jobId: 'empty', status: 'stopped', clipCount: 0,
    title: 'Empty partial job', timestamp: Date.now() }]} availableIds={new Set(['empty'])}
    onOpen={vi.fn()} onDelete={vi.fn()} onClear={vi.fn()} />);
  expect(screen.queryByRole('button', { name: /Open job/ })).toBeNull();
});

test('offline history visibly explains that records may be stale', () => {
  render(<HistoryView history={[{ jobId: 'cached', status: 'complete', clipCount: 1,
    title: 'Cached video', timestamp: Date.now() }]} offline
    availableIds={null} onOpen={vi.fn()} onDelete={vi.fn()} onClear={vi.fn()} />);
  expect(screen.getByRole('status')).toHaveTextContent(/backend unavailable/i);
});

test('storage metrics are readable and low-space warning points to selective job deletion', () => {
  const row = { jobId: 'one', status: 'complete', clipCount: 1, title: 'Video', timestamp: Date.now() };
  render(<HistoryView history={[row]} availableIds={new Set(['one'])}
    storageUsage={{ outputBytes: 1048576, dataBytes: 256, uploadsBytes: 1024,
      diskFreeBytes: 2048, diskTotalBytes: 10485760, lowSpace: true,
      jobs: [{ jobId: 'one', bytes: 1048576 }] }}
    onOpen={vi.fn()} onDelete={vi.fn()} onClear={vi.fn()} />);
  expect(screen.getByRole('status', { name: 'Disk storage usage' })).toHaveTextContent('1.0 MB');
  expect(screen.getByRole('alert')).toHaveTextContent('Low disk space');
  expect(screen.getByRole('button', { name: 'Delete job' })).toBeInTheDocument();
});
