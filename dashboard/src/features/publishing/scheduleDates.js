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
