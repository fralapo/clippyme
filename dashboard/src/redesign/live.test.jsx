// LiveMonitorView — pins: per-platform channel validation gates Start, the
// monitor list renders multiple concurrent monitors, and youtube forces VOD.
import { test, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { LiveMonitorView } from './live.jsx';

const mockStatus = vi.fn();

vi.mock('./realApi', () => ({
  getZernio: vi.fn(async () => ({
    configured: true,
    accounts: { tiktok: 'tt-1', instagram: '', youtube: '' },
  })),
  startLiveMonitor: vi.fn(async () => ({ id: 'kick:xqc', running: true, state: 'waiting_live' })),
  stopLiveMonitor: vi.fn(async () => ({ running: false, state: 'idle' })),
  getLiveMonitorStatus: (...args) => mockStatus(...args),
  updateMonitorConfig: vi.fn(async () => ({ monitor: {} })),
  setMonitorPublishing: vi.fn(async () => ({ publishing_enabled: true })),
  listFonts: vi.fn(async () => ({ fonts: [] })),
}));

beforeEach(() => {
  vi.clearAllMocks();
  mockStatus.mockResolvedValue({ monitors: [] });
});

test('start is disabled until a valid channel is entered', async () => {
  render(<LiveMonitorView />);
  await screen.findByLabelText('Channel');
  const startBtn = screen.getByRole('button', { name: /Start monitor/ });
  expect(startBtn).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Channel'), { target: { value: 'xqc' } });
  await waitFor(() => expect(startBtn).not.toBeDisabled());
});

test('invalid channel shows an inline error after blur', () => {
  render(<LiveMonitorView />);
  const input = screen.getByLabelText('Channel');
  fireEvent.change(input, { target: { value: 'has space' } });
  fireEvent.blur(input);
  expect(screen.getByText(/lowercase letters, numbers/)).toBeInTheDocument();
});

test('empty channel still blocks start after touching the field', () => {
  render(<LiveMonitorView />);
  const input = screen.getByLabelText('Channel');
  fireEvent.blur(input);
  expect(screen.getByText('Channel is required')).toBeInTheDocument();
});

test('start form is always visible alongside a running monitor', async () => {
  mockStatus.mockResolvedValue({
    monitors: [{ id: 'kick:xqc', platform: 'kick', mode: 'live', running: true, state: 'capturing',
      channel: 'xqc', segments_captured: 2, clips_published: 5 }],
  });
  render(<LiveMonitorView />);
  expect(await screen.findByText('Capturing segment')).toBeInTheDocument();
  expect(screen.getByText('xqc')).toBeInTheDocument();
  expect(screen.getByText(/2 segment\(s\) captured/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Start monitor/ })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Stop/ })).toBeInTheDocument();
});

test('monitor list renders multiple concurrent monitors', async () => {
  mockStatus.mockResolvedValue({
    monitors: [
      { id: 'kick:xqc', platform: 'kick', mode: 'live', running: true, state: 'capturing', channel: 'xqc' },
      { id: 'youtube:@MrBeast', platform: 'youtube', mode: 'vod', running: true, state: 'watching', channel: '@MrBeast' },
    ],
  });
  render(<LiveMonitorView />);
  expect(await screen.findByText('xqc')).toBeInTheDocument();
  expect(screen.getByText('@MrBeast')).toBeInTheDocument();
  expect(screen.getByText('Watching for new uploads')).toBeInTheDocument();
  expect(screen.getAllByRole('button', { name: /Stop/ })).toHaveLength(2);
});

test('idle empty list shows "No monitors running."', async () => {
  render(<LiveMonitorView />);
  expect(await screen.findByText('No monitors running.')).toBeInTheDocument();
});

test('selecting YouTube forces VOD mode and hides live-only fields', async () => {
  render(<LiveMonitorView />);
  fireEvent.click(screen.getByRole('button', { name: 'YouTube' }));
  await waitFor(() => expect(screen.queryByLabelText('Segment minutes')).toBeNull());
  expect(screen.queryByLabelText('Prelive skip minutes')).toBeNull();
  expect(screen.getByText(/YouTube: clips every new long-form upload/)).toBeInTheDocument();
});

