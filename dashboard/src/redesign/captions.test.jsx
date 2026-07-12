// EditClipModal — component tests for the staged-edit → Apply payload seam.
// Guards the exact regressions documented in captions.jsx:
//   1. karaoke vs classic subtitle_params shape (no stale style-key leakage)
//   2. manual trim forces the smartcut toggle + sends dropRanges
//   3. no-change apply shows "Save changes" (no-op branch)
//   7. bulk mode hides the Trim tab + hook text, dropRanges always empty
import { test, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { EditClipModal } from './captions.jsx';

vi.mock('./realApi', () => ({
  clipPreviewSrc: () => '/videos/job-1/clip_1.mp4',
  getClipTranscript: vi.fn(async () => ({
    segments: [
      { index: 0, text: 'keep this part', start: 0.0, end: 2.0 },
      { index: 1, text: 'cut me please', start: 2.0, end: 4.0 },
    ],
    duration: 4.0,
    language: 'en',
  })),
  editClipAI: vi.fn(),
  listFonts: vi.fn(async () => ({ fonts: [] })),
}));

const CLIP = { viral_score: 88, title: 'A clip', viral_hook_text: 'THIS changed everything' };

function mount(over = {}) {
  const onApply = vi.fn();
  const onClose = vi.fn();
  render(<EditClipModal clip={CLIP} idx={0} jobId="job-1" initial={undefined}
    appliedMode={undefined} preselections={{}} onClose={onClose} onApply={onApply} {...over} />);
  return { onApply, onClose };
}

const applyBtn = () => screen.getByRole('button', { name: /Apply & reprocess|Save changes|Apply to \d+ clips/ });
const tab = (name) => screen.getByRole('tab', { name });

beforeEach(() => vi.clearAllMocks());

// --- 3. no-op branch ----------------------------------------------------------

test('nothing changed → footer shows "Save changes" and payload is a full no-op', () => {
  const { onApply } = mount();
  expect(applyBtn()).toHaveTextContent('Save changes');
  fireEvent.click(applyBtn());
  const p = onApply.mock.calls[0][0];
  expect(p.reframeMode).toBe(p.baseMode);
  expect(Object.values(p.toggles).every((v) => v === false)).toBe(true);
});

// --- 1. karaoke vs classic payload shape ---------------------------------------

test('karaoke apply sends the karaoke override keys with their defaults', () => {
  const { onApply } = mount();
  fireEvent.click(tab('Captions'));
  fireEvent.click(screen.getByRole('switch'));            // subtitles on (karaoke default)
  fireEvent.click(applyBtn());
  const { toggles, subtitleParams } = onApply.mock.calls[0][0];
  expect(toggles.subtitles).toBe(true);
  expect(subtitleParams.mode).toBe('karaoke');
  expect(subtitleParams.preset).toBe('hormozi_bold');
  expect(subtitleParams.font_color).toBe('#FFFFFF');
  expect(subtitleParams.outline_color).toBe('#000000');
  // font_size 0 = "Auto" → must be omitted so the preset default applies.
  expect(subtitleParams.font_size).toBeUndefined();
});

test('stale karaoke font_size from a prior edit does NOT leak into a classic apply', () => {
  // The regression the captions.jsx comment guards: a raw `...sp` spread of the
  // prior edit's params would carry karaoke-only keys into a classic re-compose.
  const { onApply } = mount({
    initial: { toggles: { subtitles: true },
               subtitleParams: { mode: 'karaoke', preset: 'neon_glow', font_size: 60 } },
  });
  fireEvent.click(tab('Captions'));
  fireEvent.click(screen.getByRole('button', { name: 'Classic' }));
  fireEvent.click(applyBtn());
  const { subtitleParams } = onApply.mock.calls[0][0];
  expect(subtitleParams.mode).toBe('classic');
  expect(subtitleParams.font).toBe('Montserrat-Black');
  expect(subtitleParams.border_width).toBe(2);
  expect(subtitleParams.bg_opacity).toBe(0);
  expect(subtitleParams.font_size).toBeUndefined();       // the stale 60 must not ride along
});

// --- classic background box ------------------------------------------------------

test('classic Background box on → bg_opacity 0.6 with the hardcoded black panel', () => {
  const { onApply } = mount();
  fireEvent.click(tab('Captions'));
  fireEvent.click(screen.getByRole('switch'));            // subtitles on
  fireEvent.click(screen.getByRole('button', { name: 'Classic' }));
  // Two switches now: the Subtitles toggle + the drawer's Background box.
  fireEvent.click(screen.getAllByRole('switch')[1]);
  fireEvent.click(applyBtn());
  const { subtitleParams } = onApply.mock.calls[0][0];
  expect(subtitleParams.bg_opacity).toBe(0.6);
  expect(subtitleParams.bg_color).toBe('#000000');
});

// --- logo tab ---------------------------------------------------------------------

test('logo tab: enable + reposition → logoParams and toggle ride the payload', () => {
  const { onApply } = mount();
  fireEvent.click(tab('Logo'));
  fireEvent.click(screen.getByRole('switch'));            // logo on (defaults top-right / M)
  fireEvent.click(screen.getByRole('button', { name: 'Bot L' }));
  fireEvent.click(screen.getByRole('button', { name: 'S' }));
  fireEvent.click(applyBtn());
  const p = onApply.mock.calls[0][0];
  expect(p.toggles.logo).toBe(true);
  expect(p.logoParams).toEqual({ position: 'bottom-left', size: 'S' });
});

// --- grade tab ---------------------------------------------------------------------

test('grade tab: switch on defaults to warm_cinematic, preset click refines it', () => {
  const { onApply } = mount();
  fireEvent.click(tab('Grade'));
  fireEvent.click(screen.getByRole('switch'));            // grade on → warm_cinematic
  fireEvent.click(screen.getByRole('button', { name: 'Cool' }));
  fireEvent.click(applyBtn());
  const p = onApply.mock.calls[0][0];
  expect(p.toggles.grade).toBe(true);
  expect(p.gradeParams).toEqual({ preset: 'cool_crisp' });
});

test('grade switch off maps back to preset none and toggle false', () => {
  const { onApply } = mount({ initial: { gradeParams: { preset: 'vivid_pop' }, toggles: { grade: true } } });
  fireEvent.click(tab('Grade'));
  fireEvent.click(screen.getByRole('switch'));            // grade off
  fireEvent.click(applyBtn());
  const p = onApply.mock.calls[0][0];
  expect(p.toggles.grade).toBe(false);
  expect(p.gradeParams).toEqual({ preset: 'none' });
});

// --- 2. manual trim forces smartcut --------------------------------------------

test('dropping a transcript segment forces smartcut and sends its span', async () => {
  const { onApply } = mount();
  fireEvent.click(tab('Trim'));
  // Transcript is lazy-loaded on first Trim open.
  const seg = await screen.findByRole('button', { name: /cut me please/ });
  fireEvent.click(seg);
  fireEvent.click(applyBtn());
  const p = onApply.mock.calls[0][0];
  expect(p.toggles.smartcut).toBe(true);                  // forced despite the switch being off
  expect(p.dropRanges).toEqual([[2.0, 4.0]]);
});

// --- 7. bulk mode ---------------------------------------------------------------

test('bulk mode hides the Trim tab and the hook text field, dropRanges stay empty', () => {
  const { onApply } = mount({ bulk: true, targetCount: 3 });
  expect(screen.queryByRole('tab', { name: 'Trim' })).toBeNull();
  fireEvent.click(tab('Hook'));
  fireEvent.click(screen.getByRole('switch'));            // hook on
  expect(screen.queryByPlaceholderText(/THIS changed everything/)).toBeNull();
  expect(screen.queryByRole('textbox')).toBeNull();       // no hook-text textarea in bulk
  fireEvent.click(screen.getByRole('button', { name: 'Apply to 3 clips' }));
  const p = onApply.mock.calls[0][0];
  expect(p.toggles.hook).toBe(true);
  expect(p.dropRanges).toEqual([]);
});
