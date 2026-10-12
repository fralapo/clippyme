import { beforeEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ResultsView } from './results.jsx';
import { exportClip, downloadClip } from '../../api/client';

vi.mock('../../api/client', () => ({
  clipPreviewSrc: () => '/videos/test.mp4',
  fmtDuration: () => '00:10',
  exportClip: vi.fn(),
  downloadClip: vi.fn(),
}));
vi.mock('../../components/LazyVideo', () => ({
  LazyVideo: () => <div data-testid="video-placeholder" />,
}));

const clips = [
  { original_index: 0, video_title_for_youtube_short: 'First clip', viral_score: 90, start: 0, end: 10 },
  { original_index: 1, video_title_for_youtube_short: 'Second clip', viral_score: 85, start: 10, end: 20 },
];

function mount(selected = clips) {
  const pushToast = vi.fn();
  render(<ResultsView
    clips={selected} jobId="results-qa" preselections={{}}
    clipStates={{}} onUpdateClipState={vi.fn()}
    onPublish={vi.fn()} onPublishAll={vi.fn()} onEdit={vi.fn()}
    onApplyToAll={vi.fn()} onEditSelected={vi.fn()} pushToast={pushToast}
  />);
  return pushToast;
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.mocked(exportClip).mockReset();
  vi.mocked(downloadClip).mockReset();
});

test('a failed edited single export never silently downloads an unedited file', async () => {
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  const toast = mount(clips.slice(0, 1));
  vi.mocked(exportClip).mockRejectedValueOnce(new Error('Subtitles render failed'));
  fireEvent.click(screen.getByRole('button', { name: 'Download First clip' }));
  await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
  expect(confirm.mock.calls[0][0]).toMatch(/unedited original/);
  await waitFor(() => expect(toast).toHaveBeenCalledWith('warn', expect.stringContaining('Subtitles render failed')));
  expect(downloadClip).not.toHaveBeenCalled();
  await waitFor(() => expect(screen.getByRole('button', { name: 'Download First clip' })).toBeEnabled());
});

test('single-clip raw fallback only starts after explicit confirmation', async () => {
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
  const toast = mount(clips.slice(0, 1));
  vi.mocked(exportClip).mockRejectedValueOnce(new Error('Bad subtitles'));
  fireEvent.click(screen.getByRole('button', { name: 'Download First clip' }));
  await waitFor(() => expect(downloadClip).toHaveBeenCalledWith(clips[0], 0));
  expect(confirm).toHaveBeenCalledOnce();
  expect(toast).toHaveBeenCalledWith('warn', expect.stringContaining('unedited download'));
});

test('bulk export reports completed and skipped clips rather than claiming everything exported', async () => {
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  const toast = mount();
  vi.mocked(exportClip).mockResolvedValueOnce('composed').mockRejectedValueOnce(new Error('Compose error'));
  fireEvent.click(screen.getByRole('button', { name: 'Export all' }));
  await waitFor(() => expect(exportClip).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
  await waitFor(() => expect(toast).toHaveBeenCalledWith('warn', expect.stringContaining('Started 1/2 clip downloads')));
  expect(downloadClip).not.toHaveBeenCalled();
});

test('bulk export asks only once, and explicitly counts accepted raw fallbacks', async () => {
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
  const toast = mount();
  vi.mocked(exportClip).mockRejectedValueOnce(new Error('No access')).mockResolvedValueOnce('raw');
  fireEvent.click(screen.getByRole('button', { name: 'Export all' }));
  await waitFor(() => expect(toast).toHaveBeenCalledWith('warn', expect.stringContaining('Started 2/2 clip downloads')));
  expect(downloadClip).toHaveBeenCalledTimes(1);
  expect(downloadClip).toHaveBeenCalledWith(clips[0], 0);
  expect(confirm).toHaveBeenCalledOnce();
  expect(toast).toHaveBeenCalledWith('warn', expect.stringContaining('0 edited, 2 unedited'));
});

test('bulk export with already-raw clips reports them as raw instead of composed', async () => {
  vi.spyOn(window, 'confirm');
  const toast = mount();
  vi.mocked(exportClip).mockResolvedValue('raw');
  fireEvent.click(screen.getByRole('button', { name: 'Export all' }));
  await waitFor(() => expect(toast).toHaveBeenCalledWith('success', expect.stringContaining('0 edited, 2 unedited')));
  expect(window.confirm).not.toHaveBeenCalled();
});
