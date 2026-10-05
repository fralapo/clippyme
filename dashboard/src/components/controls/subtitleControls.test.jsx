// SubtitleControls — the shared drawer both editing surfaces render.
// Pins: karaoke vs classic control sets, the onChange partial for every
// control, and that both variants mount with their divergent chrome.
import { test, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cwd } from 'node:process';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SubtitleControls } from './subtitleControls.jsx';
import { listFonts } from '../../api/client';

vi.mock('../../api/client', () => ({
  listFonts: vi.fn(async () => ({ fonts: [] })),
}));

const KARAOKE = {
  mode: 'karaoke', preset: 'hormozi_bold', font: 'Montserrat-Black',
  font_color: '#FFFFFF', outline_color: '#000000', font_size: 0,
  border_width: 2, bg: false, position: 'bottom', align: 'center', offset_y: 0,
};

function mount(value = {}, variant = 'edit') {
  const onChange = vi.fn();
  render(<SubtitleControls value={{ ...KARAOKE, ...value }} onChange={onChange} variant={variant} />);
  return onChange;
}

beforeEach(() => vi.clearAllMocks());

test('karaoke shows preset grid + sliders/colors; classic controls absent', () => {
  mount();
  expect(screen.getByRole('button', { name: /Hormozi/ })).toBeInTheDocument();
  expect(screen.getByLabelText('Subtitle font size')).toBeInTheDocument();
  expect(screen.getByLabelText('Subtitle stroke color')).toBeInTheDocument();
  expect(screen.queryByLabelText('Subtitle outline width')).toBeNull();
  expect(screen.queryByText('Background box')).toBeNull();
});

test('classic shows font/swatches/outline/bg; karaoke controls absent', () => {
  mount({ mode: 'classic' });
  expect(screen.getByRole('combobox')).toBeInTheDocument();
  expect(screen.getByLabelText('Font color #FFFFFF')).toBeInTheDocument();
  expect(screen.getByLabelText('Subtitle outline width')).toBeInTheDocument();
  expect(screen.getByText('Background box')).toBeInTheDocument();
  expect(screen.queryByLabelText('Subtitle stroke color')).toBeNull();
});

test('classic subtitles still offer Verdana (Goal 31 removed it from hooks only)', () => {
  mount({ mode: 'classic', font: 'Verdana' });
  expect(screen.getByRole('option', { name: 'Verdana' })).toBeInTheDocument();
  expect(screen.getByRole('combobox').value).toBe('Verdana');
});

test('classic subtitles keep the live NotoSerif-Bold entry (Goal 32 hid it from hooks only)', async () => {
  vi.mocked(listFonts).mockImplementationOnce(async () => ({ fonts: ['Anton-Regular', 'NotoSerif-Bold'] }));
  mount({ mode: 'classic' });
  await waitFor(() => expect(screen.getByRole('option', { name: 'NotoSerif Bold' })).toBeInTheDocument());
  expect(screen.getByRole('option', { name: 'Verdana' })).toBeInTheDocument();
});

test('every karaoke control emits the right partial', () => {
  const onChange = mount();
  fireEvent.click(screen.getByRole('button', { name: 'Classic' }));
  expect(onChange).toHaveBeenLastCalledWith({ mode: 'classic' });
  fireEvent.click(screen.getByRole('button', { name: /Neon/ }));
  expect(onChange).toHaveBeenLastCalledWith({ preset: 'neon_glow' });
  fireEvent.change(screen.getByLabelText('Subtitle font size'), { target: { value: '55' } });
  expect(onChange).toHaveBeenLastCalledWith({ font_size: 55 });
  fireEvent.change(screen.getByLabelText('Subtitle text color'), { target: { value: '#123456' } });
  expect(onChange).toHaveBeenLastCalledWith({ font_color: '#123456' });
  fireEvent.change(screen.getByLabelText('Subtitle stroke color'), { target: { value: '#654321' } });
  expect(onChange).toHaveBeenLastCalledWith({ outline_color: '#654321' });
});

test('every classic + shared control emits the right partial', () => {
  const onChange = mount({ mode: 'classic' });
  fireEvent.click(screen.getByLabelText('Font color #581BBA'));
  expect(onChange).toHaveBeenLastCalledWith({ font_color: '#581BBA' });
  fireEvent.change(screen.getByLabelText('Subtitle outline width'), { target: { value: '4' } });
  expect(onChange).toHaveBeenLastCalledWith({ border_width: 4 });
  fireEvent.click(screen.getByRole('switch'));
  expect(onChange).toHaveBeenLastCalledWith({ bg: true });
  fireEvent.click(screen.getByRole('button', { name: 'Top' }));
  expect(onChange).toHaveBeenLastCalledWith({ position: 'top' });
  fireEvent.click(screen.getByRole('button', { name: 'Left' }));
  expect(onChange).toHaveBeenLastCalledWith({ align: 'left' });
  fireEvent.change(screen.getByLabelText('Subtitle vertical position'), { target: { value: '25' } });
  expect(onChange).toHaveBeenLastCalledWith({ offset_y: 25 });
});

