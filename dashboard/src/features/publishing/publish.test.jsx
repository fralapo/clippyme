// The immediate-publish button must never inherit the default auto-schedule
// mode from a React state update in the same click handler.
import { beforeEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { PublishModal } from './publish.jsx';
import { getZernio, publishClip } from '../../api/client';

vi.mock('../../api/client', () => ({
  getZernio: vi.fn(),
  publishClip: vi.fn(),
  clipVideoSrc: () => '/videos/clip.mp4',
}));
vi.mock('../../components/LazyVideo', () => ({
  LazyVideo: () => <div data-testid="video-placeholder" />,
}));

const clips = [
  { _idx: 0, original_index: 0, video_title_for_youtube_short: 'First clip', tiktok_caption: 'Caption' },
  { _idx: 1, original_index: 1, video_title_for_youtube_short: 'Second clip', tiktok_caption: 'Caption' },
];

function mount(selected = clips.slice(0, 1)) {
  const onPublished = vi.fn();
  render(<PublishModal clips={selected} jobId="publish-mode-test" clipStates={{}}
    preselections={{}} onClose={vi.fn()} onPublished={onPublished} pushToast={vi.fn()} />);
  return onPublished;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getZernio).mockResolvedValue({
    configured: true, accounts: { tiktok: 'tiktok-account' }, timezone: 'Europe/Rome',
  });
  vi.mocked(publishClip).mockResolvedValue({ success: true });
});

test('Publish now sends now, even though the scheduling switch defaults to on', async () => {
  const onPublished = mount();
  const immediate = screen.getByRole('button', { name: 'Publish now' });
  await waitFor(() => expect(immediate).toBeEnabled());
  expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true');

  fireEvent.click(immediate);
  await waitFor(() => expect(publishClip).toHaveBeenCalledTimes(1));

  const [jobId, index, body] = vi.mocked(publishClip).mock.calls[0];
  expect(jobId).toBe('publish-mode-test');
  expect(index).toBe(0);
  expect(body.schedule_mode).toBe('now');
  expect(body).not.toHaveProperty('start_date');
  expect(body).toHaveProperty('intent_id');
  await waitFor(() => expect(onPublished).toHaveBeenCalledWith(0));
  await waitFor(() => expect(screen.getByText('Clip published')).toBeInTheDocument());
  expect(screen.queryByText('Clip scheduled')).toBeNull();
});

test('Schedule keeps auto mode and gives each batch clip its own day', async () => {
  mount(clips);
  const scheduleButton = screen.getByRole('button', { name: 'Schedule' });
  await waitFor(() => expect(scheduleButton).toBeEnabled());

  fireEvent.click(scheduleButton);
  await waitFor(() => expect(publishClip).toHaveBeenCalledTimes(2));
  const bodies = vi.mocked(publishClip).mock.calls.map((args) => args[2]);
  expect(bodies.map((body) => body.schedule_mode)).toEqual(['auto', 'auto']);
  expect(bodies.every((body) => /^\d{4}-\d{2}-\d{2}$/.test(body.start_date))).toBe(true);
  expect(bodies[0].start_date).not.toBe(bodies[1].start_date);
  await waitFor(() => expect(screen.getByText('2 clips scheduled')).toBeInTheDocument());
});

test('turning prime-time scheduling off makes the primary Queue action publish now', async () => {
  mount();
  const primary = screen.getByRole('button', { name: 'Schedule' });
  await waitFor(() => expect(primary).toBeEnabled());

  fireEvent.click(screen.getByRole('switch'));
  fireEvent.click(screen.getByRole('button', { name: 'Queue' }));
  await waitFor(() => expect(publishClip).toHaveBeenCalledTimes(1));
  expect(vi.mocked(publishClip).mock.calls[0][2].schedule_mode).toBe('now');
  expect(vi.mocked(publishClip).mock.calls[0][2]).not.toHaveProperty('start_date');
  await waitFor(() => expect(screen.getByText('Clip published')).toBeInTheDocument());
});

test('a failed publish never shows success and keeps the Zernio error visible', async () => {
  const onPublished = mount();
  vi.mocked(publishClip).mockRejectedValueOnce(new Error('Zernio daily limit reached'));
  const immediate = screen.getByRole('button', { name: 'Publish now' });
  await waitFor(() => expect(immediate).toBeEnabled());

  fireEvent.click(immediate);
  await waitFor(() => expect(screen.getByText('Publishing incomplete')).toBeInTheDocument());
  expect(screen.getByText('0/1 clips published')).toBeInTheDocument();
  expect(screen.getByText(/failed: Zernio daily limit reached/)).toBeInTheDocument();
  expect(screen.queryByText('Clip published')).toBeNull();
  expect(onPublished).not.toHaveBeenCalled();
});
