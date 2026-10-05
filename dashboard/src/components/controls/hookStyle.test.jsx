// Goal 28: the hook preview must draw the bundled face the backend renders
// with. Renderer font IDs ("Anton-Regular") are TTF basenames, not CSS
// families; bundled ones map to the Goal 24 "ClippyMe Preview <id>" @font-face
// at the file's real weight (no faux bold). System/uploaded fonts keep their
// name as the family. Exercised through the font <select> → preview span path.
import { test, expect, vi } from 'vitest';
import { useState } from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { HookPreview, HookStyleControls } from './hookStyle.jsx';
import { HOOK_STYLE_DEFAULT } from '../../lib/uiOptions';

vi.mock('../../api/client', () => ({
  listFonts: vi.fn(async () => ({ fonts: ['Anton-Regular', 'MyBrand-Bold'] })),
}));

function Hook() {
  const [style, setStyle] = useState({ ...HOOK_STYLE_DEFAULT });
  return (
    <>
      <HookPreview text="YOUR HOOK TEXT" style={style} />
      <HookStyleControls style={style} set={(p) => setStyle((s) => ({ ...s, ...p }))} />
    </>
  );
}

const preview = () => screen.getByText('YOUR HOOK TEXT').style;
const pick = (font) => fireEvent.change(screen.getByRole('combobox'), { target: { value: font } });

test('default Anton-Regular previews the bundled Anton face at its real weight', () => {
  render(<Hook />);
  expect(HOOK_STYLE_DEFAULT.font).toBe('Anton-Regular');
  expect(preview().fontFamily).toBe('"ClippyMe Preview Anton-Regular", sans-serif');
  expect(preview().fontWeight).toBe('400');
});

test.each([
  ['Bangers-Regular', '400'],
  ['Montserrat-Black', '900'],
  ['Poppins-Black', '900'],
  ['Poppins-Medium', '500'],
])('selecting %s previews its bundled face at weight %s', (font, weight) => {
  render(<Hook />);
  pick(font);
  expect(preview().fontFamily).toBe(`"ClippyMe Preview ${font}", sans-serif`);
  expect(preview().fontWeight).toBe(weight);
});

test('system Verdana keeps its own family name with the sans-serif fallback', () => {
  render(<Hook />);
  pick('Verdana');
  expect(preview().fontFamily).toBe('"Verdana", sans-serif');
  expect(preview().fontWeight).toBe('800');
});

test('an uploaded font keeps its name as the family (no preview face exists)', async () => {
  render(<Hook />);
  await waitFor(() => expect(screen.getByRole('option', { name: 'MyBrand Bold' })).toBeInTheDocument());
  pick('MyBrand-Bold');
  expect(preview().fontFamily).toBe('"MyBrand-Bold", sans-serif');
});

test('empty font keeps the display-font fallback', () => {
  render(<Hook />);
  pick('');
  expect(preview().fontFamily).toBe('var(--font-display)');
});
