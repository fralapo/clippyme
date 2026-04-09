import { getApiUrl } from '../config';

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

  if (data.type === 'url') {
    headers['Content-Type'] = 'application/json';
    const jsonBody = { url: data.payload };
    if (data.instructions) jsonBody.instructions = data.instructions;
    if (reframeMode) jsonBody.reframe_mode = reframeMode;
    if (language) jsonBody.language = language;
    body = JSON.stringify(jsonBody);
  } else {
    const formData = new FormData();
    formData.append('file', data.payload);
    if (reframeMode) formData.append('reframe_mode', reframeMode);
    if (language) formData.append('language', language);
    body = formData;
  }

  const res = await fetch(getApiUrl('/api/process'), { method: 'POST', headers, body });
  if (!res.ok) throw new Error(await res.text());
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
  const language = pickLanguage(data.preselections);
  if (language) batchBody.language = language;
  const res = await fetch(getApiUrl('/api/batch'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Gemini-Key': apiKey },
    body: JSON.stringify(batchBody),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
