// Create-flow presets. Manual config is always primary; presets are just a
// quick way to apply a saved bundle of options. Three built-ins ship with the
// app; users can save their own and pick one as the default (auto-applied when
// Create loads). Stored per-browser in localStorage — fits the self-hosted,
// single-user app (no accounts/backend needed).
import { PRESETS as BUILTIN_PRESETS } from './data';

const PRESETS_KEY = 'clippyme_user_presets_v1';
const DEFAULT_KEY = 'clippyme_default_preset_v1';

// The create-options fields a preset captures (everything except the source).
export const PRESET_KEYS = [
  'clipsAuto', 'clips', 'aspect', 'detect', 'reframe', 'smartcut', 'zoom',
  'subtitles', 'subMode', 'subPreset', 'subPosition', 'hooks', 'hookPos', 'hookSize', 'language',
];

export function captureOpts(opts) {
  const o = {};
  for (const k of PRESET_KEYS) if (opts[k] !== undefined) o[k] = opts[k];
  return o;
}

export { BUILTIN_PRESETS };

export function loadUserPresets() {
  try { return JSON.parse(localStorage.getItem(PRESETS_KEY)) || []; } catch { return []; }
}

export function allPresets() {
  return [...BUILTIN_PRESETS, ...loadUserPresets()];
}

export function saveUserPreset(name, opts) {
  const list = loadUserPresets();
  const preset = {
    id: 'u_' + Date.now().toString(36),
    title: (name || 'My preset').slice(0, 40),
    desc: 'Saved preset',
    icon: 'sliders-horizontal',
    user: true,
    opts: captureOpts(opts),
  };
  list.push(preset);
  try { localStorage.setItem(PRESETS_KEY, JSON.stringify(list)); } catch { /* quota */ }
  return preset;
}

export function deleteUserPreset(id) {
  const list = loadUserPresets().filter((p) => p.id !== id);
  try { localStorage.setItem(PRESETS_KEY, JSON.stringify(list)); } catch { /* */ }
  if (getDefaultPresetId() === id) setDefaultPreset(null);
}

export function getDefaultPresetId() {
  try { return localStorage.getItem(DEFAULT_KEY) || null; } catch { return null; }
}

export function setDefaultPreset(id) {
  try {
    if (id) localStorage.setItem(DEFAULT_KEY, id);
    else localStorage.removeItem(DEFAULT_KEY);
  } catch { /* */ }
}

// Options of the default preset (or null) — used to seed Create on load.
export function getDefaultPresetOpts() {
  const id = getDefaultPresetId();
  if (!id) return null;
  const p = allPresets().find((x) => x.id === id);
  return p ? p.opts : null;
}
