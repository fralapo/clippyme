import { describe, expect, it } from 'vitest';

import {
  formatEta,
  latestRuntimeTelemetry,
  parseTelemetryLine,
} from './runtimeTelemetry';


describe('runtime telemetry', () => {
  it('parses numeric and string fields', () => {
    expect(parseTelemetryLine(
      '[runtime] stage=reframing progress=82 attempt=2/3 cpu=14.5',
      '[runtime]',
    )).toEqual({ stage: 'reframing', progress: 82, attempt: '2/3', cpu: 14.5 });
  });

  it('keeps the latest runtime row and the preflight row', () => {
    const result = latestRuntimeTelemetry([
      '[runtime] stage=queued progress=2',
      '[preflight] clips=6 runtime_min=12.5 disk_gb=2.4 cost_usd=0.0042',
      '[runtime] stage=quality progress=93 clips=4/6 eta_s=21',
    ]);
    expect(result.runtime.stage).toBe('quality');
    expect(result.runtime.progress).toBe(93);
    expect(result.runtime.clips).toBe('4/6');
    expect(result.preflight.runtime_min).toBe(12.5);
  });

  it('formats useful ETAs', () => {
    expect(formatEta(35)).toBe('35s');
    expect(formatEta(125)).toBe('2m 5s');
    expect(formatEta(3660)).toBe('1h 1m');
    expect(formatEta(undefined)).toBe('—');
  });
});
