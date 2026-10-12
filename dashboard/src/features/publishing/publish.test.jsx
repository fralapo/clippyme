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
  // An explicit all-off edit selection means raw even if a stale composed
  // artifact from an earlier edit is still present on the server.
  expect(body.toggles).toEqual({
    smartcut: false, hook: false, subtitles: false,
    logo: false, grade: false, banner: false,
  });
  expect(body).not.toHaveProperty('compose_first');
  expect(body).toHaveProperty('intent_id');
  await waitFor(() => expect(onPublished).toHaveBeenCalledWith(0, 'now'));
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

test('turning scheduling off shows exactly one Publish now action and never a misleading Queue', async () => {
  mount();
  const scheduleButton = screen.getByRole('button', { name: 'Schedule' });
  await waitFor(() => expect(scheduleButton).toBeEnabled());

  fireEvent.click(screen.getByRole('switch'));
  expect(screen.queryByRole('button', { name: 'Queue' })).toBeNull();
  const immediate = screen.getAllByRole('button', { name: 'Publish now' });
  expect(immediate).toHaveLength(1);
  fireEvent.click(immediate[0]);
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

function futureLocalTime() {
  const date = new Date(Date.now() + 72 * 3600 * 1000);
  const pad = (x) => String(x).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

test('single clip can schedule an exact browser-local time through the existing API', async () => {
  mount();
  await waitFor(() => expect(screen.getByRole('button', { name: 'Schedule' })).toBeEnabled());
  fireEvent.click(screen.getByRole('checkbox', { name: 'Choose exact publication time' }));
  const submit = screen.getByRole('button', { name: 'Schedule exact time' });
  expect(submit).toBeDisabled();
  const local = futureLocalTime();
  fireEvent.change(screen.getByLabelText(/Publication date and time/), { target: { value: local } });
  expect(submit).toBeEnabled();
  fireEvent.click(submit);
  await waitFor(() => expect(publishClip).toHaveBeenCalledTimes(1));
  const body = vi.mocked(publishClip).mock.calls[0][2];
  expect(body.schedule_mode).toBe('manual');
  expect(body.scheduled_for).toBe(new Date(local).toISOString());
  expect(body).not.toHaveProperty('start_date');
  await waitFor(() => expect(screen.getByText('Clip scheduled')).toBeInTheDocument());
  expect(screen.getByText(/your selected date and time/)).toBeInTheDocument();
});

test('exact scheduling is unavailable for a multi-clip publish to avoid same-time collisions', async () => {
  mount(clips);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Schedule' })).toBeEnabled());
  expect(screen.queryByRole('checkbox', { name: 'Choose exact publication time' })).toBeNull();
});

test('scheduled clips show scheduled rather than live while other batch posts are pending', async () => {
  let completeSecond;
  const second = new Promise((resolve) => { completeSecond = resolve; });
  vi.mocked(publishClip).mockImplementation((_job, index) =>
    index === 0 ? Promise.resolve({ success: true }) : second
  );
  const onPublished = mount(clips);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Schedule' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Schedule' }));
  await waitFor(() => expect(onPublished).toHaveBeenCalledWith(0, 'auto'));
  expect(screen.getByText('scheduled')).toBeInTheDocument();
  expect(screen.queryByText('live')).toBeNull();
  completeSecond({ success: true });
  await waitFor(() => expect(onPublished).toHaveBeenCalledWith(1, 'auto'));
});
