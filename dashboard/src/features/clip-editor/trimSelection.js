// Pure manual-trim selection math (flycut-style), extracted from
// EditClipModal so it is unit-testable and shareable with useManualTrim.
// Segments are { index, text, start, end } (clip-relative seconds); spans
// and ranges are [start, end] pairs.

// Reconstruct which transcript segments were marked dropped from previously
// saved drop_ranges: a segment is "dropped" if a saved span covers its
// midpoint. Lets the manual-trim checklist restore state on modal reopen.
export function dropSetFromRanges(segments, ranges) {
  const set = new Set();
  if (!ranges?.length) return set;
  segments.forEach((s) => {
    const mid = (s.start + s.end) / 2;
    if (ranges.some(([a, b]) => mid >= a && mid <= b)) set.add(s.index);
  });
  return set;
}

// Indices of every segment strictly overlapping any span (touching endpoints
// do NOT count — the AI trim must not swallow the neighbouring sentence).
export function segmentIndicesHit(segments, spans) {
  const hit = new Set();
  for (const [ds, de] of spans || []) {
    for (const s of segments || []) {
      if (s.start < de && s.end > ds) hit.add(s.index);
    }
  }
  return hit;
}

// Dropped segment indices → [start, end] spans for the backend, in
// transcript order.
export function rangesFromDropSet(segments, dropped) {
  return (segments || [])
    .filter((s) => dropped.has(s.index))
    .map((s) => [s.start, s.end]);
}
