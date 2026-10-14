// The immediate-publish button must never inherit the default auto-schedule
// mode from a React state update in the same click handler.
import process from 'node:process';
import { StrictMode } from 'react';
import { beforeEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { PublishModal } from './publish.jsx';
import { getZernio, getTikTokCreatorInfo, publishClip } from '../../api/client';

vi.mock('../../api/client', () => ({
  getZernio: vi.fn(),
  getTikTokCreatorInfo: vi.fn(),
  publishClip: vi.fn(),
  clipVideoSrc: () => '/videos/clip.mp4',
}));
vi.mock('../../components/LazyVideo', () => ({
  LazyVideo: () => <div data-testid="video-placeholder" />,
}));

const clips = [
  { _idx: 0, original_index: 0, video_title_for_youtube_short: 'First clip', tiktok_caption: 'Caption' },
  { _idx: 1, original_index: 1, video_title_for_youtube_short: 'Second clip', tiktok_caption: 'Different second caption' },
];

function mount(selected = clips.slice(0, 1), onClose = vi.fn()) {
  const onPublished = vi.fn();
  render(<PublishModal clips={selected} jobId="publish-mode-test" clipStates={{}}
    preselections={{}} onClose={onClose} onPublished={onPublished} pushToast={vi.fn()} />);
  return onPublished;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getZernio).mockResolvedValue({
    configured: true, accounts: { tiktok: 'tiktok-account' }, timezone: 'Europe/Rome',
  });
  vi.mocked(getTikTokCreatorInfo).mockResolvedValue({
    privacyLevels: [
      { value: 'PUBLIC_TO_EVERYONE', label: 'Public' },
      { value: 'SELF_ONLY', label: 'Only me' },
    ],
    interactionSettings: { comment: true, duet: true, stitch: false },
    canPostMore: true,
    maxVideoDurationSec: 600,
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
  expect(body.tiktok_settings).toEqual({
    privacy_level: 'PUBLIC_TO_EVERYONE', allow_comment: true, allow_duet: true,
    allow_stitch: false, content_preview_confirmed: true, express_consent_given: true,
  });
  await waitFor(() => expect(onPublished).toHaveBeenCalledWith(0, 'now'));
  await waitFor(() => expect(screen.getByText('Clip submitted')).toBeInTheDocument());
  expect(screen.queryByText('Clip scheduled')).toBeNull();
});

test('TikTok audience and interaction options are loaded for the connected account', async () => {
  mount();
  await waitFor(() => expect(getTikTokCreatorInfo).toHaveBeenCalledWith('tiktok-account'));
  const audience = await screen.findByLabelText('TikTok audience');
  fireEvent.change(audience, { target: { value: 'SELF_ONLY' } });
  fireEvent.click(screen.getByRole('checkbox', { name: 'Allow comments' }));
  fireEvent.click(screen.getByRole('button', { name: 'Publish now' }));
  await waitFor(() => expect(publishClip).toHaveBeenCalledTimes(1));
  expect(publishClip.mock.calls[0][2].tiktok_settings).toMatchObject({
    privacy_level: 'SELF_ONLY', allow_comment: false,
  });
});

test('TikTok publishing stays disabled if creator options cannot be loaded', async () => {
  vi.mocked(getTikTokCreatorInfo).mockRejectedValueOnce(new Error('Zernio unavailable'));
  mount();
  expect(await screen.findByRole('alert')).toHaveTextContent('Zernio unavailable');
  expect(screen.getByRole('button', { name: 'Publish now' })).toBeDisabled();
});

test('TikTok publishing blocks clips longer than the creator limit', async () => {
  vi.mocked(getTikTokCreatorInfo).mockResolvedValueOnce({
    privacyLevels: [{ value: 'SELF_ONLY', label: 'Only me' }],
    interactionSettings: {}, canPostMore: true, maxVideoDurationSec: 20,
  });
  mount([{ ...clips[0], start: 0, end: 25 }]);
  expect(await screen.findByRole('alert')).toHaveTextContent(/exceeds.*20 seconds/);
  expect(screen.getByRole('button', { name: 'Publish now' })).toBeDisabled();
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
  await waitFor(() => expect(screen.getByText('Clip submitted')).toBeInTheDocument());
});

test('a failed publish never shows success and keeps the Zernio error visible', async () => {
  const onPublished = mount();
  vi.mocked(publishClip).mockRejectedValueOnce(new Error('Zernio daily limit reached'));
  const immediate = screen.getByRole('button', { name: 'Publish now' });
  await waitFor(() => expect(immediate).toBeEnabled());

  fireEvent.click(immediate);
  await waitFor(() => expect(screen.getByText('Publishing incomplete')).toBeInTheDocument());
  expect(screen.getByText('0/1 clips submitted')).toBeInTheDocument();
  expect(screen.getByText(/failed: Zernio daily limit reached/)).toBeInTheDocument();
  expect(screen.queryByText('Clip submitted')).toBeNull();
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

test('exact-time UI rejects a repeated DST hour and explains the ambiguity', async () => {
  const original = process.env.TZ;
  try {
    process.env.TZ = 'Europe/Rome';
    mount();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Schedule' })).toBeEnabled());
    fireEvent.click(screen.getByRole('checkbox', { name: 'Choose exact publication time' }));
    fireEvent.change(screen.getByLabelText(/Publication date and time/), {
      target: { value: '2030-10-27T02:30' },
    });
    expect(screen.getByRole('button', { name: 'Schedule exact time' })).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent(/occurs twice/i);
    expect(publishClip).not.toHaveBeenCalled();
  } finally {
    if (original === undefined) delete process.env.TZ;
    else process.env.TZ = original;
  }
});

test('batch defaults to distinct editable captions from each source clip', async () => {
  mount(clips);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Schedule' })).toBeEnabled());
  expect(screen.getByRole('textbox', { name: 'Caption for First clip' })).toHaveValue('Caption');
  expect(screen.getByRole('textbox', { name: 'Caption for Second clip' })).toHaveValue('Different second caption');
  fireEvent.change(screen.getByRole('textbox', { name: 'Caption for Second clip' }), {
    target: { value: 'Edited second only' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Schedule' }));
  await waitFor(() => expect(publishClip).toHaveBeenCalledTimes(2));
  const byIndex = Object.fromEntries(vi.mocked(publishClip).mock.calls.map(([, idx, body]) => [idx, body.caption]));
  expect(byIndex).toEqual({ 0: 'Caption', 1: 'Edited second only' });
});

test('common batch caption applies to every clip only after explicit opt-in', async () => {
  mount(clips);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Schedule' })).toBeEnabled());
  fireEvent.click(screen.getByRole('checkbox', { name: 'Use the same caption for all clips' }));
  expect(screen.queryByRole('textbox', { name: 'Caption for Second clip' })).toBeNull();
  fireEvent.change(screen.getByRole('textbox', { name: 'Shared caption' }), {
    target: { value: 'One shared copy' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Schedule' }));
  await waitFor(() => expect(publishClip).toHaveBeenCalledTimes(2));
  expect(vi.mocked(publishClip).mock.calls.map(([, , body]) => body.caption)).toEqual([
    'One shared copy', 'One shared copy',
  ]);
});

test('batch publishing starts no more than two uploads concurrently', async () => {
  const batch = [...clips, {
    _idx: 2, original_index: 2,
    video_title_for_youtube_short: 'Third clip', tiktok_caption: 'Third caption',
  }];
  let resolveFirst; let resolveSecond;
  const first = new Promise((resolve) => { resolveFirst = resolve; });
  const second = new Promise((resolve) => { resolveSecond = resolve; });
  vi.mocked(publishClip).mockImplementation((_job, idx) => idx === 0 ? first : idx === 1 ? second : Promise.resolve({ success: true }));
  mount(batch);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Schedule' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Schedule' }));
  await waitFor(() => expect(publishClip).toHaveBeenCalledTimes(2));
  expect(vi.mocked(publishClip).mock.calls.map(([, idx]) => idx)).toEqual([0, 1]);
  resolveFirst({ success: true });
  await waitFor(() => expect(publishClip).toHaveBeenCalledTimes(3));
  expect(vi.mocked(publishClip).mock.calls[2][1]).toBe(2);
  resolveSecond({ success: true });
  await waitFor(() => expect(screen.getByText('3 clips scheduled')).toBeInTheDocument());
});

test('close button, backdrop and Escape cannot hide in-flight social uploads', async () => {
  let resolvePost;
  vi.mocked(publishClip).mockImplementation(() => new Promise((resolve) => { resolvePost = resolve; }));
  const onClose = vi.fn();
  mount(clips.slice(0, 1), onClose);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Publish now' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Publish now' }));
  await waitFor(() => expect(publishClip).toHaveBeenCalledOnce());
  expect(screen.getByRole('button', { name: 'Close' })).toBeDisabled();
  fireEvent.keyDown(document, { key: 'Escape' });
  fireEvent.click(screen.getByRole('dialog').parentElement);
  expect(onClose).not.toHaveBeenCalled();
  expect(screen.getByText(/keep this dialog open/i)).toBeInTheDocument();
  resolvePost({ success: true });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Done' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Done' }));
  expect(onClose).toHaveBeenCalledTimes(1);
});

test('StrictMode effect replay does not strand a confirmed post on uploading', async () => {
  render(<StrictMode>
    <PublishModal clips={clips.slice(0, 1)} jobId="strict-publish" clipStates={{}}
      preselections={{}} onClose={vi.fn()} onPublished={vi.fn()} pushToast={vi.fn()} />
  </StrictMode>);
  const button = screen.getByRole('button', { name: 'Publish now' });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  await waitFor(() => expect(publishClip).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.getByText('Clip submitted')).toBeInTheDocument());
});

test('exact-time confirmation shows device timezone, provider timezone and submitted UTC instant', async () => {
  mount();
  await waitFor(() => expect(screen.getByRole('button', { name: 'Schedule' })).toBeEnabled());
  fireEvent.click(screen.getByRole('checkbox', { name: 'Choose exact publication time' }));
  const local = futureLocalTime();
  fireEvent.change(screen.getByLabelText(/Publication date and time/), { target: { value: local } });
  const details = screen.getByRole('status', { name: 'Exact scheduling confirmation' });
  expect(details).toHaveTextContent('Device timezone:');
  expect(details).toHaveTextContent('Zernio timezone: Europe/Rome');
  expect(details).toHaveTextContent(new Date(local).toISOString());
});
