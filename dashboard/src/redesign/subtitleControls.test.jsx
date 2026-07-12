// SubtitleControls — the shared drawer both editing surfaces render.
// Pins: karaoke vs classic control sets, the onChange partial for every
// control, and that both variants mount with their divergent chrome.
import { test, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { SubtitleControls } from './subtitleControls.jsx';

vi.mock('./realApi', () => ({
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
