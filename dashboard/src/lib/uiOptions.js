// ClippyMe — shared constants (presets, fonts, languages, pipeline steps).

export const PRESETS = [
  {
    id: 'viral', icon: 'flame', title: 'Viral pack',
    desc: 'Best moments, karaoke subs, hooks & smart-cut.',
    opts: { clips: 7, aspect: '9:16', reframeMode: 'auto', detect: true, smartcut: true, zoom: true,
      subtitles: true, subMode: 'karaoke', subPreset: 'hormozi_bold', hooks: true },
  },
  {
    id: 'talking', icon: 'user-round', title: 'Talking head',
    desc: 'Face-tracked reframe, clean minimal captions.',
    opts: { clips: 5, aspect: '9:16', reframeMode: 'auto', detect: true, smartcut: true, zoom: false,
      subtitles: true, subMode: 'karaoke', subPreset: 'minimal_clean', hooks: false },
  },
  {
    id: 'podcast', icon: 'mic', title: 'Podcast clips',
    desc: 'Long-form cuts, classic subs, no zoom.',
    opts: { clips: 9, aspect: '9:16', reframeMode: 'auto', detect: true, smartcut: true, zoom: false,
      subtitles: true, subMode: 'classic', subPreset: 'classic_white', hooks: true },
  },
];

// Per-job Gemini model quick-picker (Create → Clip Options). '' = use the
// global Settings model. Live discovery lives in Settings; here we keep a small
// curated list so the picker works offline. Mirrors the allow-list prefixes
// (gemini-2.5- / gemini-3) the backend accepts.
export const GEMINI_MODELS = [
  ['', 'Default (Settings)'],
  ['gemini-3.5-flash', '3.5 Flash · recommended'],
  ['gemini-2.5-flash', '2.5 Flash · budget'],
  ['gemini-3.1-pro-preview', '3.1 Pro · max quality'],
  ['gemini-2.5-pro', '2.5 Pro · max quality'],
];

// Classic-mode subtitle fonts. Values are the bundled TTF basenames libass
// resolves from `fonts/` (Verdana falls back to a system face). The backend
// validates the name against `_FONT_NAME_RE` in subtitles.py.
export const SUB_FONTS = [
  ['Montserrat-Black', 'Montserrat Black'],
  ['Anton-Regular', 'Anton'],
  ['Bangers-Regular', 'Bangers'],
  ['Poppins-Black', 'Poppins Black'],
  ['Poppins-Medium', 'Poppins Medium'],
  ['Verdana', 'Verdana'],
];

// Classic-mode subtitle colour swatches (sent as `font_color` hex).
// First three are the ASCENSORE brand colours: white = judges,
// yellow #FDE700 / purple #581BBA = contestants.
export const SUB_COLORS = ['#FFFFFF', '#FDE700', '#581BBA', '#FFE000', '#00FF66', '#00E5FF', '#FF4D6D', '#000000'];

// Brand-logo overlay placement (compose-time layer). Values match the
// _POSITIONS keys in editing/logo.py.
export const LOGO_POSITIONS = [
  ['top-left', 'Top L'], ['top-center', 'Top C'], ['top-right', 'Top R'],
  ['bottom-left', 'Bot L'], ['bottom-center', 'Bot C'], ['bottom-right', 'Bot R'],
  ['center', 'Center'],
];
// Logo size presets → width fraction handled backend-side (_LOGO_SIZE_MAP).
export const LOGO_SIZES = [['S', 'S'], ['M', 'M'], ['L', 'L']];

// Colour-grade looks — ids MUST match backend GRADE_PRESETS keys
// (clippyme/editing/grade.py). 'none' is represented by the Grade toggle being
// off, so it is not offered as a pickable look here.
export const GRADE_PRESETS = [
  { id: 'warm_cinematic', label: 'Warm' },
  { id: 'cool_crisp', label: 'Cool' },
  { id: 'neutral_punch', label: 'Punch' },
  { id: 'vivid_pop', label: 'Vivid' },
];

// Karaoke preset preview faces. Keys are the bundled TTF basenames the backend
// burns with (subtitles.py SUBTITLE_PRESETS `font`); values are each file's real
// weight. styles/app.css declares one @font-face per key, family
// "ClippyMe Preview <key>", loading the same file from the backend's /fonts
// mount (pinned by lib/subtitlePreviewFonts.test.js). The preview-only family
// name keeps these clear of the UI's Google "Anton" and of any other family.
const PREVIEW_FONT_WEIGHTS = {
  'Montserrat-Black': 900,
  'Bangers-Regular': 400,
  'Poppins-Black': 900,
  'Poppins-Medium': 500,
  'Anton-Regular': 400,
  // Hook-only: the backend default face (see HOOK_BACKEND_DEFAULT_FONT).
  'NotoSerif-Bold': 700,
  // Hook-only: bundled file offered through the live font list.
  'Montserrat-ExtraBold': 800,
};

// Font the hook renderer burns when the hook font is empty ("Default (serif)"):
// editing/hook_overlay.py FONT_PATH. Preview-only — the payload keeps '' so the
// backend still picks its own default.
export const HOOK_BACKEND_DEFAULT_FONT = 'NotoSerif-Bold';

