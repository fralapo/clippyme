// Goal 24: the karaoke preset preview must be able to LOAD the face it
// declares. Pins, for every preset font in uiOptions.SUBTITLE_PRESETS and the
// hook-only Montserrat-ExtraBold face (Goal 33):
//   - an @font-face in styles/app.css with the preview family name, the real
//     weight, and a same-origin /fonts/<font>.ttf source (no remote fetch);
//   - that the referenced file is a bundled TTF in the repo's fonts/ dir.
// This is still static evidence: actual browser loading is verified with a
// Chromium smoke (document.fonts / rendered platform font), not in jsdom.
import { test, expect } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { cwd } from 'node:process';
import { SUBTITLE_PRESETS } from './uiOptions';

// Vitest runs from dashboard/ (npm test); the bundled fonts sit at the repo root.
const FONTS_DIR = resolve(cwd(), '..', 'fonts');
// Read from disk: vitest stubs CSS imports (even ?raw) to an empty module.
const appCss = readFileSync(resolve(cwd(), 'src', 'styles', 'app.css'), 'utf8');
const EXPECTED_WEIGHT = {
  'Montserrat-Black': '900', 'Bangers-Regular': '400', 'Poppins-Black': '900',
  'Poppins-Medium': '500', 'Anton-Regular': '400',
  // Hook-only (Goal 33): not a karaoke preset font, offered by the hook selector.
  'Montserrat-ExtraBold': '800',
};

// OS/2 usWeightClass of a TrueType file: the weight the @font-face must declare.
function usWeightClass(file) {
  const b = readFileSync(file);
  const tables = b.readUInt16BE(4);
  for (let i = 0; i < tables; i += 1) {
    const rec = 12 + 16 * i;
    if (b.toString('latin1', rec, rec + 4) === 'OS/2') return b.readUInt16BE(b.readUInt32BE(rec + 8) + 4);
  }
  return null;
}

function fontFaces(css) {
  return [...css.matchAll(/@font-face\s*\{([^}]*)\}/g)].map(([, body]) => ({
    family: body.match(/font-family:\s*"([^"]+)"/)?.[1],
    src: body.match(/src:\s*([^;]+)/)?.[1],
    weight: body.match(/font-weight:\s*(\d+)/)?.[1],
    style: body.match(/font-style:\s*(\w+)/)?.[1],
  }));
}

test('every preset declares a bundled font with a known real weight', () => {
  for (const p of SUBTITLE_PRESETS) {
    expect(EXPECTED_WEIGHT, p.id).toHaveProperty([p.font]);
  }
});

test.each(Object.keys(EXPECTED_WEIGHT))('@font-face for %s loads the bundled file at its real weight', (font) => {
  const faces = fontFaces(appCss).filter((f) => f.family === `ClippyMe Preview ${font}`);
  expect(faces).toHaveLength(1);
  const [face] = faces;
  expect(face.src).toBe(`url("/fonts/${font}.ttf") format("truetype")`);
  expect(face.weight).toBe(EXPECTED_WEIGHT[font]);
  expect(face.style).toBe('normal');
  expect(existsSync(resolve(FONTS_DIR, `${font}.ttf`))).toBe(true);
  expect(String(usWeightClass(resolve(FONTS_DIR, `${font}.ttf`)))).toBe(EXPECTED_WEIGHT[font]);
});

test('preview faces never fetch a remote font', () => {
  for (const f of fontFaces(appCss).filter((x) => x.family?.startsWith('ClippyMe Preview '))) {
    expect(f.src).not.toMatch(/https?:|\/\//);
  }
});
