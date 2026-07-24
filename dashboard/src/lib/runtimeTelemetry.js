// Parse the stable key=value rows emitted by runtime_state/preflight.
// Unknown keys are preserved so backend additions remain forward-compatible.

function coerce(value) {
  if (value === undefined) return undefined;
  if (/^-?\d+(?:\.\d+)?$/.test(value)) return Number(value);
  return value;
}

export function parseTelemetryLine(line, prefix) {
  if (typeof line !== 'string' || !line.startsWith(prefix)) return null;
  const fields = {};
  for (const token of line.slice(prefix.length).trim().split(/\s+/)) {
    const idx = token.indexOf('=');
    if (idx <= 0) continue;
    const key = token.slice(0, idx);
    const value = token.slice(idx + 1);
    fields[key] = coerce(value);
  }
  return fields;
}

export function latestRuntimeTelemetry(logs = []) {
  let runtime = null;
  let preflight = null;
  for (const line of logs) {
    const nextRuntime = parseTelemetryLine(line, '[runtime]');
    if (nextRuntime) runtime = nextRuntime;
    const nextPreflight = parseTelemetryLine(line, '[preflight]');
    if (nextPreflight) preflight = nextPreflight;
  }
  return { runtime, preflight };
}

export function formatEta(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value) || value < 0) return '—';
  if (value < 60) return `${Math.round(value)}s`;
  const minutes = Math.floor(value / 60);
  const remainder = Math.round(value % 60);
  if (minutes < 60) return remainder ? `${minutes}m ${remainder}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const minuteRemainder = minutes % 60;
  return minuteRemainder ? `${hours}h ${minuteRemainder}m` : `${hours}h`;
}

export function formatMetric(value, suffix = '') {
  return Number.isFinite(Number(value)) ? `${Number(value)}${suffix}` : '—';
}
