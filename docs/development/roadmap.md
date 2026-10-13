# ClippyMe — development execution roadmap

Updated: 2026-10-13. Status is based on actual GitHub code and pull requests,
not unverified browser-chat history. This is a living **execution tracker**, not
a source of runtime behavior: architecture docs, tests and code remain
authoritative (see [CLAUDE.md](../../CLAUDE.md)).

## Completed and integrated

- [x] [#34](https://github.com/fralapo/clippyme/pull/34): correct publishing
  intent/results and security advisories.
- [x] [#35](https://github.com/fralapo/clippyme/pull/35): fail-closed media
  acceptance metrics with real karaoke FFmpeg test coverage.
- [x] [#37](https://github.com/fralapo/clippyme/pull/37): optional
  FFmpeg/editorial/UX development references.
- [x] [#38](https://github.com/fralapo/clippyme/pull/38): require consent
  before substituting unedited source clips for failed edited exports.
- [x] [#36](https://github.com/fralapo/clippyme/pull/36): exact-time manual
  scheduling for one clip.
- [x] [#39](https://github.com/fralapo/clippyme/pull/39): authenticated
  binary previews for uploaded custom fonts.

## Next gates — verify before marking complete

- [x] [#40](https://github.com/fralapo/clippyme/pull/40):
  when scheduling is off, one **Publish now** action; no misleading **Queue**.
- [x] [#41](https://github.com/fralapo/clippyme/pull/41):
  explicitly disabled edits publish raw pixels; omitted API toggles retain
  legacy behavior.
- [x] [#43](https://github.com/fralapo/clippyme/pull/43):
  reject ambiguous autumn DST times instead of silently selecting an instant.
- [x] [#45](https://github.com/fralapo/clippyme/pull/45):
  status is **scheduled** or **submitted** after Zernio acceptance, not
  incorrectly **live**; supersedes conflicting [#44](https://github.com/fralapo/clippyme/pull/44).
- [x] Rechecked the combined `main` CI: [run #664](https://github.com/fralapo/clippyme/actions/runs/38370087530)
  on [`cf824902`](https://github.com/fralapo/clippyme/commit/cf8249023c621a168a59c71ff1330f9284aca192)
  passed all four jobs after [#52](https://github.com/fralapo/clippyme/pull/52).

## Publishing follow-up releases already integrated

- [x] [#47](https://github.com/fralapo/clippyme/pull/47): clear stale composed preview.
- [x] [#50](https://github.com/fralapo/clippyme/pull/50): bounded publishing and safe modal closing.
- [x] [#51](https://github.com/fralapo/clippyme/pull/51): restore publication state from server metadata.
- [x] [#52](https://github.com/fralapo/clippyme/pull/52): exclude reprocessing clips from bulk publish.

## Product and reliability review candidates

These are **discovery tasks**, not verified missing features. Before
implementation, compare with the current app and tests and record a concrete
user-visible gap. One independently testable change per PR.

### P1 — publishing correctness and recovery

- [x] Reject ambiguous `datetime-local` wall-clock values at autumn DST
  fallback ([#43](https://github.com/fralapo/clippyme/pull/43)).
- [ ] Independently review user-device-local scheduling versus the configured
  Zernio timezone and confirm the selected instant in the UX (separate from
  DST ambiguity already fixed).
- [ ] Audit the Publish modal's close/escape behavior while a request is
  in progress: after submission, closing the dialog must not suggest a post
  was cancelled. Verify idempotent retry and durable status visibility.
- [ ] Confirm publish-with-edits matches the **actual resulting composition**.
  Preserve the locking, metadata, `intent_id` and Zernio guarantees in
  [publishing architecture](../architecture/publishing.md).

### P2 — review-before-publish and editorial quality

- [ ] Audit the current Results and Edit modal against the intended
  review-before-publish flow. The edit preview currently displays the
  existing on-disk artifact while controls are staged; distinguish a design
  preview from a final FFmpeg-composed output.
- [ ] Define the smallest operator-approval workflow (approve, request
  changes, or discard a clip) with clear failure/retry states, accessibility,
  and no accidental blocking of unattended Live Monitor posting.
- [ ] Evaluate quality by representative talking-head, podcast, gameplay,
  screen-capture and no-face samples. Automated media-signal quality does not
  prove editorial coherence, retention value or caption legibility.
- [ ] Investigate opt-in editorial feedback (accept/reject reasons) as input
  to future clip selection. Specify safe local persistence before adding it.

### P3 — delivery profiles and operational visibility

- [ ] Inventory current platform aspect, subtitle safe-zone, branding and
  output controls; only add truly missing per-platform options.
- [ ] Inventory existing per-job Gemini/Deepgram/ElevenLabs accounting and
  user-facing visibility; add costs/queue insights only if an actual gap
  remains. Never price unknown models at zero.
- [ ] Reassess publishing queue/restart durability against the existing
  file-backed journal, monitor ownership and at-least-once Zernio behavior
  before proposing an independent queue.

## Execution contract

1. Scope a single user-visible defect or measurable improvement.
2. Read canonical architecture, source, tests, and `CLAUDE.md`.
3. Write a regression or acceptance test before editing production when
   feasible. Preserve backward compatibility deliberately.
4. Keep no-secret/no-force-push rules, safe clip resolution, `original_index`,
   atomic file writes, per-clip locks, compose order, and publish idempotency.
5. Run relevant pytest/Ruff, frontend test/lint/build and security audits;
   run real FFmpeg/Docker tests for media/renderer changes.
6. All four GitHub CI jobs green before merge; re-check `main` after merge.
   Do not claim local tests/hooks executed when changes are made via GitHub API.
7. Update completed checkboxes only after the PR is merged and its required
   verification has been observed. Link evidence rather than treating a
   proposed design as implemented.
