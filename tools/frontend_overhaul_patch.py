from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(rel, content):
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def replace_once(rel, old, new):
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected block not found in {rel}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


write("dashboard/src/lib/storage.js", r'''
const STORAGE_BY_KIND = {
  local: () => globalThis.localStorage,
  session: () => globalThis.sessionStorage,
};

function resolveStorage(kind = 'local') {
  try {
    return STORAGE_BY_KIND[kind]?.() || null;
  } catch {
    return null;
  }
}

export function readStoredJson(key, fallback, { kind = 'local', validate } = {}) {
  const storage = resolveStorage(kind);
  if (!storage) return fallback;
  try {
    const raw = storage.getItem(key);
    if (raw == null) return fallback;
    const parsed = JSON.parse(raw);
    return !validate || validate(parsed) ? parsed : fallback;
  } catch {
    return fallback;
  }
}

export function writeStoredJson(key, value, { kind = 'local' } = {}) {
  const storage = resolveStorage(kind);
  if (!storage) return false;
  try {
    storage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

export function removeStoredValue(key, { kind = 'local' } = {}) {
  const storage = resolveStorage(kind);
  if (!storage) return false;
  try {
    storage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

export function subscribeStoredJson(key, listener, { kind = 'local', validate } = {}) {
  if (typeof window === 'undefined' || typeof window.addEventListener !== 'function') return () => {};
  const onStorage = (event) => {
    if (event.storageArea !== resolveStorage(kind) || event.key !== key) return;
    if (event.newValue == null) {
      listener(null);
      return;
    }
    try {
      const value = JSON.parse(event.newValue);
      if (!validate || validate(value)) listener(value);
    } catch {
      // Ignore corrupt writes from another tab.
    }
  };
  window.addEventListener('storage', onStorage);
  return () => window.removeEventListener('storage', onStorage);
}
''')

write("dashboard/src/lib/createValidation.js", r'''
const MAX_BATCH_ITEMS = 20;
const MAX_FILE_BYTES = 16 * 1024 * 1024 * 1024;
const VIDEO_EXTENSIONS = /\.(mp4|mov|webm|mkv|m4v|avi)$/i;

const ALLOWED_HOSTS = new Set([
  'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com',
  'youtu.be', 'www.youtu.be', 'youtube-nocookie.com', 'www.youtube-nocookie.com',
  'twitch.tv', 'www.twitch.tv', 'm.twitch.tv', 'clips.twitch.tv',
  'kick.com', 'www.kick.com',
]);

function validateUrl(value) {
  const raw = String(value || '').trim();
  if (!raw) return 'Add a video URL.';
  let url;
  try { url = new URL(raw); } catch { return 'Enter a valid absolute URL.'; }
  if (url.protocol !== 'https:') return 'Use an HTTPS URL.';
  if (url.username || url.password || url.port) return 'The URL cannot contain credentials or a custom port.';
  if (!ALLOWED_HOSTS.has(url.hostname.toLowerCase())) return 'Supported sources are YouTube, Twitch, and Kick.';
  return null;
}

function validateFile(file) {
  if (!file) return 'Choose a video file.';
  if (Number(file.size) > MAX_FILE_BYTES) return 'The file exceeds the 16 GB server limit.';
  const name = String(file.name || '');
  if (file.type && !String(file.type).startsWith('video/') && !VIDEO_EXTENSIONS.test(name)) {
    return 'Choose a supported video file.';
  }
  return null;
}

export function validateCreateOptions(opts = {}) {
  const errors = [];
  const mode = opts.mode === 'batch' ? 'batch' : 'single';
  let sourceCount = 0;
  let urls = [];

  if (mode === 'single') {
    sourceCount = 1;
    if (opts.source === 'file') {
      const error = validateFile(opts.file);
      if (error) errors.push(error);
    } else {
      const error = validateUrl(opts.url);
      if (error) errors.push(error);
      else urls = [String(opts.url).trim()];
    }
  } else {
    const rawUrls = String(opts.batch || '').split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    const seen = new Set();
    urls = rawUrls.filter((url) => {
      if (seen.has(url)) return false;
      seen.add(url);
      return true;
    });
    const files = Array.isArray(opts.batchFiles) ? opts.batchFiles : [];
    sourceCount = urls.length + files.length;
    if (!sourceCount) errors.push('Add at least one URL or video file.');
    if (sourceCount > MAX_BATCH_ITEMS) errors.push(`A batch can contain at most ${MAX_BATCH_ITEMS} sources.`);
    urls.forEach((url, index) => {
      const error = validateUrl(url);
      if (error) errors.push(`URL ${index + 1}: ${error}`);
    });
    files.forEach((file, index) => {
      const error = validateFile(file);
      if (error) errors.push(`File ${index + 1}: ${error}`);
    });
  }

  return {
    valid: errors.length === 0,
    errors,
    firstError: errors[0] || '',
    sourceCount,
    urls,
  };
}

export { MAX_BATCH_ITEMS, MAX_FILE_BYTES };
''')

write("dashboard/src/redesign/AppErrorBoundary.jsx", r'''
import { Component } from 'react';
import { Btn, Icon } from './primitives';
import { clearPersistedSession } from '../hooks/useSessionPersistence';

export class AppErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('ClippyMe frontend crashed', error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="fatal-shell" role="alert">
        <div className="fatal-card">
          <span className="fatal-icon"><Icon n="triangle-alert" /></span>
          <p className="eyebrow">Frontend recovery</p>
          <h1>ClippyMe hit an unexpected UI error.</h1>
          <p>Your rendered files and backend jobs are untouched. Reload the interface, or clear only the saved browser session if the same screen keeps crashing.</p>
          <div className="fatal-actions">
            <Btn variant="grad" icon="refresh-cw" onClick={() => window.location.reload()}>Reload interface</Btn>
            <Btn variant="secondary" icon="trash-2" onClick={() => { clearPersistedSession(); window.location.reload(); }}>Clear saved session</Btn>
          </div>
          <details>
            <summary>Technical details</summary>
            <pre>{String(this.state.error?.message || this.state.error)}</pre>
          </details>
        </div>
      </main>
    );
  }
}
''')

write("dashboard/src/redesign/LazyVideo.jsx", r'''
import { forwardRef, useEffect, useRef, useState } from 'react';

export const LazyVideo = forwardRef(function LazyVideo({ src, rootMargin = '320px', className, style, ...props }, forwardedRef) {
  const localRef = useRef(null);
  const [active, setActive] = useState(false);

  useEffect(() => {
    const node = localRef.current;
    if (!node || !src) return undefined;
    if (typeof IntersectionObserver === 'undefined') {
      setActive(true);
      return undefined;
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        setActive(true);
        observer.disconnect();
      }
    }, { rootMargin });
    observer.observe(node);
    return () => observer.disconnect();
  }, [rootMargin, src]);

  const assignRef = (node) => {
    localRef.current = node;
    if (typeof forwardedRef === 'function') forwardedRef(node);
    else if (forwardedRef) forwardedRef.current = node;
  };

  return (
    <video
      {...props}
      ref={assignRef}
      className={className}
      style={style}
      src={active ? src : undefined}
      data-src={active ? undefined : src}
      preload={active ? (props.preload || 'metadata') : 'none'}
    />
  );
});
''')

write("dashboard/src/lib/api.js", r'''
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
''')