test('duplicate monitor (409) shows a warning toast', async () => {
  const { startLiveMonitor } = await import('./realApi');
  startLiveMonitor.mockRejectedValueOnce(new Error('monitor already running: kick:xqc'));
  const pushToast = vi.fn();
  render(<LiveMonitorView pushToast={pushToast} />);
  fireEvent.change(screen.getByLabelText('Channel'), { target: { value: 'xqc' } });
  await waitFor(() => expect(screen.getByRole('button', { name: /Start monitor/ })).not.toBeDisabled());
  fireEvent.click(screen.getByRole('button', { name: /Start monitor/ }));
  await waitFor(() => expect(pushToast).toHaveBeenCalledWith('warn', expect.stringMatching(/already monitoring/i)));
});

test('banner defaults to Auto and sends null', async () => {
  const { startLiveMonitor } = await import('./realApi');
  render(<LiveMonitorView />);
  fireEvent.change(screen.getByLabelText('Channel'), { target: { value: 'xqc' } });
  await waitFor(() => expect(screen.getByRole('button', { name: /Start monitor/ })).not.toBeDisabled());
  fireEvent.click(screen.getByRole('button', { name: /Start monitor/ }));
  await waitFor(() => expect(startLiveMonitor).toHaveBeenCalled());
  expect(startLiveMonitor.mock.calls[0][0].banner).toBeNull();
});

test('AI instructions field is included in the start payload', async () => {
  const { startLiveMonitor } = await import('./realApi');
  render(<LiveMonitorView />);
  fireEvent.change(screen.getByLabelText('AI instructions'), { target: { value: 'find the funniest bits' } });
  fireEvent.change(screen.getByLabelText('Channel'), { target: { value: 'xqc' } });
  await waitFor(() => expect(screen.getByRole('button', { name: /Start monitor/ })).not.toBeDisabled());
  fireEvent.click(screen.getByRole('button', { name: /Start monitor/ }));
  await waitFor(() => expect(startLiveMonitor).toHaveBeenCalled());
  expect(startLiveMonitor.mock.calls[0][0].instructions).toBe('find the funniest bits');
});

test('banner Off sends {enabled:false}', async () => {
  const { startLiveMonitor } = await import('./realApi');
  render(<LiveMonitorView />);
  fireEvent.click(screen.getByRole('button', { name: 'Off' }));
  fireEvent.change(screen.getByLabelText('Channel'), { target: { value: 'xqc' } });
  await waitFor(() => expect(screen.getByRole('button', { name: /Start monitor/ })).not.toBeDisabled());
  fireEvent.click(screen.getByRole('button', { name: /Start monitor/ }));
  await waitFor(() => expect(startLiveMonitor).toHaveBeenCalled());
  expect(startLiveMonitor.mock.calls[0][0].banner).toEqual({ enabled: false });
});

test('banner Custom reveals platform+handle and sends the override', async () => {
  const { startLiveMonitor } = await import('./realApi');
  render(<LiveMonitorView />);
  fireEvent.click(screen.getByRole('button', { name: 'Custom' }));
  const twitchBtns = screen.getAllByRole('button', { name: 'Twitch' });
  fireEvent.click(twitchBtns[twitchBtns.length - 1]); // the banner drawer's platform picker
  fireEvent.change(screen.getByLabelText('Banner handle'), { target: { value: 'xqc' } });
  fireEvent.change(screen.getByLabelText('Channel'), { target: { value: 'xqc' } });
  await waitFor(() => expect(screen.getByRole('button', { name: /Start monitor/ })).not.toBeDisabled());
  fireEvent.click(screen.getByRole('button', { name: /Start monitor/ }));
  await waitFor(() => expect(startLiveMonitor).toHaveBeenCalled());
  expect(startLiveMonitor.mock.calls[0][0].banner).toEqual({ platform: 'twitch', handle: 'xqc', y_pct: 0.85 });
});

test('catchup select value rides the start payload', async () => {
  const { startLiveMonitor } = await import('./realApi');
  render(<LiveMonitorView />);
  fireEvent.click(screen.getByRole('button', { name: 'From now only' }));
  fireEvent.change(screen.getByLabelText('Channel'), { target: { value: 'xqc' } });
  await waitFor(() => expect(screen.getByRole('button', { name: /Start monitor/ })).not.toBeDisabled());
  fireEvent.click(screen.getByRole('button', { name: /Start monitor/ }));
  await waitFor(() => expect(startLiveMonitor).toHaveBeenCalled());
  expect(startLiveMonitor.mock.calls[0][0].catchup).toBe('live_only');
});

