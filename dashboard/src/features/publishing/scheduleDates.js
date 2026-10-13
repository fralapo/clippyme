// Local YYYY-MM-DD for the publish `start_date`, offset by `addDays`. Used to
// give each clip in a batch its own day so a per-platform daily posting cap
// (e.g. YouTube's 5/day) doesn't reject the tail of the batch.
//
// `now` is injectable for tests; callers omit it.
export function localDatePlus(addDays, now = new Date()) {
  const d = new Date(now);
  d.setDate(d.getDate() + addDays);
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

// Batch spacing uses Zernio's configured calendar date, not the device's:
// a user scheduling at 01:00 in Rome for New York may still be on yesterday.
export function dateInTimezonePlus(addDays, timeZone, now = new Date()) {
  const zone = timeZone || 'Europe/Rome';
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(now).map((part) => [part.type, part.value]));
  const stamp = new Date(Date.UTC(
    Number(parts.year), Number(parts.month) - 1, Number(parts.day) + addDays,
  ));
  return stamp.toISOString().slice(0, 10);
}

// Browser-local datetime-local input -> an unambiguous UTC instant for Zernio.
// The local clock can be non-existent (spring DST gap) or occur TWICE (autumn
// DST fold). JavaScript Date silently selects the earlier instant for a fold;
// sending it would publish at an hour the operator did not unambiguously pick.
const LOCAL_MINUTE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/;

function localMinute(instant) {
  const pad = (number) => String(number).padStart(2, '0');
  return `${instant.getFullYear()}-${pad(instant.getMonth() + 1)}-${pad(instant.getDate())}T${pad(instant.getHours())}:${pad(instant.getMinutes())}`;
}

function hasSecondInstant(instant, selectedLocalMinute) {
  const milliseconds = instant.getTime();
  const selectedOffset = instant.getTimezoneOffset();
  // Inspect offsets on both sides of the selected day. If a DST transition
  // makes the selected wall-clock minute repeat, the other instant differs
  // by exactly the two timezone offsets. Handles 30-minute transitions too.
  for (const direction of [-1, 1]) {
    const otherOffset = new Date(milliseconds + direction * 24 * 60 * 60 * 1000).getTimezoneOffset();
    if (otherOffset === selectedOffset) continue;
    const alternative = new Date(milliseconds + (otherOffset - selectedOffset) * 60 * 1000);
    if (alternative.getTime() !== milliseconds && localMinute(alternative) === selectedLocalMinute) {
      return true;
    }
  }
  return false;
}

function validateManualSchedule(value, now) {
  const generic = 'Select a valid future date and time to continue.';
  if (typeof value !== 'string' || !LOCAL_MINUTE.test(value)) {
    return { iso: null, problem: generic };
  }
  const instant = new Date(value);
  if (!Number.isFinite(instant.getTime()) || localMinute(instant) !== value) {
    return { iso: null, problem: generic };
  }
  if (hasSecondInstant(instant, value)) {
    return {
      iso: null,
      problem: 'This local time occurs twice when daylight saving time ends. Choose another time.',
    };
  }
  if (instant.getTime() <= now.getTime()) return { iso: null, problem: generic };
  return { iso: instant.toISOString(), problem: null };
}

// Show the same UTC instant in both the operator's and the provider's zone.
// The provider timezone changes its displayed clock, NEVER the submitted UTC
// instant (or a browser DST ambiguity would be silently reintroduced).
export function schedulePreview(value, providerTimezone, now = new Date()) {
  const iso = manualScheduleIso(value, now);
  if (!iso) return null;
  const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'device local';
  const targetTimezone = providerTimezone || 'Europe/Rome';
  const format = (timeZone) => new Intl.DateTimeFormat('en-GB', {
    dateStyle: 'full', timeStyle: 'long', timeZone,
  }).format(new Date(iso));
  try {
    return {
      iso, browserTimezone, providerTimezone: targetTimezone,
      browserTime: format(browserTimezone),
      providerTime: format(targetTimezone),
    };
  } catch (error) {
    // An invalid server-supplied IANA timezone must never crash the modal.
    if (!(error instanceof RangeError)) throw error;
    return { iso, browserTimezone, providerTimezone: targetTimezone,
      browserTime: format(browserTimezone), providerTime: 'Invalid provider timezone' };
  }
}

// A manual timestamp is only valid if it names one specific future instant.
export function manualScheduleIso(value, now = new Date()) {
  return validateManualSchedule(value, now).iso;
}

// Human explanation for disabled exact-time scheduling. No different parser:
// the UI and outgoing payload share precisely the same validation.
export function manualScheduleProblem(value, now = new Date()) {
  return validateManualSchedule(value, now).problem;
}