write("dashboard/src/hooks/useJobPolling.js", r'''
import { useEffect, useRef } from 'react';
import { pollJob } from '../lib/api';
import { detectPipelineStep } from '../lib/pipelineStep';

const BASE_DELAY = 2000;
const MAX_DELAY = 30000;

export function useJobPolling({
  jobId,
  isActive,
  onResult,
  onCompleted,
  onStopped,
  onCancelled,
  onFailed,
  onProgress,
  onPaused,
  onConnectionChange,
}) {
  const callbacks = useRef({});
  callbacks.current = { onResult, onCompleted, onStopped, onCancelled, onFailed, onProgress, onPaused, onConnectionChange };

  useEffect(() => {
    if (!isActive || !jobId) return undefined;

    let disposed = false;
    let timer = null;
    let controller = null;
    let consecutiveErrors = 0;
    let disconnectedAnnounced = false;

    const schedule = (delay) => {
      if (!disposed) timer = setTimeout(tick, delay);
    };

    const terminal = (callback, data) => {
      disposed = true;
      callback?.(data);
    };

    const tick = async () => {
      controller = new AbortController();
      try {
        const data = await pollJob(jobId, { signal: controller.signal });
        if (disposed) return;
        consecutiveErrors = 0;
        if (disconnectedAnnounced) callbacks.current.onConnectionChange?.(true);
        disconnectedAnnounced = false;

        if (data.result) callbacks.current.onResult?.(data.result);
        if (data.status === 'completed') return terminal(callbacks.current.onCompleted, data);
        if (data.status === 'stopped') return terminal(callbacks.current.onStopped || callbacks.current.onCompleted, data);
        if (data.status === 'cancelled') return terminal(callbacks.current.onCancelled);
        if (data.status === 'failed') {
          const errorMsg = data.error || data.logs?.at?.(-1) || 'Process failed';
          return terminal(callbacks.current.onFailed, errorMsg);
        }
        if (data.status === 'paused') callbacks.current.onPaused?.(data);
        if (Array.isArray(data.logs)) callbacks.current.onProgress?.(data.logs, data.operations?.stage || detectPipelineStep(data.logs));
        schedule(typeof document !== 'undefined' && document.hidden ? 10000 : BASE_DELAY);
      } catch (error) {
        if (disposed || error?.name === 'AbortError') return;
        consecutiveErrors += 1;
        if (consecutiveErrors >= 3 && !disconnectedAnnounced) {
          disconnectedAnnounced = true;
          callbacks.current.onConnectionChange?.(false, error);
        }
        // A network outage is not a pipeline failure. Keep the durable backend
        // job alive and retry with a ceiling instead of changing its status.
        schedule(Math.min(BASE_DELAY * 2 ** consecutiveErrors, MAX_DELAY));
      }
    };

    tick();
    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
      controller?.abort();
    };
  }, [isActive, jobId]);
}
''')

write("dashboard/src/hooks/useLiveMonitorStatus.js", r'''
import { useCallback, useEffect, useRef, useState } from 'react';
import { getLiveMonitorStatus } from '../redesign/realApi';

export function useLiveMonitorStatus(intervalMs = 5000) {
  const [monitors, setMonitors] = useState([]);
  const [meta, setMeta] = useState({ loading: true, error: null, updatedAt: null });
  const timerRef = useRef(null);
  const controllerRef = useRef(null);
  const mountedRef = useRef(false);

  const refresh = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    try {
      const data = await getLiveMonitorStatus({ signal: controller.signal });
      if (!mountedRef.current) return;
      setMonitors(Array.isArray(data?.monitors) ? data.monitors : []);
      setMeta({ loading: false, error: null, updatedAt: Date.now() });
    } catch (error) {
      if (!mountedRef.current || error?.name === 'AbortError') return;
      setMeta((current) => ({ ...current, loading: false, error }));
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    let disposed = false;
    const tick = async () => {
      await refresh();
      if (!disposed) timerRef.current = setTimeout(tick, typeof document !== 'undefined' && document.hidden ? intervalMs * 3 : intervalMs);
    };
    tick();
    return () => {
      disposed = true;
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
      controllerRef.current?.abort();
    };
  }, [intervalMs, refresh]);

  return [monitors, refresh, meta];
}
''')

write("dashboard/src/hooks/useBackendStatus.js", r'''
import { useCallback, useEffect, useRef, useState } from 'react';
import { getApiUrl } from '../config';
import { apiFetch } from '../lib/apiToken';

export function useBackendStatus() {
  const [hfTokenSet, setHfTokenSet] = useState(true);
  const [cookiesConfigured, setCookiesConfigured] = useState(false);
  const [state, setState] = useState({ loading: true, reachable: true, error: null, updatedAt: null });
  const controllerRef = useRef(null);

  const refresh = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setState((current) => ({ ...current, loading: true }));
    try {
      const [configRes, cookiesRes] = await Promise.all([
        apiFetch(getApiUrl('/api/config'), { signal: controller.signal }),
        apiFetch(getApiUrl('/api/config/cookies/status'), { signal: controller.signal }),
      ]);
      if (!configRes.ok || !cookiesRes.ok) throw new Error('Backend status request failed');
      const [config, cookies] = await Promise.all([configRes.json(), cookiesRes.json()]);
      setHfTokenSet(!!config.HF_TOKEN);
      setCookiesConfigured(!!cookies.configured);
      setState({ loading: false, reachable: true, error: null, updatedAt: Date.now() });
    } catch (error) {
      if (error?.name === 'AbortError') return;
      setState({ loading: false, reachable: false, error, updatedAt: Date.now() });
    }
  }, []);

  useEffect(() => {
    refresh();
    return () => controllerRef.current?.abort();
  }, [refresh]);

  return { hfTokenSet, setHfTokenSet, cookiesConfigured, setCookiesConfigured, ...state, refresh };
}
''')

write("dashboard/src/hooks/useHistory.js", r'''
import { useCallback, useEffect, useState } from 'react';
import { HISTORY_KEY, HISTORY_MAX_ITEMS } from '../lib/constants';
import { readStoredJson, removeStoredValue, subscribeStoredJson, writeStoredJson } from '../lib/storage';

const validHistory = (value) => Array.isArray(value);
const normalize = (value) => (Array.isArray(value) ? value.filter((entry) => entry && typeof entry.jobId === 'string') : []);

export function useHistory() {
  const [history, setHistoryState] = useState(() => normalize(readStoredJson(HISTORY_KEY, [], { validate: validHistory })));

  useEffect(() => subscribeStoredJson(HISTORY_KEY, (value) => setHistoryState(normalize(value)), { validate: validHistory }), []);

  const replaceHistory = useCallback((next) => {
    const value = normalize(typeof next === 'function' ? next(history) : next).slice(0, HISTORY_MAX_ITEMS);
    setHistoryState(value);
    writeStoredJson(HISTORY_KEY, value);
  }, [history]);

  const saveToHistory = useCallback((entry) => {
    if (!entry?.jobId) return;
    setHistoryState((previous) => {
      const updated = [entry, ...previous.filter((item) => item.jobId !== entry.jobId)].slice(0, HISTORY_MAX_ITEMS);
      writeStoredJson(HISTORY_KEY, updated);
      return updated;
    });
  }, []);

  const purgeJobStorage = useCallback((jobId) => {
    removeStoredValue(`clippyme_clip_states_${jobId}`);
    removeStoredValue(`clippyme_preselections_job_${jobId}`);
  }, []);

  const deleteFromHistory = useCallback((jobId) => {
    setHistoryState((previous) => {
      const updated = previous.filter((entry) => entry.jobId !== jobId);
      writeStoredJson(HISTORY_KEY, updated);
      return updated;
    });
    purgeJobStorage(jobId);
  }, [purgeJobStorage]);

  const clearHistory = useCallback(() => {
    setHistoryState((previous) => {
      previous.forEach((entry) => entry?.jobId && purgeJobStorage(entry.jobId));
      return [];
    });
    removeStoredValue(HISTORY_KEY);
  }, [purgeJobStorage]);

  return { history, setHistory: replaceHistory, saveToHistory, deleteFromHistory, clearHistory };
}
''')

