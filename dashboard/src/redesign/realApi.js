// Real backend calls the redesign needs beyond api.js (submit/poll). Mirrors
// the exact payloads the production components use, so the redesign talks to
// the same endpoints with the same contracts.
import { getApiUrl } from '../config';
import { seedToggles, seedHookParams, seedSubtitleParams, seedLogoParams } from '../lib/seedClipParams';
import { clipDownloadName } from '../lib/clipFilename';

export { clipDownloadName };

// Only http/https absolute URLs are honoured as-is; anything else (javascript:,
// data:, blob:, or a bare "httpfoo:" that slips past a startsWith check) is
// treated as a relative path and resolved against our own backend. This stops
// a malicious/compromised API response from injecting a scheme that executes
// when set as an <a href> / <video src>.
function safeResolveUrl(url) {
  const raw = url || '';
  try {
    const u = new URL(raw, window.location.origin);
    if (u.protocol === 'http:' || u.protocol === 'https:') {
      // Absolute http(s) → keep; relative → getApiUrl maps to backend.
      return /^https?:\/\//i.test(raw) ? raw : getApiUrl(raw);
    }
  } catch { /* fall through to backend-relative */ }
  return getApiUrl(raw);
}

export function clipVideoSrc(clip, bust) {
  const full = safeResolveUrl(clip?.video_url || '');
  return bust ? `${full}${full.includes('?') ? '&' : '?'}v=${bust}` : full;
}

// Source for the clip preview, honouring an applied edit. After "Apply &
// reprocess": if layers were composed, a `previewUrl` (a separate composed
// file) takes priority; otherwise we fall back to the raw/reframed clip with
// the reframe cache-buster so a re-reframed clip re-fetches.
export function clipPreviewSrc(clip, state) {
  if (state?.previewUrl) {
    const full = safeResolveUrl(state.previewUrl);
    const b = state.previewBust;
    return b ? `${full}${full.includes('?') ? '&' : '?'}v=${b}` : full;
  }
  return clipVideoSrc(clip, state?.reframeBust);
}

