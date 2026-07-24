
import { getApiUrl } from '../config';
import { apiFetch } from './apiToken';

export async function throwFromResponse(res) {
  const text = await res.text();
  let msg = text;
  try {
    const parsed = JSON.parse(text);
    const detail = parsed?.detail ?? parsed?.message;
    msg = typeof detail === 'string' ? detail : detail ? JSON.stringify(detail) : text;
  } catch {
    // Non-JSON body: use the captured text.
  }
  const error = new Error(msg || `HTTP ${res.status}`);
  error.status = res.status;
  error.retryable = res.status === 408 || res.status === 429 || res.status >= 500;
  throw error;
}

export async function pollJob(jobId, { signal } = {}) {
  const res = await apiFetch(getApiUrl(`/api/status/${encodeURIComponent(jobId)}`), { signal });
  if (!res.ok) await throwFromResponse(res);
  return res.json();
}

function pickLanguage(pre) {
  const lang = (pre?.language || '').trim();
  if (!lang || lang === 'multi' || lang === 'auto') return undefined;
  return lang;
}

export async function submitProcessJob(data, apiKey, { signal } = {}) {
  const headers = { 'X-Gemini-Key': apiKey };
  let body;
  const language = pickLanguage(data.preselections);
  const reframeMode = data.preselections?.reframe_mode;
  const aspect = data.preselections?.aspect;
  const noZoom = data.preselections?.no_zoom === true;
  const skipAnalysis = data.preselections?.skip_analysis === true;
  const model = (data.preselections?.model || '').trim();

  if (data.type === 'url') {
    headers['Content-Type'] = 'application/json';
    const jsonBody = { url: data.payload };
    if (data.instructions) jsonBody.instructions = data.instructions;
    if (reframeMode) jsonBody.reframe_mode = reframeMode;
    if (aspect && aspect !== '9:16') jsonBody.aspect = aspect;
    if (language) jsonBody.language = language;
    if (noZoom) jsonBody.no_zoom = true;
    if (skipAnalysis) jsonBody.skip_analysis = true;
    if (model) jsonBody.model = model;
    body = JSON.stringify(jsonBody);
  } else {
    if (data.payload?.size > 16 * 1024 * 1024 * 1024) throw new Error('File too large. Maximum size is 16 GB.');
    const formData = new FormData();
    formData.append('file', data.payload);
    if (data.instructions) formData.append('instructions', data.instructions);
    if (reframeMode) formData.append('reframe_mode', reframeMode);
    if (aspect && aspect !== '9:16') formData.append('aspect', aspect);
    if (language) formData.append('language', language);
    if (noZoom) formData.append('no_zoom', 'true');
    if (skipAnalysis) formData.append('skip_analysis', 'true');
    if (model) formData.append('model', model);
    body = formData;
  }

  const res = await apiFetch(getApiUrl('/api/process'), { method: 'POST', headers, body, signal });
  if (!res.ok) await throwFromResponse(res);
  return res.json();
}

export async function submitBatchJob(data, apiKey, { signal } = {}) {
  const batchBody = { urls: data.urls, instructions: data.instructions };
  if (data.preselections?.reframe_mode) batchBody.reframe_mode = data.preselections.reframe_mode;
  if (data.preselections?.aspect && data.preselections.aspect !== '9:16') batchBody.aspect = data.preselections.aspect;
  const language = pickLanguage(data.preselections);
  if (language) batchBody.language = language;
  if (data.preselections?.no_zoom === true) batchBody.no_zoom = true;
  if (data.preselections?.skip_analysis === true) batchBody.skip_analysis = true;
  if ((data.preselections?.model || '').trim()) batchBody.model = data.preselections.model.trim();
  const res = await apiFetch(getApiUrl('/api/batch'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Gemini-Key': apiKey },
    body: JSON.stringify(batchBody),
    signal,
  });
  if (!res.ok) await throwFromResponse(res);
  return res.json();
}