write("dashboard/src/hooks/useClipStates.js", r'''
import { useCallback, useEffect, useState } from 'react';
import { readStoredJson, removeStoredValue, subscribeStoredJson, writeStoredJson } from '../lib/storage';

const validStates = (value) => value && typeof value === 'object' && !Array.isArray(value);

function keyFor(jobId) { return `clippyme_clip_states_${jobId}`; }

function normalize(value) {
  if (!validStates(value)) return {};
  const next = {};
  for (const [key, state] of Object.entries(value)) {
    if (!/^\d+$/.test(key) || !state || typeof state !== 'object') continue;
    next[key] = state.processing ? { ...state, processing: false } : state;
  }
  return next;
}

export function useClipStates(jobId) {
  const [states, setStates] = useState({});

  useEffect(() => {
    if (!jobId) { setStates({}); return undefined; }
    const key = keyFor(jobId);
    setStates(normalize(readStoredJson(key, {}, { validate: validStates })));
    return subscribeStoredJson(key, (value) => setStates(normalize(value)), { validate: validStates });
  }, [jobId]);

  const updateClip = useCallback((index, patch) => {
    if (!Number.isInteger(Number(index)) || !patch || typeof patch !== 'object') return;
    setStates((previous) => {
      const next = { ...previous, [index]: { ...(previous[index] || {}), ...patch } };
      if (jobId) writeStoredJson(keyFor(jobId), next);
      return next;
    });
  }, [jobId]);

  const getClipState = useCallback((index) => states[index] || {}, [states]);
  const reset = useCallback(() => {
    setStates({});
    if (jobId) removeStoredValue(keyFor(jobId));
  }, [jobId]);

  return { states, updateClip, getClipState, reset };
}
''')

write("dashboard/src/hooks/useSessionPersistence.js", r'''
import { useEffect } from 'react';
import { SESSION_KEY } from '../lib/constants';
import { readStoredJson, removeStoredValue, writeStoredJson } from '../lib/storage';

const MAX_SESSION_AGE_MS = 7 * 24 * 60 * 60 * 1000;
const VALID_STATUSES = new Set(['processing', 'complete', 'error']);

export function clearPersistedSession() {
  removeStoredValue(SESSION_KEY);
}

export function loadPersistedSession() {
  const value = readStoredJson(SESSION_KEY, null);
  if (!value || typeof value !== 'object' || !value.jobId || !VALID_STATUSES.has(value.status)) return null;
  if (!Number.isFinite(value.timestamp) || Date.now() - value.timestamp > MAX_SESSION_AGE_MS) {
    clearPersistedSession();
    return null;
  }
  if (value.status === 'complete' && !value.results) return null;
  return {
    jobId: value.jobId,
    status: value.status,
    results: value.results || null,
    processingMedia: value.processingMedia || null,
    activeTab: value.status === 'processing' || value.status === 'complete' ? 'create' : (value.activeTab || 'create'),
    preselections: value.preselections || null,
  };
}

export function useSessionPersistence({ status, jobId, results, processingMedia, activeTab, preselections }) {
  useEffect(() => {
    if (status === 'idle' || !jobId) {
      clearPersistedSession();
      return;
    }
    const safeMedia = processingMedia?.type === 'url' || processingMedia?.type === 'batch'
      ? processingMedia
      : processingMedia?.payload?.name
        ? { type: 'file', payload: { name: processingMedia.payload.name } }
        : null;
    const payload = {
      jobId,
      status,
      results: status === 'complete' ? results : (results ? { clips: results.clips || [], operations: results.operations } : null),
      processingMedia: safeMedia,
      activeTab,
      preselections: preselections || null,
      timestamp: Date.now(),
    };
    if (!writeStoredJson(SESSION_KEY, payload) && payload.results) {
      writeStoredJson(SESSION_KEY, { ...payload, results: { clips: payload.results.clips || [] } });
    }
  }, [jobId, status, results, activeTab, processingMedia, preselections]);
}
''')

write("dashboard/src/redesign/primitives.jsx", r'''
import { useId, useRef } from 'react';
import { Icon, Social } from './icon';

export { Icon, Social };

export function Btn({ variant = 'secondary', size, block, icon, iconRight, children, loading = false, disabled, type = 'button', className = '', ...props }) {
  const classes = ['btn', `btn-${variant}`, size && `btn-${size}`, block && 'btn-block', className].filter(Boolean).join(' ');
  return (
    <button {...props} type={type} className={classes} disabled={disabled || loading} aria-busy={loading || undefined}>
      {(loading || icon) && <Icon n={loading ? 'loader' : icon} />}
      <span>{children}</span>
      {!loading && iconRight && <Icon n={iconRight} />}
    </button>
  );
}

export function Badge({ tone = 'out', icon, children, className = '', ...props }) {
  return <span {...props} className={`badge badge-${tone}${className ? ` ${className}` : ''}`}>{icon && <Icon n={icon} />}{children}</span>;
}

export function Switch({ on, onChange, disabled, label = 'Toggle option', ...props }) {
  return (
    <button {...props} type="button" role="switch" aria-checked={!!on} aria-label={label} disabled={disabled}
      className={`sw${on ? ' on' : ''}`} onClick={(event) => { event.stopPropagation(); onChange?.(!on); }}>
      <i aria-hidden="true" />
    </button>
  );
}

export function Segmented({ options, value, onChange, full, blue, label = 'Choose an option' }) {
  const refs = useRef([]);
  const move = (event, index) => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    const direction = event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 1;
    const next = (index + direction + options.length) % options.length;
    onChange(options[next].id);
    refs.current[next]?.focus();
  };
  return (
    <div className={`seg${full ? ' full' : ''}${blue ? ' blue' : ''}`} role="radiogroup" aria-label={label}>
      {options.map((option, index) => (
        <button key={option.id} ref={(node) => { refs.current[index] = node; }} type="button" role="radio"
          aria-checked={value === option.id} tabIndex={value === option.id || (!options.some((item) => item.id === value) && index === 0) ? 0 : -1}
          className={value === option.id ? 'on' : ''} onClick={() => onChange(option.id)} onKeyDown={(event) => move(event, index)}>
          {option.icon && <Icon n={option.icon} />}{option.label}
        </button>
      ))}
    </div>
  );
}

export function Stepper({ value, set, min = 1, max = 12, label = 'Value' }) {
  return (
    <div className="stepper" role="group" aria-label={label}>
      <button type="button" disabled={value <= min} onClick={() => set(Math.max(min, value - 1))} aria-label={`Decrease ${label}`}>–</button>
      <output aria-live="polite">{value}</output>
      <button type="button" disabled={value >= max} onClick={() => set(Math.min(max, value + 1))} aria-label={`Increase ${label}`}>+</button>
    </div>
  );
}

export function Panel({ title, sub, icon, headRight, pad = true, children, className, style, as: Tag = 'section' }) {
  const titleId = useId();
  return (
    <Tag className={`panel${className ? ` ${className}` : ''}`} style={style} aria-labelledby={title ? titleId : undefined}>
      {title && (
        <div className="panel-head">
          {icon && <div className="ico" aria-hidden="true"><Icon n={icon} /></div>}
          <div><h3 id={titleId}>{title}</h3>{sub && <div className="sub">{sub}</div>}</div>
          {headRight && <div className="right">{headRight}</div>}
        </div>
      )}
      <div className={pad ? 'panel-pad' : ''}>{children}</div>
    </Tag>
  );
}

export const PLATFORMS = [
  { id: 'tiktok', icon: 'tiktok', label: 'TikTok' },
  { id: 'ig', icon: 'instagram', label: 'Reels' },
  { id: 'yt', icon: 'youtube', label: 'Shorts' },
];

export function PlatPill({ id, icon, label, on, onClick }) {
  return (
    <button type="button" className={`plat${on ? ` on ${id}` : ''}`} aria-pressed={!!on} onClick={onClick}>
      <Social n={icon} color={on ? 'white' : '7E7E8F'} />{label}
    </button>
  );
}
''')