test('fully controlled: never mutates, only reports', () => {
  const onChange = mount();
  fireEvent.click(screen.getByRole('button', { name: 'Classic' }));
  // Still karaoke on screen — the parent owns the state.
  expect(screen.getByLabelText('Subtitle font size')).toBeInTheDocument();
  expect(onChange).toHaveBeenCalledTimes(1);
});

test.each(['create', 'edit'])('variant %s renders its own chrome (D1/D2)', (variant) => {
  mount({ mode: 'classic' }, variant);
  const box = screen.getByText('Background box').closest(variant === 'create' ? '.opt' : '.edit-opt');
  expect(box).not.toBeNull();
});

// Goal 24: each karaoke preset card previews with the SAME bundled face the
// renderer burns (subtitles.py SUBTITLE_PRESETS `font`), at that face's real
// weight — not a system stand-in. Unit-level only: jsdom checks the declared
// inline style; real loading is proven by the CSS/asset test in
// lib/subtitlePreviewFonts.test.js plus a browser smoke.
const PREVIEW_FONTS = [
  ['classic_white', 'Classic', 'Montserrat-Black', '900'],
  ['hormozi_bold', 'Hormozi', 'Bangers-Regular', '400'],
  ['neon_glow', 'Neon', 'Montserrat-Black', '900'],
  ['mrbeast_box', 'MrBeast', 'Poppins-Black', '900'],
  ['minimal_clean', 'Minimal', 'Poppins-Medium', '500'],
  ['fire_impact', 'Fire', 'Anton-Regular', '400'],
];
// By card label, not role: the mode toggle also has a "Classic" button.
const card = (label) => [...document.querySelectorAll('.subpre')].find((b) => b.querySelector('.nm').textContent === label);
const previewSpan = (label) => card(label).querySelector('.prev > span');

test.each(PREVIEW_FONTS)('preset %s (%s) previews with bundled %s at weight %s', (_id, label, font, weight) => {
  mount();
  const span = previewSpan(label);
  expect(span.style.fontFamily).toBe(`"ClippyMe Preview ${font}", sans-serif`);
  expect(span.style.fontWeight).toBe(weight);
});

test('switching preset moves the selection; each card keeps only its own font', () => {
  const onChange = vi.fn();
  const { rerender } = render(<SubtitleControls value={KARAOKE} onChange={onChange} />);
  for (const [id, label, font, weight] of PREVIEW_FONTS) {
    rerender(<SubtitleControls value={{ ...KARAOKE, preset: id }} onChange={onChange} />);
    const on = document.querySelectorAll('.subpre.on');
    expect(on).toHaveLength(1);
    expect(on[0]).toBe(card(label));
    const span = on[0].querySelector('.prev > span');
    expect(span.style.fontFamily).toBe(`"ClippyMe Preview ${font}", sans-serif`);
    expect(span.style.fontWeight).toBe(weight);
  }
});

// Goal 35: body sets the dashboard's OpenType features ("ss01", "cv11",
// "tnum"). Inherited by the preset preview they swap Montserrat's W/U (and
// y/a/t/l… ss01, tabular digits) and Poppins' punctuation, while libass burns
// the TTF's default glyphs. The preview box opts out; the card label keeps
// the body's features. The real app.css is loaded so the cascade/inheritance
// is exercised on the rendered preview text.
test.each(PREVIEW_FONTS)('preset %s (%s) preview text does not inherit the UI font-feature-settings', (_id, label, font, weight) => {
  const sheet = document.createElement('style');
  sheet.textContent = readFileSync(resolve(cwd(), 'src', 'styles', 'app.css'), 'utf8');
  document.head.appendChild(sheet);
  try {
    mount();
    const span = previewSpan(label);
    expect(getComputedStyle(document.body).fontFeatureSettings).toContain('ss01');
    expect(getComputedStyle(span).fontFeatureSettings).toBe('normal');
    expect(getComputedStyle(span.querySelector('span')).fontFeatureSettings).toBe('normal');
    expect(getComputedStyle(span).fontFamily).toBe(`"ClippyMe Preview ${font}", sans-serif`);
    expect(getComputedStyle(span).fontWeight).toBe(weight);
    expect(getComputedStyle(card(label).querySelector('.nm')).fontFeatureSettings)
      .toBe(getComputedStyle(document.body).fontFeatureSettings);
  } finally {
    sheet.remove();
  }
});
