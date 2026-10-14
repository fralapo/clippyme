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
  { original_index: 0, video_title_for_youtube_short: 'First clip', viral_score: 90, start: 0, end: 10, review_status: 'approved' },
  { original_index: 1, video_title_for_youtube_short: 'Second clip', viral_score: 85, start: 10, end: 20, review_status: 'approved' },
];

function mount(selected = clips, clipStates = {}, onPublishAll = vi.fn(), onReviewClip = vi.fn().mockResolvedValue({})) {
  const pushToast = vi.fn();
  render(<ResultsView
    clips={selected} jobId="results-qa" preselections={{}}
    clipStates={clipStates} onUpdateClipState={vi.fn()}
    onPublish={vi.fn()} onPublishAll={onPublishAll} onEdit={vi.fn()}
    onApplyToAll={vi.fn()} onEditSelected={vi.fn()} onReviewClip={onReviewClip} pushToast={pushToast}
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

test('a scheduled clip keeps a scheduled badge rather than claiming it is published', () => {
  mount(clips.slice(0, 1), { 0: { publishedAt: 123, publicationStatus: 'scheduled' } });
  expect(screen.getByText('scheduled')).toBeInTheDocument();
  expect(screen.queryByText('published')).toBeNull();
});

test('immediate accepted requests show submitted while persisted legacy entries remain compatible', () => {
  mount(clips, {
    0: { publishedAt: 123, publicationStatus: 'submitted' },
    1: { publishedAt: 456 },
  });
  expect(screen.getByText('submitted')).toBeInTheDocument();
  expect(screen.getByText('published')).toBeInTheDocument();
});

test('manual bulk publish includes only approved clips that are not reprocessing', () => {
  const onPublishAll = vi.fn();
  mount(clips, { 0: { processing: true } }, onPublishAll);
  expect(screen.getByText(/1 clip still reprocessing/i)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Publish approved 1' }));
  expect(onPublishAll).toHaveBeenCalledTimes(1);
  expect(onPublishAll.mock.calls[0][0].map((c) => c.original_index)).toEqual([1]);
});

test('manual bulk publish is disabled when none are approved and ready', () => {
  const onPublishAll = vi.fn();
  mount(clips.map((clip) => ({ ...clip, review_status: 'pending' })), {}, onPublishAll);
  expect(screen.getByRole('button', { name: 'Publish approved 0' })).toBeDisabled();
  expect(onPublishAll).not.toHaveBeenCalled();
});

test('operator approval is saved before the clip can enter manual publish batches', async () => {
  const pending = [{ ...clips[0], review_status: 'pending' }];
  const onReviewClip = vi.fn().mockResolvedValue({ review_status: 'approved' });
  const onPublishAll = vi.fn();
  mount(pending, {}, onPublishAll, onReviewClip);

  expect(screen.getByRole('button', { name: 'Publish First clip' })).toBeDisabled();
  fireEvent.click(screen.getByText('Optional approval feedback'));
  fireEvent.change(screen.getByLabelText('Why is this clip worth keeping?'), { target: { value: 'strong_payoff' } });
  fireEvent.click(screen.getByRole('button', { name: 'Approve First clip' }));

  await waitFor(() => expect(onReviewClip).toHaveBeenCalledWith(0, 'approved', '', 'strong_payoff'));
  expect(screen.getByText('Pending review')).toBeInTheDocument();
  expect(onPublishAll).not.toHaveBeenCalled();
});

test('request changes requires a note and exposes a retry after persistence fails', async () => {
  const onReviewClip = vi.fn().mockRejectedValueOnce(new Error('Disk unavailable'));
  mount([{ ...clips[0], review_status: 'changes_requested', review_note: 'Keep the whole sentence.' }], {}, vi.fn(), onReviewClip);

  expect(screen.getByText('Keep the whole sentence.')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Edit request' }));
  const note = screen.getByRole('textbox', { name: 'What should change?' });
  expect(note).toHaveValue('Keep the whole sentence.');
  fireEvent.change(note, { target: { value: 'Keep the full sentence and ending.' } });
  fireEvent.change(screen.getByLabelText('Optional feedback reason'), { target: { value: 'cut_loses_context' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save change request' }));

  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Disk unavailable'));
  expect(onReviewClip).toHaveBeenCalledWith(0, 'changes_requested', 'Keep the full sentence and ending.', 'cut_loses_context');
  expect(screen.getByRole('button', { name: 'Save change request' })).toBeEnabled();
});

test('discard can save one explicit reason without sending free-form clip data', async () => {
  const onReviewClip = vi.fn().mockResolvedValue({ review_status: 'discarded' });
  mount([{ ...clips[0], review_status: 'pending' }], {}, vi.fn(), onReviewClip);

  fireEvent.click(screen.getByRole('button', { name: 'Discard' }));
  fireEvent.change(screen.getByLabelText('Optional feedback reason'), { target: { value: 'weak_moment' } });
  fireEvent.click(screen.getByRole('button', { name: 'Confirm discard' }));

  await waitFor(() => expect(onReviewClip).toHaveBeenCalledWith(0, 'discarded', '', 'weak_moment'));
});

test('selection mode does not publish a clip currently being reprocessed', () => {
  const onPublishAll = vi.fn();
  mount(clips, { 0: { processing: true }, 1: { selected: true } }, onPublishAll);
  fireEvent.click(screen.getByRole('button', { name: 'Select' }));
  // Mocked onUpdateClipState does not rerender the harness. Both original
  // clips were selected, so Select-all is already in its checked state.
  expect(screen.getByRole('button', { name: 'Publish approved 1' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'Publish approved 1' }));
  expect(onPublishAll.mock.calls[0][0].map((c) => c.original_index)).toEqual([1]);
});

test('provider-accepted scheduled post restores its status from job metadata after browser state is lost', () => {
  const restored = [{ ...clips[0], published: [{
    post_id: 'provider-id', at: '2030-01-01T00:00:00.000Z',
    scheduled_for: '2030-01-02T12:00:00.000Z',
  }] }];
  mount(restored, {});
  expect(screen.getByText('scheduled')).toBeInTheDocument();
  expect(screen.queryByText('published')).toBeNull();
});

test('provider-accepted immediate post restores as submitted without localStorage', () => {
  mount([{ ...clips[0], published: [{ at: '2030-01-01T00:00:00.000Z', post_id: 'provider-id' }] }], {});
  expect(screen.getByText('submitted')).toBeInTheDocument();
  expect(screen.queryByText('published')).toBeNull();
});

test('newer provider record takes priority over an old local published badge', () => {
  mount([{ ...clips[0], published: [{
    at: '2030-01-01T00:00:00.000Z', scheduled_for: '2030-01-02T12:00:00.000Z',
  }] }], { 0: { publishedAt: 456 } });
  expect(screen.getByText('scheduled')).toBeInTheDocument();
  expect(screen.queryByText('published')).toBeNull();
});

test('a newer local submission remains visible before a refreshed server result arrives', () => {
  mount([{ ...clips[0], published: [{
    at: '2020-01-01T00:00:00.000Z', scheduled_for: '2020-01-02T12:00:00.000Z',
  }] }], { 0: { publishedAt: Date.now(), publicationStatus: 'submitted' } });
  expect(screen.getByText('submitted')).toBeInTheDocument();
  expect(screen.queryByText('scheduled')).toBeNull();
});