write("dashboard/src/redesign/chrome.jsx", r'''
import { useEffect, useState } from 'react';
import { Icon } from './icon';
import logoMark from './logo-mark.png';

const TABS = [
  { id: 'create', label: 'Create', icon: 'wand-sparkles' },
  { id: 'live', label: 'Live Monitor', icon: 'rss' },
  { id: 'history', label: 'History', icon: 'clock' },
  { id: 'settings', label: 'Settings', icon: 'settings' },
];

function useBrowserOnline() {
  const [online, setOnline] = useState(() => typeof navigator === 'undefined' || navigator.onLine !== false);
  useEffect(() => {
    const update = () => setOnline(navigator.onLine !== false);
    window.addEventListener('online', update);
    window.addEventListener('offline', update);
    return () => { window.removeEventListener('online', update); window.removeEventListener('offline', update); };
  }, []);
  return online;
}

export function TopNav({ tab, setTab, busy }) {
  const online = useBrowserOnline();
  const status = !online ? 'Offline' : busy ? 'Working' : 'Local';
  return (
    <header className="topnav">
      <div className="brand" aria-label="ClippyMe home">
        <img src={logoMark} alt="" aria-hidden="true" />
        <span>Clippy<span className="me">Me</span></span>
      </div>
      <nav className="tabs" aria-label="Primary navigation">
        {TABS.map((item) => (
          <button key={item.id} type="button" className={`tab${tab === item.id ? ' active' : ''}`}
            aria-current={tab === item.id ? 'page' : undefined} onClick={() => setTab(item.id)}>
            <Icon n={item.icon} /><span className="lbl">{item.label}</span>
          </button>
        ))}
      </nav>
      <div className="nav-right">
        <span className={`status-dot${online ? '' : ' offline'}`} role="status" aria-live="polite">
          <i aria-hidden="true" style={busy && online ? { background: 'var(--brand-blue)', boxShadow: '0 0 0 3px rgba(10,129,217,.16)' } : null} />
          <span className="sd-lbl">{status}</span>
        </span>
        <div className="avatar" aria-hidden="true">CM</div>
      </div>
    </header>
  );
}

export function Hero({ eyebrow, line1, grad, sub }) {
  return (
    <div className="hero">
      {eyebrow && <div className="eyebrow"><i aria-hidden="true" />{eyebrow}</div>}
      <h1>{line1}{grad && <> <span className="grad">{grad}</span></>}</h1>
      {sub && <p>{sub}</p>}
    </div>
  );
}
''')

write("dashboard/src/redesign/results.jsx", r'''
import { memo, useCallback, useMemo, useState } from 'react';
import { Icon, Btn, Badge } from './primitives';
import { LazyVideo } from './LazyVideo';
import { clipPreviewSrc, fmtDuration, downloadClip, exportClip } from './realApi';

const REFRAME_ICON = { auto: 'crop', subject: 'scan-face', object: 'scan-face', disabled: 'square' };
const REFRAME_LABEL = { auto: 'Auto', subject: 'Subject', object: 'Subject', disabled: 'Off' };
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const ClipCard = memo(function ClipCard({ clip, index, jobId, state, preselections, onUpdate, onEdit, onApplyToAll, selectMode, onPublish, pushToast }) {
  const [downloading, setDownloading] = useState(false);
  const selected = state?.selected !== false;
  const score = Math.round(clip.viral_score || 0);
  const mode = state?.reframeMode || clip.reframe_mode || 'auto';
  const title = clip.video_title_for_youtube_short || `Clip ${index + 1}`;
  const processing = !!state?.processing;

  const doDownload = async (event) => {
    event.stopPropagation();
    if (downloading || processing) return;
    setDownloading(true);
    try {
      const kind = await exportClip(jobId, index, clip, state, preselections);
      pushToast?.('success', kind === 'composed' ? 'Composed clip downloaded' : 'Clip downloaded');
    } catch {
      pushToast?.('warn', 'Compose failed; downloading the raw clip instead');
      downloadClip(clip, index);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <article className={`clip${score >= 90 ? ' top' : ''}${selectMode && selected ? ' sel' : ''}`}
      role={selectMode ? 'checkbox' : undefined} tabIndex={selectMode ? 0 : undefined} aria-checked={selectMode ? selected : undefined}
      onClick={() => selectMode && onUpdate(index, { selected: !selected })}
      onKeyDown={(event) => { if (selectMode && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); onUpdate(index, { selected: !selected }); } }}>
      <div className="clip-media" style={{ padding: 0, background: '#000' }}>
        <LazyVideo src={clipPreviewSrc(clip, state)} controls={!selectMode} playsInline muted={selectMode}
          aria-label={`Preview ${title}`} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', zIndex: 0 }} />
        <div className="clip-top" style={{ padding: 10 }}>
          <span className="score"><Icon n="flame" />{score}</span>
          {selectMode ? <span className="clip-check" aria-hidden="true"><Icon n="check" /></span>
            : <span className="rf-badge" title={`Reframe: ${REFRAME_LABEL[mode] || mode}`}><Icon n={REFRAME_ICON[mode] || 'crop'} />{REFRAME_LABEL[mode] || 'Auto'}</span>}
        </div>
        <div className="clip-bottom" style={{ padding: 10 }}>
          {state?.publishedAt && <span className="clip-pub"><Icon n="check" />published</span>}
          <span className="dur" style={{ marginLeft: state?.publishedAt ? 8 : 0 }}>{fmtDuration(clip.start, clip.end)}</span>
        </div>
        {processing && <div className="clip-busy" role="status"><Icon n="loader" /><span>Reprocessing…</span></div>}
      </div>
      {!selectMode && (
        <button type="button" className="clip-edit" disabled={processing} onClick={(event) => { event.stopPropagation(); onEdit(clip, index); }}
          aria-label={`Edit and reprocess ${title}`}><Icon n={processing ? 'loader' : 'sliders-horizontal'} />{processing ? 'Reprocessing…' : 'Edit & reprocess'}</button>
      )}
      <div className="clip-foot">
        <span className="ttl" title={title}>{title}</span>
        {!selectMode && <button type="button" className="mini" title="Apply these settings to all clips" aria-label="Apply settings to all clips" disabled={processing}
          onClick={(event) => { event.stopPropagation(); if (!processing && window.confirm("Apply this clip's settings to every other clip? Manual trim and per-clip hook text are not copied.")) onApplyToAll(index); }}><Icon n="copy" /></button>}
        <button type="button" className="mini" title="Download with edits" aria-label={`Download ${title}`} disabled={downloading || processing} onClick={doDownload}><Icon n={downloading ? 'loader' : 'download'} /></button>
        <button type="button" className="mini" title="Publish" aria-label={`Publish ${title}`} disabled={processing} onClick={(event) => { event.stopPropagation(); onPublish({ ...clip, _idx: index, _apiIdx: clip.original_index ?? index }); }}><Icon n="send" /></button>
        <button type="button" className="mini" title="Remove from grid" aria-label={`Remove ${title}`} onClick={(event) => {
          event.stopPropagation();
          if (window.confirm('Remove this clip from the grid? The file stays on disk.')) { onUpdate(index, { deleted: true }); pushToast?.('info', 'Clip removed'); }
        }}><Icon n="trash-2" /></button>
      </div>
    </article>
  );
});

export function ResultsView({ clips, jobId, preselections, clipStates = {}, onUpdateClipState,
  doneIn, onBack, onPublish, onPublishAll, onEdit, onApplyToAll, onEditSelected, embedded, pushToast }) {
  const [selectMode, setSelectMode] = useState(false);
  const [exporting, setExporting] = useState(false);
  const visible = useMemo(() => clips.map((clip, index) => ({ c: clip, i: index })).filter(({ i }) => !clipStates[i]?.deleted), [clips, clipStates]);
  const selected = useMemo(() => visible.filter(({ i }) => clipStates[i]?.selected !== false), [visible, clipStates]);
  const topScore = useMemo(() => visible.length ? Math.max(...visible.map(({ c }) => Math.round(c.viral_score || 0))) : 0, [visible]);
  const allSelected = visible.length > 0 && selected.length === visible.length;

  const setSelectedAll = useCallback((value) => visible.forEach(({ i }) => onUpdateClipState(i, { selected: value })), [visible, onUpdateClipState]);
  const publishMany = useCallback((list) => onPublishAll(list.map(({ c, i }) => ({ ...c, _idx: i, _apiIdx: c.original_index ?? i }))), [onPublishAll]);
  const exportMany = async (list) => {
    if (exporting || !list.length) return;
    setExporting(true);
    let composed = 0;
    let rawFallback = 0;
    try {
      for (const { c, i } of list) {
        try { await exportClip(jobId, i, c, clipStates[i], preselections); composed += 1; }
        catch { downloadClip(c, i); rawFallback += 1; }
        await delay(150);
      }
      pushToast?.(rawFallback ? 'warn' : 'success', rawFallback
        ? `Exported ${list.length} clips; ${rawFallback} used the raw fallback`
        : `Exported ${composed}/${list.length} clips`);
    } finally { setExporting(false); }
  };

  return (
    <main className="container fade-in">
      <div className="results-head">
        {!embedded && <Btn variant="icon" icon="arrow-left" onClick={onBack} title="Start over" aria-label="Start over" />}
        <h2>{visible.length} clips ready</h2>
        {doneIn && <Badge tone="teal" icon="check">done in {doneIn}</Badge>}
        <div className="rh-right">
          <Btn variant="secondary" size="sm" icon={selectMode ? 'x' : 'check-square'} onClick={() => setSelectMode((current) => {
            if (!current) visible.forEach(({ i }) => onUpdateClipState(i, { selected: false }));
            return !current;
          })}>{selectMode ? 'Cancel' : 'Select'}</Btn>
          {!selectMode && <Btn variant="secondary" size="sm" icon="download" loading={exporting} disabled={!visible.length} onClick={() => exportMany(visible)}>{exporting ? 'Exporting…' : 'Export all'}</Btn>}
          {!selectMode && <Btn variant="grad" size="sm" icon="send" disabled={!visible.length} onClick={() => publishMany(visible)}>Publish all</Btn>}
        </div>
      </div>
      <div className="results-sub">Sorted by virality score · top moment {topScore}</div>

      {selectMode && <div className="actionbar" role="toolbar" aria-label="Selected clip actions">
        <span className="sel-n" aria-live="polite">{selected.length} selected</span>
        <Btn variant="ghost" size="sm" icon="check-check" onClick={() => setSelectedAll(!allSelected)}>{allSelected ? 'Deselect all' : 'Select all'}</Btn>
        <div className="ab-right">
          <Btn variant="secondary" size="sm" icon="sliders-horizontal" disabled={!selected.length} onClick={() => onEditSelected(selected)}>Edit {selected.length || ''}</Btn>
          <Btn variant="secondary" size="sm" icon="download" loading={exporting} disabled={!selected.length} onClick={() => exportMany(selected)}>{exporting ? 'Exporting…' : 'Export'}</Btn>
          <Btn variant="grad" size="sm" icon="send" disabled={!selected.length} onClick={() => publishMany(selected)}>Publish {selected.length || ''}</Btn>
        </div>
      </div>}

      {visible.length ? <div className="results-grid" role="list" aria-label="Generated clips">
        {visible.map(({ c, i }) => <ClipCard key={c.original_index ?? i} clip={c} index={i} jobId={jobId} state={clipStates[i]}
          preselections={preselections} onUpdate={onUpdateClipState} selectMode={selectMode} onPublish={onPublish}
          onEdit={onEdit} onApplyToAll={onApplyToAll} pushToast={pushToast} />)}
      </div> : <div className="empty" role="status"><div className="ei"><Icon n="film" /></div><h3>No visible clips</h3><p>All clips were removed from this view. Start over to generate a new set.</p></div>}
    </main>
  );
}
''')