export function downloadClip(clip, index) {
  const a = document.createElement('a');
  a.href = safeResolveUrl(clip.video_url || '');
  a.download = clipDownloadName(clip, index);
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

export async function cancelJob(jobId) {
  try { await fetch(getApiUrl(`/api/cancel/${jobId}`), { method: 'POST' }); } catch { /* best-effort */ }
}

// Suspend the job's process tree (status → paused). Resumable.
export async function pauseJob(jobId) {
  const res = await fetch(getApiUrl(`/api/pause/${jobId}`), { method: 'POST' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json().catch(() => ({}));
}

// Resume a paused job (status → processing).
export async function resumeJob(jobId) {
  const res = await fetch(getApiUrl(`/api/resume/${jobId}`), { method: 'POST' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json().catch(() => ({}));
}

// Graceful stop: kill the subprocess but KEEP the clips finished so far
// (status → stopped). Unlike cancelJob, which hard-discards all output.
export async function stopJob(jobId) {
  const res = await fetch(getApiUrl(`/api/stop/${jobId}`), { method: 'POST' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json().catch(() => ({}));
}

export async function composeClip(jobId, index, { toggles, hook_params, subtitle_params, logo_params, grade_params, drop_ranges }) {
  const res = await fetch(getApiUrl(`/api/compose/${jobId}/${index}`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ toggles, hook_params, subtitle_params, logo_params, grade_params: grade_params || {}, drop_ranges: drop_ranges || [] }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json(); // { composed_url }
}

// Conversational trim: a plain-English instruction → Gemini → spans to cut
// (clip-relative seconds). Returns { drop_ranges: [[s,e],...], explanation }.
export async function editClipAI(jobId, index, instruction, model) {
  const res = await fetch(getApiUrl(`/api/edit-ai/${jobId}/${index}`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ instruction, ...(model ? { model } : {}) }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// Per-clip transcript segments (clip-relative seconds) for the manual-trim UI.
// Returns { segments: [{index, text, start, end}], duration, language }.
export async function getClipTranscript(jobId, index) {
  const res = await fetch(getApiUrl(`/api/transcript/${jobId}/${index}`));
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// Download a clip, composing first (subtitles/hook/smart-cut) when any toggle
// is active for it, otherwise grabbing the raw clip. Shared by the per-clip
// download button and bulk export. Returns 'composed' | 'raw'.
export async function exportClip(jobId, index, clip, state, preselections) {
  const toggles = state?.toggles ?? seedToggles(preselections);
  const any = Object.values(toggles || {}).some(Boolean);
  if (!any) { downloadClip(clip, index); return 'raw'; }
  const hook = state?.hookParams ?? seedHookParams(clip, preselections);
  const subs = state?.subtitleParams ?? seedSubtitleParams(preselections);
  const logo = state?.logoParams ?? seedLogoParams(preselections);
  const grade = state?.gradeParams ?? { preset: preselections?.grade?.preset || 'none' };
  const { composed_url } = await composeClip(jobId, index, {
    toggles,
    hook_params: toggles.hook ? hook : {},
    subtitle_params: toggles.subtitles ? subs : {},
    logo_params: toggles.logo ? logo : {},
    grade_params: toggles.grade ? grade : {},
    drop_ranges: toggles.smartcut ? (state?.dropRanges || []) : [],
  });
  const href = safeResolveUrl(composed_url);
  const a = document.createElement('a');
  a.href = href; a.download = clipDownloadName(clip, index); a.style.display = 'none';
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  return 'composed';
}

export async function reframeClip(jobId, index, mode) {
  const res = await fetch(getApiUrl(`/api/reframe/${jobId}/${index}`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reframe_mode: mode }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const e = new Error(err.detail || `HTTP ${res.status}`);
    e.status = res.status;
    throw e;
  }
  return res.json(); // { success, new_video_url }
}

export async function publishClip(jobId, index, body) {
  const res = await fetch(getApiUrl(`/api/publish/${jobId}/${index}`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const e = new Error((err.detail || `HTTP ${res.status}`).toString());
    e.status = res.status;
    throw e;
  }
  return res.json().catch(() => ({}));
}

export async function restoreJob(jobId) {
  const res = await fetch(getApiUrl(`/api/history/${jobId}/restore`), { method: 'POST' });
  if (!res.ok) { const e = new Error('Restore failed'); e.status = res.status; throw e; }
  return res.json(); // { result: { clips, cost_analysis } }
}

// Jobs that actually exist on disk right now. The History list is driven by
// localStorage (survives rebuilds), but the clip files live in output/ — a
// docker rebuild/cleanup can wipe them while the localStorage entry lingers.
// Cross-checking against this set lets the UI flag entries that can no longer
// be opened instead of failing silently on click. Returns a Set of jobIds;
// empty Set on any error (treated as "unknown" → don't disable anything).
export async function listBackendJobIds() {
  try {
    const res = await fetch(getApiUrl('/api/history'));
    if (!res.ok) return null;
    const data = await res.json();
    return new Set((data.jobs || []).map((j) => j.jobId).filter(Boolean));
  } catch { return null; }
}

// --- config / settings ----------------------------------------------------

export async function getConfig() {
  const res = await fetch(getApiUrl('/api/config'));
  if (!res.ok) return {};
  return res.json();
}

export async function saveConfig(keys) {
  const res = await fetch(getApiUrl('/api/config'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keys }),
  });
  if (!res.ok) throw new Error('Save config failed');
  return res.json().catch(() => ({}));
}

export async function getModels(apiKey) {
  const res = await fetch(getApiUrl('/api/config/models'), { headers: { 'X-Gemini-Key': apiKey } });
  if (!res.ok) return { models: [] };
  return res.json();
}

export async function cookiesStatus() {
  const res = await fetch(getApiUrl('/api/config/cookies/status'));
  if (!res.ok) return { configured: false };
  return res.json();
}

export async function uploadCookies(file) {
  const fd = new FormData();
  fd.append('cookies_file', file);
  const res = await fetch(getApiUrl('/api/config/cookies'), { method: 'POST', body: fd });
  if (!res.ok) throw new Error('Cookie upload failed');
  return res.json().catch(() => ({}));
}

export async function deleteCookies() {
  const res = await fetch(getApiUrl('/api/config/cookies'), { method: 'DELETE' });
  if (!res.ok) throw new Error('Cookie remove failed');
  return res.json().catch(() => ({}));
}

// --- Custom fonts (e.g. licensed Stratos) ---------------------------------
export async function listFonts() {
  const res = await fetch(getApiUrl('/api/config/fonts'));
  if (!res.ok) return { fonts: [] };
  return res.json();
}

export async function uploadFont(file) {
  const fd = new FormData();
  fd.append('font_file', file);
  const res = await fetch(getApiUrl('/api/config/fonts'), { method: 'POST', body: fd });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Font upload failed'); }
  return res.json().catch(() => ({}));
}

export async function deleteFont(name) {
  const res = await fetch(getApiUrl(`/api/config/fonts/${encodeURIComponent(name)}`), { method: 'DELETE' });
  if (!res.ok) throw new Error('Font remove failed');
  return res.json().catch(() => ({}));
}

// --- Brand logo / watermark ------------------------------------------------
export async function logoStatus() {
  const res = await fetch(getApiUrl('/api/config/logo/status'));
  if (!res.ok) return { configured: false };
  return res.json();
}

export async function uploadLogo(file) {
  const fd = new FormData();
  fd.append('logo_file', file);
  const res = await fetch(getApiUrl('/api/config/logo'), { method: 'POST', body: fd });
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || 'Logo upload failed'); }
  return res.json().catch(() => ({}));
}

export async function deleteLogo() {
  const res = await fetch(getApiUrl('/api/config/logo'), { method: 'DELETE' });
  if (!res.ok) throw new Error('Logo remove failed');
  return res.json().catch(() => ({}));
}

export async function getZernio() {
  const res = await fetch(getApiUrl('/api/config/zernio'));
  if (!res.ok) return { configured: false };
  return res.json();
}

export async function saveZernio(payload) {
  const res = await fetch(getApiUrl('/api/config/zernio'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('Save Zernio failed');
  return res.json().catch(() => ({}));
}

export async function discoverZernioAccounts() {
  const res = await fetch(getApiUrl('/api/zernio/accounts'));
  if (!res.ok) throw new Error('Discover failed');
  return res.json();
}

// Map the redesign's flat `opts` into the preselections shape the existing
// hooks + seedClipParams expect (subtitles/hook as truthy objects).
export function optsToPreselections(opts) {
  return {
    // Tri-state reframe mode. Fall back to the legacy boolean (`reframe`) for
    // any persisted preselections saved before the 3-mode selector landed.
    // 'object' is the legacy name for 'subject' (FrameShift face-first); the
    // backend accepts both but normalize here so new jobs persist the new name.
    reframe_mode: (opts.reframeMode === 'object' ? 'subject' : opts.reframeMode) || (opts.reframe === false ? 'disabled' : 'auto'),
    aspect: opts.aspect || '9:16',
    language: opts.language,
    no_zoom: !opts.zoom,
    skip_analysis: !opts.detect,
    smartcut: opts.smartcut,
    // Per-job Gemini model override (quick-picker). Omitted when blank →
    // lib/api.js skips the field and the backend uses the Settings default.
    model: (opts.model || '').trim() || undefined,
    subtitles: opts.subtitles
      ? {
          mode: opts.subMode, preset: opts.subPreset, position: opts.subPosition || 'bottom',
          // Horizontal alignment applies to both modes ('center' | 'left').
          align: opts.subAlign || 'center',
          // Vertical nudge applies to both modes.
          offset_y: opts.subOffsetY || 0,
          // Karaoke font-size override (0 = Auto → use the preset size; omitted
          // so seedSubtitleParams doesn't force a value) + text/stroke colours
          // (stroke defaults black; both recolourable per preset).
          ...(opts.subMode === 'karaoke'
            ? {
                font_color: opts.subColor || '#FFFFFF',
                outline_color: opts.subStroke || '#000000',
                ...(opts.subFontSize > 0 ? { font_size: opts.subFontSize } : {}),
              }
            : {}),
          // Classic-mode typography (karaoke draws style from the preset, so
          // these are only meaningful for classic).
          ...(opts.subMode === 'classic'
            ? {
                font: opts.subFont || 'Montserrat-Black',
                font_color: opts.subColor || '#FFFFFF',
                border_width: opts.subOutlineW ?? 2,
                bg_opacity: opts.subBg ? 0.6 : 0,
                bg_color: '#000000',
              }
            : {}),
        }
      : false,
    hook: opts.hooks ? { position: opts.hookPos, size: opts.hookSize, ...(opts.hookStyle || {}) } : false,
    // Logo overlay is a compose-time layer (not a process-time arg) — persisted
    // here only so each generated clip inherits the toggle + placement default.
    logo: opts.logo ? { position: opts.logoPos || 'top-right', size: opts.logoSize || 'M' } : false,
    // Colour grade default for every generated clip (compose-time layer). Off
    // ('none') → omitted so seedToggles leaves the grade toggle off.
    grade: opts.gradePreset && opts.gradePreset !== 'none' ? { preset: opts.gradePreset } : false,
  };
}

// Seconds → m:ss for clip duration display.
export function fmtDuration(start, end) {
  const s = Math.max(0, Math.round((end || 0) - (start || 0)));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, '0')}`;
}
