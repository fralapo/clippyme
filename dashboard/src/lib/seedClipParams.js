// Shared seeding of per-clip toggle/hook/subtitle defaults from the global
// pre-selections. Previously duplicated (and subtly diverged!) between
// ResultCard.jsx and BatchPublishModal.jsx — the single-clip path used a
// camelCase `fontSize` key the backend never reads, so a custom font size set
// in the pre-selection panel was silently dropped on download. Centralising it
// here keeps the single-clip and batch paths byte-identical.
//
// The backend (compose.py / subtitles.py) reads `font_size` and
// `words_per_group`, so those are the canonical keys.

export function seedToggles(preselections) {
    return {
        smartcut: !!preselections?.smartcut,
        hook: !!preselections?.hook,
        subtitles: !!preselections?.subtitles,
        logo: !!preselections?.logo,
        grade: !!(preselections?.grade && preselections.grade.preset && preselections.grade.preset !== 'none'),
    };
}

export function seedGradeParams(preselections) {
    return { preset: preselections?.grade?.preset || 'none' };
}

export function seedLogoParams(preselections) {
    const logo = preselections?.logo;
    return {
        position: logo?.position || 'top-right',
        size: logo?.size || 'M',
    };
}

// Instagram-Stories-style hook text style keys (mirror domain/hooks.py
// HOOK_STYLE_DEFAULTS). Forwarded to the compose hook layer.
const HOOK_STYLE_KEYS = ['bg_enabled', 'bg_color', 'bg_opacity', 'text_color', 'outline_width', 'outline_color', 'font'];

export function seedHookParams(clip, preselections) {
    const h = preselections?.hook || {};
    const base = {
        text: clip?.viral_hook_text || clip?.hook_text || '',
        position: h.position || 'top',
        size: h.size || 'S',
        offset_y: 0,
    };
    // Carry any pre-selected style keys through to the per-clip params so the
    // burn reflects the user's banner/colour/outline/font choices.
    for (const k of HOOK_STYLE_KEYS) {
        if (h[k] !== undefined) base[k] = h[k];
    }
    return base;
}

export function seedSubtitleParams(preselections) {
    const subs = preselections?.subtitles;
    const out = {
        preset: subs?.preset || 'classic_white',
        mode: subs?.mode || 'karaoke',
        display_mode: 'word_group',
        highlight_color: null,
        font: subs?.font || 'Montserrat-Black',
        offset_y: subs?.offset_y ?? 0,
        font_color: subs?.font_color || '#FFFFFF',
        position: subs?.position || 'bottom',
        // Horizontal alignment: 'center' (default) or 'left' (a bandiera). No
        // 'right' — the social UI lives down the right edge.
        align: subs?.align || 'center',
        // Karaoke stroke (outline) colour — defaults black; recolourable.
        outline_color: subs?.outline_color || '#000000',
        // Classic-mode stroke + background (passed through to burn_subtitles).
        border_color: subs?.border_color || '#000000',
        border_width: subs?.border_width ?? 2,
        bg_color: subs?.bg_color || '#000000',
        bg_opacity: subs?.bg_opacity ?? 0,
    };
    // uppercase: only forward an EXPLICIT choice. Omitted → the backend honours
    // the preset's own casing (mrbeast_box / minimal_clean are lower-case
    // presets that a hard-coded `true` used to silently force uppercase).
    if (subs?.uppercase !== undefined) out.uppercase = subs.uppercase;
    // Optional karaoke overrides — omitted when unset so the preset default
    // applies instead of a hard-coded value.
    if (subs?.outline_width !== undefined) out.outline_width = subs.outline_width;
    if (subs?.font_size !== undefined) out.font_size = subs.font_size;
    if (subs?.words_per_group !== undefined) out.words_per_group = subs.words_per_group;
    return out;
}
