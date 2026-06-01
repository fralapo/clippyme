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
    };
}

export function seedHookParams(clip, preselections) {
    return {
        text: clip?.viral_hook_text || clip?.hook_text || '',
        position: preselections?.hook?.position || 'top',
        size: preselections?.hook?.size || 'S',
        offset_y: 0,
    };
}

export function seedSubtitleParams(preselections) {
    const subs = preselections?.subtitles;
    return {
        preset: subs?.preset || 'classic_white',
        mode: subs?.mode || 'karaoke',
        display_mode: 'word_group',
        highlight_color: null,
        font: subs?.font || 'Montserrat-Black',
        uppercase: true,
        offset_y: 0,
        font_color: subs?.font_color || '#FFFFFF',
        position: subs?.position || 'bottom',
        // Classic-mode stroke + background (passed through to burn_subtitles).
        border_color: subs?.border_color || '#000000',
        border_width: subs?.border_width ?? 2,
        bg_color: subs?.bg_color || '#000000',
        bg_opacity: subs?.bg_opacity ?? 0,
        // Optional custom size / grouping — keys omitted when unset so the
        // backend preset default applies instead of a hard-coded value.
        ...(subs?.font_size !== undefined ? { font_size: subs.font_size } : {}),
        ...(subs?.words_per_group !== undefined ? { words_per_group: subs.words_per_group } : {}),
    };
}