write("dashboard/src/redesign/processing.jsx", r'''
import { useEffect, useMemo, useRef } from 'react';
import { Icon, Btn, Badge, Panel } from './primitives';
import { LazyVideo } from './LazyVideo';
import { Hero } from './chrome';
import { PIPE } from './data';
import { pipelineStepMeta } from '../lib/pipelineStep';
import { clipVideoSrc, fmtDuration } from './realApi';
import { latestRuntimeTelemetry, formatEta, formatMetric } from '../lib/runtimeTelemetry';

const STEP_INFO = {
  queued: { pct: 5, idx: 0 }, acquiring: { pct: 12, idx: 0 }, downloading: { pct: 18, idx: 0 },
  preflight: { pct: 22, idx: 0 }, transcribing: { pct: 38, idx: 1 }, analyzing: { pct: 58, idx: 2 },
  cutting: { pct: 68, idx: 3 }, reframing: { pct: 82, idx: 3 }, quality: { pct: 93, idx: 4 },
  finalizing: { pct: 97, idx: 4 }, processing: { pct: 80, idx: 3 },
};

function MiniClip({ clip }) {
  return <div className="clip fade-in" style={{ cursor: 'default' }}><div className="clip-media" style={{ padding: 0, background: '#000' }}>
    <LazyVideo src={clipVideoSrc(clip)} muted playsInline aria-label="Verified clip preview"
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }} />
    <div className="clip-top" style={{ padding: 8 }}><span className="score">{Math.round(clip.viral_score || 0)}</span></div>
    <div className="clip-bottom" style={{ padding: 8 }}><span className="dur">{fmtDuration(clip.start, clip.end)}</span></div>
  </div></div>;
}

function Metric({ label, value, hint }) {
  return <div className="operation-metric"><div className="label">{label}</div><div className="operation-value">{value}</div>{hint && <div className="operation-hint">{hint}</div>}</div>;
}

function Operations({ runtime, preflight }) {
  if (!runtime && !preflight) return null;
  return <section className="operations" aria-label="Job operations">
    <div className="stream-head"><h3>Operations</h3>{runtime?.stage && <Badge tone="out">{runtime.stage}</Badge>}</div>
    <div className="operation-grid">
      <Metric label="attempt" value={runtime?.attempt || '—'} hint="bounded retry" />
      <Metric label="verified clips" value={runtime?.clips || '0/0'} hint="QA passed" />
      <Metric label="ETA" value={formatEta(runtime?.eta_s)} hint="live estimate" />
      <Metric label="CPU" value={formatMetric(runtime?.cpu, '%')} />
      <Metric label="job RAM" value={formatMetric(runtime?.rss_mb, ' MB')} />
      <Metric label="disk free" value={formatMetric(runtime?.disk_free_gb, ' GB')} />
    </div>
    {preflight && <div className="operation-grid operation-grid-secondary">
      <Metric label="planned clips" value={formatMetric(preflight.clips)} />
      <Metric label="estimated time" value={formatEta(Number(preflight.runtime_min) * 60)} />
      <Metric label="peak disk" value={formatMetric(preflight.disk_gb, ' GB')} />
      <Metric label="Gemini estimate" value={Number.isFinite(Number(preflight.cost_usd)) ? `$${Number(preflight.cost_usd).toFixed(4)}` : '—'} hint="upper-bound estimate" />
    </div>}
  </section>;
}

export function ProcessingView({ media, status, logs = [], step, clips = [], onCancel, onRetry,
  paused = false, onPause, onResume, onStop, opts = {} }) {
  const logRef = useRef(null);
  const followTail = useRef(true);
  useEffect(() => {
    const node = logRef.current;
    if (node && followTail.current) node.scrollTop = node.scrollHeight;
  }, [logs]);

  const { runtime, preflight } = useMemo(() => latestRuntimeTelemetry(logs), [logs]);
  const visibleLogs = useMemo(() => logs.filter((line) => !String(line).startsWith('[runtime]') && !String(line).startsWith('[preflight]')), [logs]);
  const failed = status === 'error';
  const effectiveStep = runtime?.stage || step;
  const info = STEP_INFO[effectiveStep] || STEP_INFO.queued;
  const reportedProgress = Number(runtime?.progress);
  const pct = failed ? 100 : Number.isFinite(reportedProgress) ? Math.min(100, Math.max(0, reportedProgress)) : Math.min(96, info.pct + Math.min(18, clips.length * 3));
  const activeIdx = clips.length > 0 ? Math.max(info.idx, 4) : info.idx;
  const sourceLabel = media?.type === 'url' ? media.payload : (media?.payload?.name || media?.payload || 'your video');
  const words = { queued: 'queued', acquiring: 'fetching', downloading: 'fetching', preflight: 'checking capacity', transcribing: 'transcribing', analyzing: 'scoring', cutting: 'cutting', reframing: 'rendering', quality: 'verifying', finalizing: 'finalizing', processing: 'rendering', completed: 'complete' };
  const phase = failed ? 'failed' : paused ? 'paused' : (words[effectiveStep] || (clips.length > 0 ? 'rendering' : 'working'));
  const metaOverride = pipelineStepMeta(logs, { ...opts, mediaType: media?.type });

  return <main className="container fade-in">
    <Hero eyebrow={failed ? 'Pipeline error' : paused ? 'Pipeline paused' : 'Pipeline running'} line1={failed ? 'Something broke.' : paused ? 'Work is paused.' : 'Cutting your clips.'}
      sub={failed ? 'Check the log below, then retry or start over.' : 'Every phase is checkpointed. Verified clips appear immediately, and retries resume from durable work.'} />
    <div className="proc">
      <aside className="proc-aside"><Panel><div className="pipe">
        {PIPE.map((pipelineStep, index) => {
          const done = !failed && index < activeIdx;
          const active = !failed && index === activeIdx;
          return <div key={pipelineStep.id} className={`pstep${done ? ' done' : active ? ' active' : ''}`} aria-current={active ? 'step' : undefined}>
            <div className="rail"><div className="pdot"><Icon n={done ? 'check' : pipelineStep.icon} /></div>{index < PIPE.length - 1 && <div className="pseg-v" />}</div>
            <div className="pbody"><div className="pname">{pipelineStep.id === 'reframe' ? `Reframe ${opts.aspect || '9:16'}` : pipelineStep.name}</div>
              <div className="pmeta">{active ? `${metaOverride[pipelineStep.id] || pipelineStep.meta} …` : done ? 'done' : (metaOverride[pipelineStep.id] || pipelineStep.meta)}</div></div>
          </div>;
        })}
      </div></Panel></aside>
      <div><Panel>
        <div className="pbar-wrap" role="progressbar" aria-label={`Pipeline ${phase}`} aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round(pct)}>
          <div className="pbar"><i style={{ width: `${pct}%`, background: failed ? 'var(--danger)' : undefined }} /></div><div className="pbar-pct">{phase}</div>
        </div>
        <div className="processing-toolbar"><span className="label"><span className="mono">src ·</span> {String(sourceLabel).slice(0, 46)}</span>
          <span className="processing-actions">
            {failed && <Btn variant="secondary" size="sm" icon="wand-sparkles" onClick={onRetry}>Retry</Btn>}
            {!failed && onPause && (paused ? <Btn variant="secondary" size="sm" icon="play" onClick={onResume}>Resume</Btn> : <Btn variant="ghost" size="sm" icon="clock" onClick={onPause}>Pause</Btn>)}
            {!failed && onStop && clips.length > 0 && <Btn variant="secondary" size="sm" icon="check-square" onClick={onStop}>Stop & keep</Btn>}
            <Btn variant="ghost" size="sm" icon="x" onClick={onCancel}>{failed ? 'Start over' : 'Discard'}</Btn>
          </span>
        </div>
        <Operations runtime={runtime} preflight={preflight} />
        <div className="log" ref={logRef} role="log" aria-live="polite" aria-relevant="additions"
          onScroll={(event) => { const node = event.currentTarget; followTail.current = node.scrollHeight - node.scrollTop - node.clientHeight < 48; }}>
          {visibleLogs.length === 0 && <div className="ln"><span>waiting for the worker…</span></div>}
          {visibleLogs.map((line, index) => <div key={`${index}-${line}`} className="ln"><span className={/✓|done|complete|found/i.test(line) ? 'ok' : ''} style={/error/i.test(line) ? { color: 'var(--danger)' } : undefined}>{line}</span></div>)}
          {!failed && <div aria-hidden="true"><span className="cursor" /></div>}
        </div>
      </Panel>
      <div className="stream-head"><h3>Clips</h3>{clips.length > 0 ? <Badge tone="teal" icon="check">{clips.length} ready</Badge> : <Badge tone="out">{failed ? 'no clips' : 'finding moments…'}</Badge>}</div>
      <div className="stream">{clips.slice(0, 8).map((clip, index) => <MiniClip key={clip.original_index ?? index} clip={clip} />)}
        {!failed && clips.length < 4 && Array.from({ length: 4 - clips.length }).map((_, index) => <div key={`slot${index}`} className="slot">{index === 0 ? <div className="sk" /> : null}</div>)}</div>
      </div>
    </div>
  </main>;
}
''')

