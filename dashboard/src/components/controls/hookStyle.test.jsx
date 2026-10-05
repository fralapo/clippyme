// Goal 28: the hook preview must draw the bundled face the backend renders
// with. Renderer font IDs ("Anton-Regular") are TTF basenames, not CSS
// families; bundled ones map to the Goal 24 "ClippyMe Preview <id>" @font-face
// at the file's real weight (no faux bold). Uploaded fonts keep their
// name as the family. Exercised through the font <select> → preview span path.
import { test, expect, vi } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cwd } from 'node:process';
import { useState } from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { HookPreview, HookStyleControls } from './hookStyle.jsx';
import { HOOK_STYLE_DEFAULT } from '../../lib/uiOptions';
import { optsToPreselections, listFonts } from '../../api/client';
import { HookTab } from '../../features/clip-editor/editTabs.jsx';
import { useFontCatalog } from '../../hooks/useFontList';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal()),
  listFonts: vi.fn(async () => ({ fonts: ['Anton-Regular', 'MyBrand-Bold'] })),
}));

let latestStyle;
function Hook() {
  const [style, setStyle] = useState({ ...HOOK_STYLE_DEFAULT });
  const fontCatalog = useFontCatalog();
  latestStyle = style;
  return (
    <>
      <HookPreview text="YOUR HOOK TEXT" style={style} fontCatalog={fontCatalog} />
      <HookStyleControls style={style} set={(p) => setStyle((s) => ({ ...s, ...p }))} fonts={fontCatalog.fonts} />
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

// Goal 31: hook_overlay only loads font files from fonts/ and the user fonts
// dir. Verdana (a curated classic-subtitle font resolved by fontconfig) has no
// file there, so the hook renderer burns it as NotoSerif-Bold: not offered.
test('the hook font selector does not offer Verdana', async () => {
  render(<Hook />);
  await waitFor(() => expect(screen.getByRole('option', { name: 'MyBrand Bold' })).toBeInTheDocument());
  const options = screen.getAllByRole('option').map((o) => o.value);
  expect(options).not.toContain('Verdana');
  expect(options).toEqual(expect.arrayContaining(['', 'Montserrat-Black', 'Anton-Regular',
    'Bangers-Regular', 'Poppins-Black', 'Poppins-Medium', 'MyBrand-Bold']));
});

test('every curated hook font choice is a bundled file the hook renderer loads', () => {
  render(<Hook />);
  const curated = screen.getAllByRole('option').map((o) => o.value).filter(Boolean);
  expect(curated.length).toBeGreaterThan(0);
  for (const font of curated) expect(existsSync(resolve(cwd(), '..', 'fonts', `${font}.ttf`)), font).toBe(true);
});

test('an uploaded font keeps its name as the family (no preview face exists)', async () => {
  render(<Hook />);
  await waitFor(() => expect(screen.getByRole('option', { name: 'MyBrand Bold' })).toBeInTheDocument());
  pick('MyBrand-Bold');
  expect(preview().fontFamily).toBe('"MyBrand-Bold", sans-serif');
});

// Goal 29: the empty "Default (serif)" option means "backend default", which
// hook_overlay resolves to fonts/NotoSerif-Bold.ttf. The preview models that
// default with its bundled face (weight 700); the value itself stays empty.
test('empty font previews the backend default Noto Serif Bold face', () => {
  render(<Hook />);
  pick('');
  expect(preview().fontFamily).toBe('"ClippyMe Preview NotoSerif-Bold", sans-serif');
  expect(preview().fontWeight).toBe('700');
});

test('empty font stays empty in state and in the job payload', () => {
  render(<Hook />);
  pick('');
  expect(screen.getByRole('combobox').value).toBe('');
  expect(latestStyle.font).toBe('');
  const { hook } = optsToPreselections({ hooks: true, hookPos: 'top', hookSize: 'M', hookStyle: latestStyle });
  expect(hook.font).toBe('');
});

test('the Noto Serif preview face loads the bundled backend default file at 700', () => {
  // Read from disk: vitest stubs CSS imports. Runs from dashboard/ (npm test).
  const css = readFileSync(resolve(cwd(), 'src', 'styles', 'app.css'), 'utf8');
  const face = [...css.matchAll(/@font-face\s*\{([^}]*)\}/g)].map(([, b]) => b)
    .filter((b) => b.includes('font-family:"ClippyMe Preview NotoSerif-Bold"'));
  expect(face).toHaveLength(1);
  expect(face[0]).toContain('src:url("/fonts/NotoSerif-Bold.ttf") format("truetype")');
  expect(face[0]).toContain('font-weight:700');
  expect(existsSync(resolve(cwd(), '..', 'fonts', 'NotoSerif-Bold.ttf'))).toBe(true);
});

// Goal 30: a hook font that is no longer available (an uploaded font deleted
// in Settings, still named by a saved preset / job pre-selection / clip edit)
// is rendered by hook_overlay with its FONT_PATH fallback, NotoSerif-Bold. The
// preview follows once the live font list has loaded and does not contain the
// name; the stale value itself is never rewritten. Exercised through the real
// editor Hook tab (preview + controls share one font list there, as in Create).
const BUNDLED = ['Anton-Regular', 'Bangers-Regular', 'Montserrat-Black', 'Montserrat-ExtraBold',
  'NotoSerif-Bold', 'Poppins-Black', 'Poppins-Medium'];
const liveList = (fonts) => vi.mocked(listFonts).mockImplementationOnce(async () => ({ fonts }));
const NOTO = '"ClippyMe Preview NotoSerif-Bold", sans-serif';
const tabPreview = () => screen.getByText('YOUR HOOK TEXT', { selector: 'span' }).style;

function EditorHookTab({ font, onStyle = () => {} }) {
  return <HookTab on onToggle={() => {}} text="YOUR HOOK TEXT" onText={() => {}}
    style={{ ...HOOK_STYLE_DEFAULT, font }} onStyle={onStyle} />;
}

test('a deleted custom font previews the backend Noto Serif fallback, state untouched', async () => {
  liveList([...BUNDLED, 'MyBrand-Bold']);
  const onStyle = vi.fn();
  render(<EditorHookTab font="MyDeleted-Font" onStyle={onStyle} />);
  await waitFor(() => expect(tabPreview().fontFamily).toBe(NOTO));
  expect(tabPreview().fontWeight).toBe('700');
  expect(onStyle).not.toHaveBeenCalled();
  const { hook } = optsToPreselections({ hooks: true, hookPos: 'top', hookSize: 'M',
    hookStyle: { ...HOOK_STYLE_DEFAULT, font: 'MyDeleted-Font' } });
  expect(hook.font).toBe('MyDeleted-Font');
});

test('any other name outside the app font list also previews the Noto Serif fallback', async () => {
  liveList([...BUNDLED]);
  render(<EditorHookTab font="Arial" />);
  await waitFor(() => expect(tabPreview().fontFamily).toBe(NOTO));
  expect(tabPreview().fontWeight).toBe('700');
});

test('a custom font still in the live list keeps its name as the family', async () => {
  liveList([...BUNDLED, 'MyBrand-Bold']);
  render(<EditorHookTab font="MyBrand-Bold" />);
  await waitFor(() => expect(screen.getByRole('option', { name: 'MyBrand Bold' })).toBeInTheDocument());
  expect(tabPreview().fontFamily).toBe('"MyBrand-Bold", sans-serif');
  expect(tabPreview().fontWeight).toBe('800');
});

test.each([
  ['the font list request fails', () => vi.mocked(listFonts).mockImplementationOnce(async () => { throw new Error('offline'); })],
  ['the font list is unavailable (empty)', () => liveList([])],
])('a custom font is not treated as missing when %s', async (_, arrange) => {
  arrange();
  render(<EditorHookTab font="MyBrand-Bold" />);
  await waitFor(() => expect(listFonts).toHaveBeenCalled());
  await new Promise((r) => setTimeout(r, 0));
  expect(tabPreview().fontFamily).toBe('"MyBrand-Bold", sans-serif');
});

test.each([
  ['Verdana', NOTO, '700'],
  ['Anton-Regular', '"ClippyMe Preview Anton-Regular", sans-serif', '400'],
  ['', NOTO, '700'],
])('with the live list loaded, %j keeps its Goal 28/29 preview', async (font, family, weight) => {
  liveList([...BUNDLED, 'MyBrand-Bold']);
  render(<EditorHookTab font={font} />);
  await waitFor(() => expect(screen.getByRole('option', { name: 'MyBrand Bold' })).toBeInTheDocument());
  expect(tabPreview().fontFamily).toBe(family);
  expect(tabPreview().fontWeight).toBe(weight);
});

// Goal 31: a saved Verdana hook font (preset, job pre-selection, clip edit)
// stays readable and unchanged, and previews the Noto Serif face the backend
// burns. Verdana is unsupported by design, so this holds before the live font
// list loads too (no flash of a system Verdana).
test.each([
  ['before the live font list loads', () => vi.mocked(listFonts).mockImplementationOnce(() => new Promise(() => {}))],
  ['after the live font list loads', () => liveList([...BUNDLED, 'MyBrand-Bold'])],
  ['when the font list request fails', () => vi.mocked(listFonts).mockImplementationOnce(async () => { throw new Error('offline'); })],
])('a saved Verdana hook font previews Noto Serif %s, state and payload untouched', async (_, arrange) => {
  arrange();
  const onStyle = vi.fn();
  render(<EditorHookTab font="Verdana" onStyle={onStyle} />);
  expect(tabPreview().fontFamily).toBe(NOTO);
  expect(tabPreview().fontWeight).toBe('700');
  await waitFor(() => expect(listFonts).toHaveBeenCalled());
  await new Promise((r) => setTimeout(r, 0));
  expect(tabPreview().fontFamily).toBe(NOTO);
  expect(screen.queryByRole('option', { name: 'Verdana' })).toBeNull();
  expect(onStyle).not.toHaveBeenCalled();
  const { hook } = optsToPreselections({ hooks: true, hookPos: 'top', hookSize: 'M',
    hookStyle: { ...HOOK_STYLE_DEFAULT, font: 'Verdana' } });
  expect(hook.font).toBe('Verdana');
});
