// BannerControls — the shared platform/handle/position drawer (Create +
// EditClipModal). Pins: fully controlled, emits partials, live preview text.
import { test, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { BannerControls } from './bannerControls.jsx';

function mount(value = {}) {
  const onChange = vi.fn();
  render(<BannerControls value={{ platform: 'kick', handle: '', y_pct: 0.85, ...value }} onChange={onChange} />);
  return onChange;
}

test('renders platform options and the handle input with a per-platform placeholder', () => {
  mount();
  expect(screen.getByRole('button', { name: 'Kick' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'YouTube' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Twitch' })).toBeInTheDocument();
  expect(screen.getByLabelText('Banner handle')).toHaveAttribute('placeholder', 'grenbaud');
});

test('youtube placeholder uses the @handle form', () => {
  mount({ platform: 'youtube' });
  expect(screen.getByLabelText('Banner handle')).toHaveAttribute('placeholder', '@GrenBaudLounge');
});

test('every control emits the right partial (fully controlled)', () => {
  const onChange = mount();
  fireEvent.click(screen.getByRole('button', { name: 'Twitch' }));
  expect(onChange).toHaveBeenLastCalledWith({ platform: 'twitch' });
  fireEvent.change(screen.getByLabelText('Banner handle'), { target: { value: 'grenbaud' } });
  expect(onChange).toHaveBeenLastCalledWith({ handle: 'grenbaud' });
  fireEvent.change(screen.getByLabelText('Banner vertical position'), { target: { value: '70' } });
  expect(onChange).toHaveBeenLastCalledWith({ y_pct: 0.7 });
});

test('shows a live preview of the resulting banner text', () => {
  mount({ platform: 'kick', handle: 'grenbaud' });
  expect(screen.getByText(/kick\.com\/grenbaud/)).toBeInTheDocument();
});

test('prompts for a handle when none is set yet', () => {
  mount({ handle: '' });
  expect(screen.getByText(/Enter a handle to preview/)).toBeInTheDocument();
});