write("dashboard/src/lib/storage.test.js", r'''
import { beforeEach, expect, test, vi } from 'vitest';
import { readStoredJson, removeStoredValue, writeStoredJson } from './storage';

beforeEach(() => localStorage.clear());

test('round-trips JSON and validates the shape', () => {
  expect(writeStoredJson('x', { ok: true })).toBe(true);
  expect(readStoredJson('x', null, { validate: (value) => value.ok === true })).toEqual({ ok: true });
  expect(readStoredJson('x', 'fallback', { validate: () => false })).toBe('fallback');
});

test('corrupt JSON and storage failures degrade to fallback', () => {
  localStorage.setItem('x', '{bad');
  expect(readStoredJson('x', [])).toEqual([]);
  const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota'); });
  expect(writeStoredJson('y', {})).toBe(false);
  spy.mockRestore();
});

test('removes a stored value', () => {
  localStorage.setItem('x', '1');
  expect(removeStoredValue('x')).toBe(true);
  expect(localStorage.getItem('x')).toBeNull();
});
''')

write("dashboard/src/lib/createValidation.test.js", r'''
import { expect, test } from 'vitest';
import { validateCreateOptions } from './createValidation';

test('accepts official HTTPS video sources', () => {
  for (const url of ['https://youtu.be/abc', 'https://www.youtube.com/watch?v=abc', 'https://twitch.tv/user', 'https://kick.com/user']) {
    expect(validateCreateOptions({ mode: 'single', source: 'url', url }).valid).toBe(true);
  }
});

test('rejects unsupported hosts, credentials and non-HTTPS URLs', () => {
  expect(validateCreateOptions({ mode: 'single', source: 'url', url: 'https://vimeo.com/1' }).valid).toBe(false);
  expect(validateCreateOptions({ mode: 'single', source: 'url', url: 'http://youtube.com/watch?v=1' }).valid).toBe(false);
  expect(validateCreateOptions({ mode: 'single', source: 'url', url: 'https://u:p@youtube.com/watch?v=1' }).valid).toBe(false);
});

test('deduplicates batch URLs and enforces the 20 source limit', () => {
  const duplicate = validateCreateOptions({ mode: 'batch', batch: 'https://youtu.be/a\nhttps://youtu.be/a', batchFiles: [] });
  expect(duplicate.valid).toBe(true);
  expect(duplicate.sourceCount).toBe(1);
  const tooMany = validateCreateOptions({ mode: 'batch', batch: Array.from({ length: 21 }, (_, i) => `https://youtu.be/${i}`).join('\n'), batchFiles: [] });
  expect(tooMany.firstError).toMatch(/at most 20/);
});

test('validates uploaded file size', () => {
  expect(validateCreateOptions({ mode: 'single', source: 'file', file: { name: 'x.mp4', type: 'video/mp4', size: 10 } }).valid).toBe(true);
  expect(validateCreateOptions({ mode: 'single', source: 'file', file: { name: 'x.mp4', type: 'video/mp4', size: 17 * 1024 ** 3 } }).valid).toBe(false);
});
''')

