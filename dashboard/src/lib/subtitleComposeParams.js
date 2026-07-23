// Translates a SubtitleControls value ({ mode, preset, font, font_color,
// outline_color, font_size, border_width, bg, position, align, offset_y })
// into the vocabulary compose.py's `_apply_subtitles` actually reads.
// Karaoke mode already speaks SubtitleControls' vocabulary 1:1. Classic mode
// does NOT: the backend reads `border_color` (not `outline_color`) and
// `bg_opacity`/`bg_color` (not the boolean `bg`) — see compose.py ~318-343.
// Every call site that feeds a SubtitleControls value into a compose payload
// must translate through here (captions.jsx / realApi.js do the same
// mapping inline for their own differently-shaped option objects).
export function toComposeSubtitleParams(v) {
  const base = { mode: v.mode, preset: v.preset, position: v.position, align: v.align, offset_y: v.offset_y };
  if (v.mode === 'karaoke') {
    return {
      ...base,
      font_color: v.font_color,
      outline_color: v.outline_color,
      ...(v.font_size > 0 ? { font_size: v.font_size } : {}),
    };
  }
  return {
    ...base,
    font: v.font,
    font_color: v.font_color,
    border_width: v.border_width,
    border_color: v.outline_color,
    bg_opacity: v.bg ? 0.6 : 0,
    bg_color: '#000000',
  };
}

// Reverse of toComposeSubtitleParams: seed a SubtitleControls value from a
// persisted compose.subtitle_params (backend vocabulary) layered onto
// `defaults` (a full SubtitleControls value, e.g. SUB_DEFAULTS). Used to
// prefill the monitor Settings drawer from status().config — never sent back
// verbatim, only as UI seed (apply() still re-translates through
// toComposeSubtitleParams).
export function fromComposeSubtitleParams(params, defaults) {
  if (!params) return defaults;
  const out = { ...defaults };
  for (const key of ['mode', 'preset', 'position', 'align', 'offset_y', 'font', 'font_color', 'font_size', 'border_width']) {
    if (params[key] !== undefined) out[key] = params[key];
  }
  if (params.border_color !== undefined) out.outline_color = params.border_color;
  else if (params.outline_color !== undefined) out.outline_color = params.outline_color;
  if (params.bg_opacity !== undefined) out.bg = params.bg_opacity > 0;
  return out;
}
