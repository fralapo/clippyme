// Pure helper: turn an AI-suggested clip title into a safe download filename.
//
// Sanitized for Windows (and friendly on macOS/Linux): strips the characters
// Windows forbids in filenames (< > : " / \ | ? *) plus control chars,
// collapses whitespace, trims trailing dots/spaces (Windows silently drops
// them), dodges reserved device names, and caps the length. Falls back to
// `clip_N` when the title is empty/unusable. Kept dependency-free here so it is
// host-testable under `node --test` (api/client.js pulls in browser globals).

// Windows-reserved device names — a file named exactly any of these (case-
// insensitive, with or without an extension) is rejected by the OS.
const WIN_RESERVED = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/i;

export function clipDownloadName(clip, index, ext = 'mp4') {
  const raw = (clip && clip.video_title_for_youtube_short) || '';
  let name = String(raw)
    // eslint-disable-next-line no-control-regex -- deliberately strip control chars from filenames
    .replace(/[<>:"/\\|?*\x00-\x1f]/g, ' ') // forbidden + control chars → space
    .replace(/\s+/g, ' ')                    // collapse whitespace
    .trim()
    .replace(/[. ]+$/, '');                  // no trailing dot/space (Windows)
  if (name.length > 120) name = name.slice(0, 120).trim().replace(/[. ]+$/, '');
  if (!name || WIN_RESERVED.test(name)) name = `clip_${(index || 0) + 1}`;
  return `${name}.${ext}`;
}