write("dashboard/src/hooks/useJobPolling.test.jsx", r'''
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

vi.mock('../lib/api', () => ({ pollJob: vi.fn() }));
import { pollJob } from '../lib/api';
import { useJobPolling } from './useJobPolling';

beforeEach(() => { vi.useFakeTimers(); vi.clearAllMocks(); });
afterEach(() => vi.useRealTimers());

function mount(overrides = {}) {
  const callbacks = {
    onResult: vi.fn(), onCompleted: vi.fn(), onStopped: vi.fn(), onCancelled: vi.fn(),
    onFailed: vi.fn(), onProgress: vi.fn(), onConnectionChange: vi.fn(), ...overrides,
  };
  const hook = renderHook(() => useJobPolling({ jobId: 'j', isActive: true, ...callbacks }));
  return { ...hook, callbacks };
}

test('polls immediately and completes once', async () => {
  pollJob.mockResolvedValue({ status: 'completed', result: { clips: [] } });
  const { callbacks } = mount();
  await act(async () => {});
  expect(pollJob).toHaveBeenCalledTimes(1);
  expect(callbacks.onCompleted).toHaveBeenCalledTimes(1);
  expect(vi.getTimerCount()).toBe(0);
});

test('network errors do not falsely mark a durable job as failed', async () => {
  pollJob.mockRejectedValue(new Error('offline'));
  const { callbacks, unmount } = mount();
  await act(() => vi.advanceTimersByTimeAsync(20_000));
  expect(callbacks.onFailed).not.toHaveBeenCalled();
  expect(callbacks.onConnectionChange).toHaveBeenCalledWith(false, expect.any(Error));
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});

test('aborts an in-flight request on unmount', async () => {
  let signal;
  pollJob.mockImplementation((_id, options) => { signal = options.signal; return new Promise(() => {}); });
  const { unmount } = mount();
  await act(async () => {});
  expect(signal.aborted).toBe(false);
  unmount();
  expect(signal.aborted).toBe(true);
});
''')

write("dashboard/src/redesign/LazyVideo.test.jsx", r'''
import { render } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import { LazyVideo } from './LazyVideo';

afterEach(() => { delete globalThis.IntersectionObserver; });

test('defers the src until the video approaches the viewport', () => {
  let callback;
  globalThis.IntersectionObserver = vi.fn((cb) => { callback = cb; return { observe: vi.fn(), disconnect: vi.fn() }; });
  const { container } = render(<LazyVideo src="/clip.mp4" />);
  const video = container.querySelector('video');
  expect(video.getAttribute('src')).toBeNull();
  callback([{ isIntersecting: true }]);
  expect(video.getAttribute('src')).toBe('/clip.mp4');
});

test('loads immediately when IntersectionObserver is unavailable', () => {
  const { container } = render(<LazyVideo src="/clip.mp4" />);
  expect(container.querySelector('video').getAttribute('src')).toBe('/clip.mp4');
});
''')

write("dashboard/src/redesign/primitives.test.jsx", r'''
import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { Btn, Segmented, Switch } from './primitives';

test('button exposes loading state and blocks duplicate action', () => {
  const onClick = vi.fn();
  render(<Btn loading onClick={onClick}>Save</Btn>);
  const button = screen.getByRole('button', { name: 'Save' });
  expect(button).toBeDisabled();
  expect(button).toHaveAttribute('aria-busy', 'true');
});

test('switch has native switch semantics', () => {
  const onChange = vi.fn();
  render(<Switch on={false} onChange={onChange} label="Subtitles" />);
  fireEvent.click(screen.getByRole('switch', { name: 'Subtitles' }));
  expect(onChange).toHaveBeenCalledWith(true);
});

test('segmented control supports arrow-key selection', () => {
  const onChange = vi.fn();
  render(<Segmented value="a" onChange={onChange} options={[{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }]} />);
  fireEvent.keyDown(screen.getByRole('radio', { name: 'A' }), { key: 'ArrowRight' });
  expect(onChange).toHaveBeenCalledWith('b');
});
''')

write("dashboard/src/hooks/useSessionPersistence.test.jsx", r'''
import { act, renderHook } from '@testing-library/react';
import { beforeEach, expect, test } from 'vitest';
import { SESSION_KEY } from '../lib/constants';
import { clearPersistedSession, loadPersistedSession, useSessionPersistence } from './useSessionPersistence';

beforeEach(() => localStorage.clear());

test('persists and restores an active URL job', () => {
  renderHook(() => useSessionPersistence({ status: 'processing', jobId: 'j', results: null, processingMedia: { type: 'url', payload: 'https://youtu.be/a' }, activeTab: 'create', preselections: { aspect: '9:16' } }));
  expect(loadPersistedSession()).toMatchObject({ jobId: 'j', status: 'processing', activeTab: 'create' });
});

test('idle clears the saved session', () => {
  localStorage.setItem(SESSION_KEY, JSON.stringify({ jobId: 'j' }));
  renderHook(() => useSessionPersistence({ status: 'idle', jobId: null, results: null, processingMedia: null, activeTab: 'create' }));
  expect(localStorage.getItem(SESSION_KEY)).toBeNull();
});

test('explicit clear removes persisted state', () => {
  localStorage.setItem(SESSION_KEY, '{}');
  act(() => clearPersistedSession());
  expect(localStorage.getItem(SESSION_KEY)).toBeNull();
});
''')

# Root error boundary.
write("dashboard/src/main.jsx", r'''
import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import RedesignApp from './redesign/RedesignApp';
import { AppErrorBoundary } from './redesign/AppErrorBoundary';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <AppErrorBoundary><RedesignApp /></AppErrorBoundary>
  </React.StrictMode>,
);
''')

# Minimal, assertion-backed integration into the large app controller.
replace_once(
    "dashboard/src/redesign/RedesignApp.jsx",
    "import { useSessionPersistence } from '../hooks/useSessionPersistence';",
    "import { useSessionPersistence, loadPersistedSession, clearPersistedSession } from '../hooks/useSessionPersistence';",
)
replace_once(
    "dashboard/src/redesign/RedesignApp.jsx",
    "export default function RedesignApp() {\n  // The Gemini key",
    "export default function RedesignApp() {\n  const restoredSession = useMemo(() => loadPersistedSession(), []);\n  // The Gemini key",
)
replace_once("dashboard/src/redesign/RedesignApp.jsx", "const [tab, setTab] = useState('create');", "const [tab, setTab] = useState(restoredSession?.activeTab || 'create');")
replace_once("dashboard/src/redesign/RedesignApp.jsx", "const [jobId, setJobId] = useState(null);", "const [jobId, setJobId] = useState(restoredSession?.jobId || null);")
replace_once("dashboard/src/redesign/RedesignApp.jsx", "const [status, setStatus] = useState('idle'); // idle | processing | complete | error", "const [status, setStatus] = useState(restoredSession?.status || 'idle'); // idle | processing | complete | error")
replace_once("dashboard/src/redesign/RedesignApp.jsx", "const [results, setResults] = useState(null);", "const [results, setResults] = useState(restoredSession?.results || null);")
replace_once("dashboard/src/redesign/RedesignApp.jsx", "const [processingMedia, setProcessingMedia] = useState(null);", "const [processingMedia, setProcessingMedia] = useState(restoredSession?.processingMedia || null);")
replace_once("dashboard/src/redesign/RedesignApp.jsx", "const [preselections, setPreselectionsRaw] = useState(null);", "const [preselections, setPreselectionsRaw] = useState(restoredSession?.preselections || null);")
replace_once("dashboard/src/redesign/RedesignApp.jsx", "try { localStorage.removeItem('clippyme_session'); } catch { /* */ }", "clearPersistedSession();")
replace_once(
    "dashboard/src/redesign/RedesignApp.jsx",
    "function Toasts({ items }) {\n  const ic = { success: 'circle-check', warn: 'triangle-alert', info: 'info', error: 'triangle-alert' };\n  return (\n    <div className=\"toasts\">\n      {items.map((t) => (\n        <div key={t.id} className={'toast ' + (t.type === 'error' ? 'warn' : t.type)}>\n          <span className=\"ti\"><Icon n={ic[t.type] || 'info'} /></span>\n          <span>{t.msg}</span>\n        </div>\n      ))}\n    </div>\n  );\n}",
    "function Toasts({ items, onDismiss }) {\n  const ic = { success: 'circle-check', warn: 'triangle-alert', info: 'info', error: 'triangle-alert' };\n  return (\n    <div className=\"toasts\" aria-live=\"polite\" aria-relevant=\"additions\">\n      {items.map((t) => (\n        <div key={t.id} role={t.type === 'error' ? 'alert' : 'status'} className={'toast ' + (t.type === 'error' ? 'warn' : t.type)}>\n          <span className=\"ti\" aria-hidden=\"true\"><Icon n={ic[t.type] || 'info'} /></span>\n          <span>{t.msg}</span>\n          <button type=\"button\" className=\"toast-close\" aria-label=\"Dismiss notification\" onClick={() => onDismiss(t.id)}><Icon n=\"x\" /></button>\n        </div>\n      ))}\n    </div>\n  );\n}",
)
replace_once(
    "dashboard/src/redesign/RedesignApp.jsx",
    "setToasts((t) => [...t, { id, type, msg }]);",
    "setToasts((t) => [...t.slice(-4), { id, type, msg }]);",
)
replace_once(
    "dashboard/src/redesign/RedesignApp.jsx",
    "  const pushToast = useCallback((type, msg) => {",
    "  const dismissToast = useCallback((id) => setToasts((items) => items.filter((item) => item.id !== id)), []);\n\n  const pushToast = useCallback((type, msg) => {",
)
replace_once("dashboard/src/redesign/RedesignApp.jsx", "<Toasts items={toasts} />", "<Toasts items={toasts} onDismiss={dismissToast} />")

