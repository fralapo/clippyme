// Real backend calls the redesign needs beyond api.js (submit/poll). Mirrors
// the exact payloads the production components use, so the redesign talks to
// the same endpoints with the same contracts.
import { getApiUrl } from '../config';

export function clipVideoSrc(clip, bust) {
  const url = clip?.video_url || '';
  const full = url.startsWith('http') ? url : getApiUrl(url);
  return bust ? `${full}${full.includes('?') ? '&' : '?'}v=${bust}` : full;
}

export function downloadClip(clip, index) {
  const a = document.createElement('a');
  a.href = clip.video_url && clip.video_url.startsWith('http')
    ? clip.video_url
    : `${window.location.origin}${clip.video_url || ''}`;
  a.download = `clip_${index + 1}.mp4`;
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
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
  if (!res.ok) throw new Error('Restore failed');
  return res.json(); // { result: { clips, cost_analysis } }
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
    reframe_mode: opts.reframe ? 'auto' : 'disabled',
    language: opts.language,
    no_zoom: !opts.zoom,
    skip_analysis: !opts.detect,
    smartcut: opts.smartcut,
    subtitles: opts.subtitles
      ? { mode: opts.subMode, preset: opts.subPreset, position: opts.subPosition }
      : false,
    hook: opts.hooks ? { position: opts.hookPos, size: opts.hookSize } : false,
  };
}

// Seconds → m:ss for clip duration display.
export function fmtDuration(start, end) {
  const s = Math.max(0, Math.round((end || 0) - (start || 0)));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, '0')}`;
}
