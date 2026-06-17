import { getApiUrl } from '../config';

async function throwFromResponse(res) {
  const text = await res.text();
  let msg = text;
  try {
    const parsed = JSON.parse(text);
    msg = typeof parsed.detail === 'string' ? parsed.detail : JSON.stringify(parsed.detail);
  } catch {
    // Non-JSON body: fall back to the raw text captured above.
  }
  throw new Error(msg || `HTTP ${res.status}`);
}

export async function pollJob(jobId) {
  const res = await fetch(getApiUrl(`/api/status/${jobId}`));
  if (!res.ok) throw new Error('Status check failed');
  return res.json();
}

/**
 * Normalize the language preselection into an optional backend field.
 * "multi" / undefined / empty → undefined (backend default applies).
 *
 * @param {{ language?: string } | undefined} pre
 * @returns {string | undefined}
 */
function pickLanguage(pre) {
  const lang = (pre?.language || '').trim();
  if (!lang || lang === 'multi' || lang === 'auto') return undefined;
  return lang;
}

/**
 * Submit a single video (URL or uploaded file) for processing.
 *
 * @param {{ type: 'url' | 'file', payload: string | File, instructions?: string, preselections?: { reframe_mode?: string, language?: string } }} data
 * @param {string} apiKey
 * @returns {Promise<{ job_id: string }>}
 */
export async function submitProcessJob(data, apiKey) {
  const headers = { 'X-Gemini-Key': apiKey };
  let body;

  const language = pickLanguage(data.preselections);

  // Forward reframe_mode unconditionally so the backend echoes the user's
  // pre-selection instead of relying on its own default (which could drift).
  const reframeMode = data.preselections?.reframe_mode;
  const aspect = data.preselections?.aspect;
  const noZoom = data.preselections?.no_zoom === true;
  const skipAnalysis = data.preselections?.skip_analysis === true;
  // Per-job Gemini model override (optional). Validated server-side against the
  // gemini- family prefix; omitted → backend uses the global Settings model.
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
    if (data.payload?.size > 2048 * 1024 * 1024) {
      throw new Error('File too large. Max size 2048MB');
    }
    const formData = new FormData();
    formData.append('file', data.payload);
    if (reframeMode) formData.append('reframe_mode', reframeMode);
    if (aspect && aspect !== '9:16') formData.append('aspect', aspect);
    if (language) formData.append('language', language);
    if (noZoom) formData.append('no_zoom', 'true');
    if (skipAnalysis) formData.append('skip_analysis', 'true');
    if (model) formData.append('model', model);
    body = formData;
  }

  const res = await fetch(getApiUrl('/api/process'), { method: 'POST', headers, body });
  if (!res.ok) await throwFromResponse(res);
  return res.json();
}

/**
 * Submit a batch of URLs for processing.
 *
 * @param {{ urls: string[], instructions?: string, preselections?: { reframe_mode?: string, language?: string } }} data
 * @param {string} apiKey
 * @returns {Promise<{ batch_id: string, total: number }>}
 */
export async function submitBatchJob(data, apiKey) {
  const batchBody = { urls: data.urls, instructions: data.instructions };
  if (data.preselections?.reframe_mode) {
    batchBody.reframe_mode = data.preselections.reframe_mode;
  }
  if (data.preselections?.aspect && data.preselections.aspect !== '9:16') {
    batchBody.aspect = data.preselections.aspect;
  }
  const language = pickLanguage(data.preselections);
  if (language) batchBody.language = language;
  if (data.preselections?.no_zoom === true) batchBody.no_zoom = true;
  if (data.preselections?.skip_analysis === true) batchBody.skip_analysis = true;
  if ((data.preselections?.model || '').trim()) batchBody.model = data.preselections.model.trim();
  const res = await fetch(getApiUrl('/api/batch'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Gemini-Key': apiKey },
    body: JSON.stringify(batchBody),
  });
  if (!res.ok) await throwFromResponse(res);
  return res.json();
}