# Create flow validation and corrected source copy.
replace_once(
    "dashboard/src/redesign/create.jsx",
    "import { BannerControls } from './bannerControls';",
    "import { BannerControls } from './bannerControls';\nimport { validateCreateOptions } from '../lib/createValidation';",
)
replace_once("dashboard/src/redesign/create.jsx", "Paste a video link (YouTube, Twitch, Vimeo, …)", "Paste a video link (YouTube, Twitch, or Kick)")
replace_once("dashboard/src/redesign/create.jsx", "MP4 · MOV · WEBM · up to 2&nbsp;GB", "MP4 · MOV · WEBM · up to 16&nbsp;GB")
replace_once(
    "dashboard/src/redesign/create.jsx",
    "function SummaryBar({ opts, ready, count, onCreate }) {",
    "function SummaryBar({ opts, ready, count, onCreate, error }) {",
)
replace_once(
    "dashboard/src/redesign/create.jsx",
    "        <div className=\"s-sub\">\n          {chips.map((c) => <span key={c} className=\"chip\">{c}</span>)}\n        </div>",
    "        <div className=\"s-sub\">\n          {chips.map((c) => <span key={c} className=\"chip\">{c}</span>)}\n        </div>\n        {error && <div className=\"field-error\" role=\"alert\">{error}</div>}",
)
replace_once(
    "dashboard/src/redesign/create.jsx",
    "  const batchCount = opts.batch.split('\\n').filter((l) => l.trim()).length + (opts.batchFiles || []).length;\n  const ready = opts.mode === 'single'\n    ? (opts.source === 'url' ? !!opts.url : !!opts.file)\n    : batchCount > 0;\n  const nSources = opts.mode === 'single' ? 1 : Math.max(1, batchCount);",
    "  const validation = validateCreateOptions(opts);\n  const ready = validation.valid;\n  const nSources = Math.max(1, validation.sourceCount);",
)
replace_once(
    "dashboard/src/redesign/create.jsx",
    "sub=\"Drop a link from YouTube, Twitch, or Vimeo (or upload a file) and ClippyMe does the rest: transcribes it, finds the best moments, reframes and trims them, and queues the top clips to post.\"",
    "sub=\"Drop a link from YouTube, Twitch, or Kick (or upload a file) and ClippyMe does the rest: transcribes it, finds the best moments, reframes and trims them, and queues the top clips to post.\"",
)
replace_once(
    "dashboard/src/redesign/create.jsx",
    "<SummaryBar opts={opts} ready={ready} count={count} onCreate={onCreate} />",
    "<SummaryBar opts={opts} ready={ready} count={count} onCreate={onCreate} error={validation.firstError} />",
)

# Real API live monitor accepts an AbortSignal without changing existing callers.
replace_once(
    "dashboard/src/redesign/realApi.js",
    "export async function getLiveMonitorStatus() {",
    "export async function getLiveMonitorStatus({ signal } = {}) {",
)
replace_once(
    "dashboard/src/redesign/realApi.js",
    "const res = await apiFetch(getApiUrl('/api/live-monitor/status'));",
    "const res = await apiFetch(getApiUrl('/api/live-monitor/status'), { signal });",
)

# Progressive enhancement styles, kept in the canonical app stylesheet.
css_path = ROOT / "dashboard/src/redesign/app.css"
css = css_path.read_text(encoding="utf-8")
marker = "/* frontend-overhaul: resilience, accessibility, lazy media */"
if marker not in css:
    css += r'''

/* frontend-overhaul: resilience, accessibility, lazy media */
.sr-only{position:absolute!important;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.status-dot.offline{color:var(--danger);border-color:rgba(255,92,92,.35)}
.status-dot.offline i{background:var(--danger);box-shadow:0 0 0 3px rgba(255,92,92,.14)}
.toast{gap:10px}.toast-close{margin-left:auto;background:none;border:0;color:inherit;display:flex;padding:3px;cursor:pointer;border-radius:6px}.toast-close:hover{background:rgba(255,255,255,.08)}.toast-close svg{width:14px;height:14px}
.field-error{margin-top:9px;color:var(--danger);font-size:var(--text-xs);line-height:1.45}
.operation-grid{display:flex;flex-wrap:wrap;gap:8px}.operation-grid-secondary{margin-top:8px}.operation-metric{min-width:112px;flex:1 1 112px;border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:var(--bg-2)}.operation-metric .label{font-size:10px;margin-bottom:4px}.operation-value{font-family:var(--font-mono);font-size:15px;color:var(--fg-1)}.operation-hint{font-size:11px;color:var(--fg-4);margin-top:2px}.operations{margin-bottom:16px}.operations .stream-head{margin:0 0 8px}.operations .stream-head h3{font-size:14px}
.processing-toolbar{display:flex;align-items:center;margin-bottom:16px;gap:10px}.processing-toolbar>.label{text-transform:none;letter-spacing:0;color:var(--fg-3);font-family:var(--font-mono);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.processing-actions{margin-left:auto;display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}.pbar-pct{font-family:var(--font-mono);font-size:13px;letter-spacing:.04em;min-width:110px;color:var(--blue-300)}
.fatal-shell{min-height:100vh;display:grid;place-items:center;padding:24px}.fatal-card{width:min(680px,100%);background:var(--bg-2);border:1px solid var(--line-2);border-radius:var(--r-lg);padding:32px;box-shadow:var(--shadow-lg)}.fatal-card h1{font-size:clamp(28px,5vw,44px);margin:12px 0}.fatal-card p{color:var(--fg-3);line-height:1.6}.fatal-icon{width:48px;height:48px;border-radius:14px;display:grid;place-items:center;background:var(--danger-bg);color:var(--danger)}.fatal-icon svg{width:24px;height:24px}.fatal-actions{display:flex;gap:10px;flex-wrap:wrap;margin:24px 0}.fatal-card details{border-top:1px solid var(--line-1);padding-top:16px;color:var(--fg-3)}.fatal-card pre{white-space:pre-wrap;margin-top:10px;font:12px/1.5 var(--font-mono)}
@media (max-width:760px){.topnav{padding:0 10px;gap:8px}.brand>span,.status-dot .sd-lbl,.avatar{display:none}.tabs{overflow-x:auto;scrollbar-width:none}.tab{padding:7px 11px}.processing-toolbar{align-items:flex-start;flex-direction:column}.processing-actions{margin-left:0;width:100%;justify-content:flex-start}.operation-metric{min-width:calc(50% - 4px)}}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}.confetti{display:none!important}.fade-in{animation:none!important}}
'''
    css_path.write_text(css.rstrip() + "\n", encoding="utf-8")

print("frontend overhaul patch applied")