test('catchup defaults to backfill', async () => {
  const { startLiveMonitor } = await import('./realApi');
  render(<LiveMonitorView />);
  fireEvent.change(screen.getByLabelText('Channel'), { target: { value: 'xqc' } });
  await waitFor(() => expect(screen.getByRole('button', { name: /Start monitor/ })).not.toBeDisabled());
  fireEvent.click(screen.getByRole('button', { name: /Start monitor/ }));
  await waitFor(() => expect(startLiveMonitor).toHaveBeenCalled());
  expect(startLiveMonitor.mock.calls[0][0].catchup).toBe('backfill');
});

test('subtitle override section untouched → start payload has no compose key', async () => {
  const { startLiveMonitor } = await import('./realApi');
  render(<LiveMonitorView />);
  fireEvent.change(screen.getByLabelText('Channel'), { target: { value: 'xqc' } });
  await waitFor(() => expect(screen.getByRole('button', { name: /Start monitor/ })).not.toBeDisabled());
  fireEvent.click(screen.getByRole('button', { name: /Start monitor/ }));
  await waitFor(() => expect(startLiveMonitor).toHaveBeenCalled());
  expect(startLiveMonitor.mock.calls[0][0].compose).toBeUndefined();
});

test('subtitle override section switched on → start payload carries a compose.subtitle_params key', async () => {
  const { startLiveMonitor } = await import('./realApi');
  render(<LiveMonitorView />);
  fireEvent.click(screen.getByRole('switch', { name: 'Customize subtitles' }));
  fireEvent.change(screen.getByLabelText('Channel'), { target: { value: 'xqc' } });
  await waitFor(() => expect(screen.getByRole('button', { name: /Start monitor/ })).not.toBeDisabled());
  fireEvent.click(screen.getByRole('button', { name: /Start monitor/ }));
  await waitFor(() => expect(startLiveMonitor).toHaveBeenCalled());
  expect(startLiveMonitor.mock.calls[0][0].compose).toEqual({ subtitle_params: expect.objectContaining({ position: 'bottom' }) });
});

test('publishing toggle calls setMonitorPublishing with the flipped value', async () => {
  const { setMonitorPublishing } = await import('./realApi');
  mockStatus.mockResolvedValue({
    monitors: [{ id: 'kick:xqc', platform: 'kick', mode: 'live', running: true, state: 'capturing',
      channel: 'xqc', publishing_enabled: false, pending_publish: 3 }],
  });
  render(<LiveMonitorView />);
  expect(await screen.findByText('Paused — 3 clip(s) waiting')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('switch', { name: 'Zernio auto-publish kick:xqc' }));
  await waitFor(() => expect(setMonitorPublishing).toHaveBeenCalledWith('kick:xqc', true));
});

test('config Applica posts only changed/allowed fields (instructions + caption_template)', async () => {
  const { updateMonitorConfig } = await import('./realApi');
  mockStatus.mockResolvedValue({
    monitors: [{ id: 'kick:xqc', platform: 'kick', mode: 'live', running: true, state: 'capturing', channel: 'xqc' }],
  });
  render(<LiveMonitorView />);
  await screen.findByText('xqc');
  fireEvent.click(screen.getByRole('button', { name: 'Settings' }));
  fireEvent.change(screen.getByLabelText('Settings instructions kick:xqc'), { target: { value: 'find hype moments' } });
  fireEvent.change(screen.getByLabelText('Settings caption template kick:xqc'), { target: { value: '{hook}' } });
  fireEvent.click(screen.getByRole('button', { name: /Apply/ }));
  await waitFor(() => expect(updateMonitorConfig).toHaveBeenCalledWith('kick:xqc', {
    instructions: 'find hype moments',
    caption_template: '{hook}',
  }));
});

test('twitch missing-credentials (400) points to Settings', async () => {
  const { startLiveMonitor } = await import('./realApi');
  startLiveMonitor.mockRejectedValueOnce(new Error(
    'Twitch monitoring requires TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET (set them in Settings or the environment)'));
  const pushToast = vi.fn();
  render(<LiveMonitorView pushToast={pushToast} />);
  fireEvent.click(screen.getByRole('button', { name: 'Twitch' }));
  fireEvent.change(screen.getByLabelText('Channel'), { target: { value: 'xqc' } });
  await waitFor(() => expect(screen.getByRole('button', { name: /Start monitor/ })).not.toBeDisabled());
  fireEvent.click(screen.getByRole('button', { name: /Start monitor/ }));
  await waitFor(() => expect(pushToast).toHaveBeenCalledWith('error', expect.stringMatching(/Twitch not configured/i)));
});