// Renderer font ID → bundled preview face ({ fontFamily, fontWeight }), or null
// when no preview face exists (system Verdana, uploaded fonts). Font IDs are
// TTF basenames, not CSS families: "Anton-Regular" alone falls back.
export function bundledPreviewFont(fontId) {
  if (!Object.hasOwn(PREVIEW_FONT_WEIGHTS, fontId)) return null;
  return { fontFamily: `"ClippyMe Preview ${fontId}", sans-serif`, fontWeight: PREVIEW_FONT_WEIGHTS[fontId] };
}

// Curated subtitle fonts the hook renderer cannot load: hook_overlay only opens
// files in fonts/ and the user fonts dir, so a font with no bundled file (system
// Verdana, which only libass/fontconfig resolves) burns as NotoSerif-Bold. Not
// offered for hooks; a saved one stays in state and previews the backend default.
export const HOOK_UNSUPPORTED_FONTS = new Set(
  SUB_FONTS.map(([v]) => v).filter((v) => !bundledPreviewFont(v)),
);

// Hook font selector curation. Offered: every font the hook renderer loads,
// except unsupported ones (above) and HOOK_BACKEND_DEFAULT_FONT, which the
// live font list carries but "Default (serif)" ('') already renders. A saved
// explicit 'NotoSerif-Bold' stays a distinct value and keeps rendering Noto.
export function isHookFontSelectable(fontId) {
  return fontId !== HOOK_BACKEND_DEFAULT_FONT && !HOOK_UNSUPPORTED_FONTS.has(fontId);
}

// Karaoke preset picker. `font` must equal the backend preset font
// (tests/editing/test_subtitle_preset_parity.py); it only drives the preview —
// karaoke payloads never send a font, the backend resolves it from the preset.
export const SUBTITLE_PRESETS = [
  { id: 'classic_white', label: 'Classic', hi: '#FFFF00', font: 'Montserrat-Black', style: { color: '#fff', textShadow: '-1px -1px 0 #000,1px -1px 0 #000,-1px 1px 0 #000,1px 1px 0 #000' } },
  { id: 'hormozi_bold', label: 'Hormozi', hi: '#00FF00', font: 'Bangers-Regular', style: { color: '#fff', textShadow: '-1.5px -1.5px 0 #000,1.5px -1.5px 0 #000,-1.5px 1.5px 0 #000,1.5px 1.5px 0 #000', letterSpacing: '.02em' } },
  { id: 'neon_glow', label: 'Neon', hi: '#00FFFF', font: 'Montserrat-Black', style: { color: '#fff', textShadow: '0 0 4px #0ff,0 0 8px #0ff' } },
  { id: 'mrbeast_box', label: 'MrBeast', hi: '#FFFF00', font: 'Poppins-Black', style: { color: '#fff', background: '#000', padding: '2px 6px', borderRadius: '3px' } },
  { id: 'minimal_clean', label: 'Minimal', hi: '#FFFFFF', font: 'Poppins-Medium', style: { color: '#fff' } },
  { id: 'fire_impact', label: 'Fire', hi: '#FF4444', font: 'Anton-Regular', style: { color: '#fff', textShadow: '0 0 3px #f44,-1px -1px 0 #000,1px 1px 0 #000', letterSpacing: '.03em' } },
].map((p) => ({
  ...p,
  // Explicit real weight: .subpre .prev sets 800, which would faux-bold the
  // 400-only faces (Bangers, Anton) and mis-weight Poppins Medium.
  style: { ...p.style, fontFamily: `"ClippyMe Preview ${p.font}", sans-serif`, fontWeight: PREVIEW_FONT_WEIGHTS[p.font] },
}));

// Instagram-Stories-style hook text defaults. Keys match the backend
// create_hook_image `style` dict (editing/hook_overlay.py:HOOK_STYLE_DEFAULTS).
// Default look = bannerless white Anton with a thin black outline (the
// bannerless path also auto-adds a soft drop shadow for legibility). Users can
// still re-enable the banner / pick any colour or font per clip.
export const HOOK_STYLE_DEFAULT = {
  bg_enabled: false,
  bg_color: '#FFFFFF',
  bg_opacity: 0.94,
  text_color: '#FFFFFF',
  outline_width: 4,
  outline_color: '#000000',
  font: 'Anton-Regular',
  animate: false,
};
// Outline thickness presets → px stroke width.
export const HOOK_OUTLINE = [['0', 'None'], ['4', 'Thin'], ['8', 'Thick']];

export const LANGUAGES = [
  ['multi', 'Multi-language'], ['en', 'English'], ['it', 'Italiano'], ['es', 'Español'],
  ['fr', 'Français'], ['de', 'Deutsch'], ['pt', 'Português'], ['nl', 'Nederlands'],
  ['ja', '日本語'], ['ko', '한국어'], ['zh', '中文'], ['hi', 'हिन्दी'],
];

export const PIPE = [
  { id: 'download', name: 'Download', icon: 'download', meta: 'fetch source' },
  { id: 'transcribe', name: 'Transcribe', icon: 'audio-lines', meta: 'deepgram nova-3' },
  { id: 'detect', name: 'Detect moments', icon: 'sparkles', meta: 'gemini scoring' },
  { id: 'reframe', name: 'Reframe 9:16', icon: 'scan-face', meta: 'face tracking' },
  // Captions/hooks are NOT burned during the main render — they're applied at
  // compose/download time (user-triggered in results). Worded as a roadmap node
  // so the live bar doesn't imply the render is doing caption work right now.
  { id: 'caption', name: 'Caption & hook', icon: 'captions', meta: 'added on export' },
  { id: 'finish', name: 'Finish', icon: 'check', meta: 'render out' },
];

