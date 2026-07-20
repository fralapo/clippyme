import { test } from 'vitest';
import assert from 'node:assert/strict';
import { buildMonitorBannerPayload } from './liveMonitorBanner.js';

// Mirrors LiveMonitorStartRequest.banner / monitor_banner_params semantics:
// null = auto (monitor's own platform + channel), {enabled:false} = off,
// {platform, handle, y_pct?} = override.

test('auto mode sends null', () => {
  assert.equal(buildMonitorBannerPayload('auto'), null);
  assert.equal(buildMonitorBannerPayload('auto', { platform: 'kick', handle: 'x' }), null);
});

test('off mode sends {enabled:false}', () => {
  assert.deepEqual(buildMonitorBannerPayload('off'), { enabled: false });
});

test('custom mode sends the trimmed platform+handle override', () => {
  assert.deepEqual(
    buildMonitorBannerPayload('custom', { platform: 'twitch', handle: '  xqc  ' }),
    { platform: 'twitch', handle: 'xqc' },
  );
});

test('custom mode forwards y_pct only when provided', () => {
  assert.deepEqual(
    buildMonitorBannerPayload('custom', { platform: 'kick', handle: 'x', y_pct: 0.7 }),
    { platform: 'kick', handle: 'x', y_pct: 0.7 },
  );
  const noYPct = buildMonitorBannerPayload('custom', { platform: 'kick', handle: 'x' });
  assert.equal('y_pct' in noYPct, false);
});
