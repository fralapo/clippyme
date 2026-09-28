
import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { Btn, Segmented, Switch } from './primitives';

test('button exposes loading state and blocks duplicate action', () => {
  const onClick = vi.fn();
  render(<Btn loading onClick={onClick}>Save</Btn>);
  const button = screen.getByRole('button', { name: 'Save' });
  expect(button).toBeDisabled();
  expect(button).toHaveAttribute('aria-busy', 'true');
});

test('switch has native switch semantics', () => {
  const onChange = vi.fn();
  render(<Switch on={false} onChange={onChange} label="Subtitles" />);
  fireEvent.click(screen.getByRole('switch', { name: 'Subtitles' }));
  expect(onChange).toHaveBeenCalledWith(true);
});

test('segmented control supports arrow-key selection', () => {
  const onChange = vi.fn();
  render(<Segmented value="a" onChange={onChange} options={[{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }]} />);
  fireEvent.keyDown(screen.getByRole('button', { name: 'A' }), { key: 'ArrowRight' });
  expect(onChange).toHaveBeenCalledWith('b');
});
