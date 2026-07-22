// Pure(ish) share helper for the manual-publish queue. Native Web Share only
// fires when every capability gate holds; anything else returns a tagged
// result so the caller keeps its explicit Copy/Download actions instead of
// silently doing nothing. Never auto-checks "published" — that's the user's
// call after they've actually posted on the target platform.
export async function shareClip({ videoUrl, filename, caption }) {
  if (
    typeof window === 'undefined' || window.isSecureContext !== true
    || typeof navigator === 'undefined'
    || typeof navigator.share !== 'function'
    || typeof navigator.canShare !== 'function'
  ) {
    return { fallback: true };
  }

  let file;
  try {
    const res = await fetch(videoUrl);
    if (!res.ok) return { fallback: true };
    const blob = await res.blob();
    file = new File([blob], filename || 'clip.mp4', { type: 'video/mp4' });
  } catch {
    return { fallback: true };
  }

  if (!navigator.canShare({ files: [file] })) return { fallback: true };

  try {
    await navigator.share({ files: [file], text: caption || '' });
    return { shared: true };
  } catch (err) {
    if (err && err.name === 'AbortError') return { cancelled: true };
    return { fallback: true };
  }
}
