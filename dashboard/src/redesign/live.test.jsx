// LiveMonitorView — pins: slug validation gates Start, and the status panel
// renders correctly for a couple of monitor states.
import { test, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { LiveMonitorView } from './live.jsx';

const mockStatus = vi.fn();

vi.mock('./realApi', () => ({
  getZernio: vi.fn(async () => ({
    configured: true,
    accounts: { tiktok: 'tt-1', instagram: '', youtube: '' },
  })),
  startLiveMonitor: vi.fn(async () => ({ running: true, state: 'waiting_live' })),
  stopLiveMonitor: vi.fn(async () => ({ running: false, state: 'idle' })),
  getLiveMonitorStatus: (...args) => mockStatus(...args),
}));

beforeEach(() => {
  vi.clearAllMocks();
  mockStatus.mockResolvedValue({ running: false, state: 'idle', segments_captured: 0, clips_published: 0 });
});

test('start is disabled until a valid slug is entered', async () => {
  render(<LiveMonitorView />);
  await screen.findByLabelText('Kick channel slug');
  const startBtn = screen.getByRole('button', { name: /Start monitor/ });
  expect(startBtn).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Kick channel slug'), { target: { value: 'xqc' } });
  await waitFor(() => expect(startBtn).not.toBeDisabled());
});

test('invalid slug shows an inline error after blur', () => {
  render(<LiveMonitorView />);
  const input = screen.getByLabelText('Kick channel slug');
  fireEvent.change(input, { target: { value: 'has space' } });
  fireEvent.blur(input);
  expect(screen.getByText(/lowercase letters, numbers/)).toBeInTheDocument();
});

test('empty slug still blocks start after touching the field', () => {
  render(<LiveMonitorView />);
  const input = screen.getByLabelText('Kick channel slug');
  fireEvent.blur(input);
  expect(screen.getByText('Channel slug is required')).toBeInTheDocument();
});

test('capturing status hides the start form and shows Stop', async () => {
  mockStatus.mockResolvedValue({
    running: true, state: 'capturing', slug: 'xqc', segments_captured: 2, clips_published: 5,
  });
  render(<LiveMonitorView />);
  expect(await screen.findByText('Capturing segment')).toBeInTheDocument();
  expect(screen.getByText('xqc')).toBeInTheDocument();
  expect(screen.getByText(/2 segment\(s\) captured/)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Start monitor/ })).toBeNull();
  expect(screen.getByRole('button', { name: /Stop/ })).toBeInTheDocument();
});

test('idle status shows the start form', async () => {
  render(<LiveMonitorView />);
  expect(await screen.findByText('Idle')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Start monitor/ })).toBeInTheDocument();
});
