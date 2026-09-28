// Pure payload builder for the Live Monitor's banner mode picker (Auto/Off/
// Custom), mirroring the backend's LiveMonitorStartRequest.banner semantics
// (domain/banner.py monitor_banner_params): null = auto from the monitor's
// own platform + channel, {enabled:false} = off, {platform, handle, y_pct?} =
// override.
export function buildMonitorBannerPayload(mode, { platform, handle, y_pct } = {}) {
  if (mode === 'off') return { enabled: false };
  if (mode === 'custom') return { platform, handle: (handle || '').trim(), ...(y_pct !== undefined ? { y_pct } : {}) };
  return null; // auto
}
