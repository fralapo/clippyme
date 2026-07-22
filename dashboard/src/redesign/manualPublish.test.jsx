// ManualPublishView — mobile-first manual-publish app: Da pubblicare (default)
// / Pubblicate / History / Monitor tabs. Pins: pending-first grouping order
// (platform -> channel -> project -> clip index), complete/restore round
// trip, copy/share/download actions, History per-clip delete with
// confirmation + immediate refresh, and empty/error states.
import { test, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { ManualPublishView } from './manualPublish.jsx';

const PENDING_ENTRIES = [
  { id: 'b1', status: 'pending', job_id: 'job2', clip_index: 1, title: 'Second clip', caption: 'cap B',
    source_platform: 'kick', source_channel: 'xqc', project_title: 'Session A' },
  { id: 'a1', status: 'pending', job_id: 'job1', clip_index: 0, title: 'First clip', caption: 'cap A',
    source_platform: 'kick', source_channel: 'xqc', project_title: 'Session A' },
  { id: 'c1', status: 'pending', job_id: 'job3', clip_index: 0, title: 'Twitch clip', caption: 'cap C',
    source_platform: 'twitch', source_channel: 'shroud', project_title: 'Session Z' },
];

const COMPLETED_ENTRIES = [
  { id: 'd1', status: 'completed', job_id: 'job4', clip_index: 0, title: 'Done clip', caption: 'cap D',
    source_platform: 'kick', source_channel: 'xqc', project_title: 'Session A' },
];

const HISTORY_JOBS = [
  {
    jobId: 'job1', title: 'My video', clipCount: 2,
    clips: [
      { video_url: '/videos/job1/a.mp4', title: 'Clip one', start: 0, end: 10, published: [] },
      { video_url: '/videos/job1/b.mp4', title: 'Clip two', start: 10, end: 20, published: ['tiktok'] },
    ],
  },
];

const getManualQueue = vi.fn();
const completeManualEntry = vi.fn(async () => ({}));
const restoreManualEntry = vi.fn(async () => ({}));
const deleteHistoryClip = vi.fn(async () => ({ project_deleted: false, remaining: 1 }));
const listHistoryJobs = vi.fn(async () => HISTORY_JOBS);

vi.mock('./realApi', () => ({
  getManualQueue: (...args) => getManualQueue(...args),
  completeManualEntry: (...args) => completeManualEntry(...args),
  restoreManualEntry: (...args) => restoreManualEntry(...args),
  manualEntryVideoUrl: (id) => `/api/manual-publish/${id}/video`,
  deleteHistoryClip: (...args) => deleteHistoryClip(...args),
  listHistoryJobs: (...args) => listHistoryJobs(...args),
  fmtDuration: (s, e) => `${Math.round((e || 0) - (s || 0))}s`,
}));

vi.mock('./live.jsx', () => ({ LiveMonitorView: () => <div>Live Monitor stub</div> }));

const shareClip = vi.fn();
vi.mock('../lib/manualShare', () => ({ shareClip: (...args) => shareClip(...args) }));

beforeEach(() => {
  vi.clearAllMocks();
  getManualQueue.mockImplementation(async (status) => ({
    entries: status === 'completed' ? COMPLETED_ENTRIES : PENDING_ENTRIES,
  }));
  vi.stubGlobal('confirm', vi.fn(() => true));
});

test('defaults to the Da pubblicare tab and groups platform -> channel -> project -> clip order', async () => {
  render(<ManualPublishView />);
  await waitFor(() => expect(getManualQueue).toHaveBeenCalledWith('pending'));
  expect(await screen.findByText('First clip')).toBeInTheDocument();
  const titles = screen.getAllByText(/First clip|Second clip|Twitch clip/).map((el) => el.textContent);
  // Session A (kick/xqc) before Session Z (twitch/shroud); within Session A,
  // clip_index 0 ("First clip") before clip_index 1 ("Second clip").
  expect(titles).toEqual(['First clip', 'Second clip', 'Twitch clip']);
});

test('renders breadcrumbs, Copia caption, Condividi, Scarica MP4 and Segna pubblicata', async () => {
  render(<ManualPublishView />);
  await screen.findByText('First clip');
  expect(screen.getAllByText('kick / xqc / Session A')[0]).toBeInTheDocument();
  const card = screen.getByText('First clip').closest('.panel');
  const scoped = within(card);
  expect(scoped.getByRole('button', { name: /Copia caption/ })).toBeInTheDocument();
  expect(scoped.getByRole('button', { name: /Condividi/ })).toBeInTheDocument();
  expect(scoped.getByRole('button', { name: /Scarica MP4/ })).toBeInTheDocument();
  expect(scoped.getByRole('button', { name: /Segna pubblicata/ })).toBeInTheDocument();
});

test('Segna pubblicata completes the entry and refreshes the pending list', async () => {
  render(<ManualPublishView />);
  await screen.findByText('First clip');
  const card = screen.getByText('First clip').closest('.panel');
  fireEvent.click(within(card).getByRole('button', { name: /Segna pubblicata/ }));
  await waitFor(() => expect(completeManualEntry).toHaveBeenCalledWith('a1'));
  await waitFor(() => expect(getManualQueue).toHaveBeenCalledTimes(2));
});

test('Pubblicate tab lists completed entries with Ripristina nella coda', async () => {
  render(<ManualPublishView />);
  fireEvent.click(screen.getByRole('button', { name: 'Pubblicate' }));
  await waitFor(() => expect(getManualQueue).toHaveBeenCalledWith('completed'));
  const card = await screen.findByText('Done clip');
  const scoped = within(card.closest('.panel'));
  const restoreBtn = scoped.getByRole('button', { name: /Ripristina nella coda/ });
  fireEvent.click(restoreBtn);
  await waitFor(() => expect(restoreManualEntry).toHaveBeenCalledWith('d1'));
});

test('Copia caption copies the clip caption to the clipboard', async () => {
  const writeText = vi.fn(async () => {});
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
  render(<ManualPublishView />);
  await screen.findByText('First clip');
  const card = screen.getByText('First clip').closest('.panel');
  fireEvent.click(within(card).getByRole('button', { name: /Copia caption/ }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith('cap A'));
});

test('empty pending queue shows an empty state', async () => {
  getManualQueue.mockResolvedValue({ entries: [] });
  render(<ManualPublishView />);
  expect(await screen.findByText(/Nothing to publish yet/i)).toBeInTheDocument();
});

test('a queue load failure shows an error state, not a crash', async () => {
  getManualQueue.mockRejectedValue(new Error('network down'));
  render(<ManualPublishView />);
  expect(await screen.findByText(/Could not load/i)).toBeInTheDocument();
});

test('History tab lists per-clip rows and deletes one clip after confirmation, then refreshes', async () => {
  render(<ManualPublishView />);
  fireEvent.click(screen.getByRole('button', { name: 'History' }));
  await screen.findByText('My video');
  expect(screen.getByText('Clip one')).toBeInTheDocument();
  expect(screen.getByText('Clip two')).toBeInTheDocument();
  fireEvent.click(screen.getAllByLabelText(/Delete clip/)[0]);
  expect(window.confirm).toHaveBeenCalled();
  await waitFor(() => expect(deleteHistoryClip).toHaveBeenCalledWith('job1', 0));
  await waitFor(() => expect(listHistoryJobs).toHaveBeenCalledTimes(2));
});

test('declining the confirmation does not delete the clip', async () => {
  vi.stubGlobal('confirm', vi.fn(() => false));
  render(<ManualPublishView />);
  fireEvent.click(screen.getByRole('button', { name: 'History' }));
  await screen.findByText('My video');
  fireEvent.click(screen.getAllByLabelText(/Delete clip/)[0]);
  expect(deleteHistoryClip).not.toHaveBeenCalled();
});

test.each([
  ['shared', { shared: true }],
  ['cancelled', { cancelled: true }],
  ['fallback', { fallback: true }],
])('Condividi never marks the entry as completed on a %s share outcome', async (_label, outcome) => {
  shareClip.mockResolvedValue(outcome);
  render(<ManualPublishView />);
  await screen.findByText('First clip');
  const card = screen.getByText('First clip').closest('.panel');
  fireEvent.click(within(card).getByRole('button', { name: /Condividi/ }));
  await waitFor(() => expect(shareClip).toHaveBeenCalled());
  expect(completeManualEntry).not.toHaveBeenCalled();
});

test('Monitor tab renders the Live Monitor view', async () => {
  render(<ManualPublishView />);
  fireEvent.click(screen.getByRole('button', { name: 'Monitor' }));
  expect(await screen.findByText('Live Monitor stub')).toBeInTheDocument();
});
