import { test, expect } from 'vitest';
import { dropSetFromRanges, segmentIndicesHit, rangesFromDropSet } from './trimSelection';

const SEGS = [
  { index: 0, text: 'a', start: 0.0, end: 2.0 },
  { index: 1, text: 'b', start: 2.0, end: 4.0 },
  { index: 2, text: 'c', start: 4.0, end: 6.0 },
];

test('dropSetFromRanges uses midpoint semantics', () => {
  // Range [1.5, 3.5] covers seg 1's midpoint (3.0) but not seg 0's (1.0).
  expect([...dropSetFromRanges(SEGS, [[1.5, 3.5]])]).toEqual([1]);
  expect(dropSetFromRanges(SEGS, []).size).toBe(0);
  expect(dropSetFromRanges(SEGS, undefined).size).toBe(0);
});

test('segmentIndicesHit is strict overlap — touching endpoints do not hit', () => {
  // Span exactly abutting seg 1 on both sides hits nothing.
  expect(segmentIndicesHit(SEGS, [[2.0, 2.0]]).size).toBe(0);
  // Span [1.9, 2.1] straddles the 0/1 boundary → both hit.
  expect([...segmentIndicesHit(SEGS, [[1.9, 2.1]])].sort()).toEqual([0, 1]);
  // A span covering seg 2 only.
  expect([...segmentIndicesHit(SEGS, [[4.5, 5.0]])]).toEqual([2]);
  expect(segmentIndicesHit(null, [[0, 9]]).size).toBe(0);
});

test('rangesFromDropSet returns spans in transcript order', () => {
  expect(rangesFromDropSet(SEGS, new Set([2, 0]))).toEqual([[0.0, 2.0], [4.0, 6.0]]);
  expect(rangesFromDropSet(SEGS, new Set())).toEqual([]);
  expect(rangesFromDropSet(null, new Set([0]))).toEqual([]);
});
