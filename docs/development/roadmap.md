# ClippyMe — development execution roadmap

Updated: 2026-10-14. The latest follow-up changes are pushed to
`codex/local-roadmap-follow-up` and are not merged; GitHub Actions is paused
while free credits are exhausted. Earlier integrated work is based on actual
GitHub code and pull requests, not unverified browser-chat history. This is a
living **execution tracker**, not a source of runtime behavior: architecture
docs, tests and code remain authoritative (see [CLAUDE.md](../../CLAUDE.md)).

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
- [x] [#53](https://github.com/fralapo/clippyme/pull/53),
  [#54](https://github.com/fralapo/clippyme/pull/54) and
  [#55](https://github.com/fralapo/clippyme/pull/55): History recovery,
  Python advisory review and the compatible Click/SceneDetect updates.
- [x] [#57](https://github.com/fralapo/clippyme/pull/57) and
  [#60](https://github.com/fralapo/clippyme/pull/60): offline backup/restore,
  disk capacity reporting and History storage visibility.
- [x] [#58](https://github.com/fralapo/clippyme/pull/58): durable receipts
  and safe reconciliation for uncertain Zernio publication results.
- [x] [#56](https://github.com/fralapo/clippyme/pull/56): explicit device,
  Zernio and UTC schedule times; saved-video preview labeling; session-only
  browser credential retention. Its [four-job CI](https://github.com/fralapo/clippyme/actions/runs/38416212114)
  passed before merge.
- [x] [#59](https://github.com/fralapo/clippyme/pull/59): Chromium user
  journeys, progressive coverage gates, production Docker smoke checks and
  opt-in provider/monitor test harnesses. Its [five-job CI](https://github.com/fralapo/clippyme/actions/runs/38418800831)
  passed before merge.

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

## Multi-provider LLM — local, not merged

- [x] Add OpenAI, OpenRouter, Anthropic and DeepSeek credentials and route
  analysis through each provider's documented API while preserving Gemini as
  the default.
- [x] Replace manual model IDs with provider-backed Settings catalogs,
  refresh controls, safe failure behavior and a short cache. Keep provider keys
  in owner-only backend configuration.
- [x] Add offline catalog, auth, pagination, JSON-output, usage-normalization,
  request-security and UI regression tests. Record the API contracts in
  [the provider integration note](llm-providers.md).
- [ ] Optional operator check: run catalog and analysis smoke checks against
  provider accounts configured on the operator's self-hosted installation.
  Local tests stub HTTP; model generation can incur provider charges, so no
  live call is needed for local code verification and none is claimed here.
  Rechecked on 2026-10-14: credentials are present on this host but were not
  used. The focused local LLM request/service tests passed (40 tests across
  `test_llm_service.py`, `test_gemini_service.py` and `test_gemini_request.py`);
  both provider-catalog API route tests also passed in the local Docker
  container.

## Product and reliability review candidates

These are **discovery tasks**, not verified missing features. Before
implementation, compare with the current app and tests and record a concrete
user-visible gap. One independently testable change per PR.

### P1 — publishing correctness and recovery

- [x] Reject ambiguous `datetime-local` wall-clock values at autumn DST
  fallback ([#43](https://github.com/fralapo/clippyme/pull/43)).
- [x] [#56](https://github.com/fralapo/clippyme/pull/56): display user-device,
  configured Zernio and exact UTC scheduling times before confirmation.
- [x] Publish modal close/Escape behavior and recovery are covered: the dialog
  stays visible while uploads are in flight, retries reuse the same intent,
  and the backend keeps a durable receipt/status for reconciliation
  (`publish.test.jsx`, `publishIntent.test.js`, publishing intent tests).
- [x] Publish-with-edits was verified through the API and a real FFmpeg render:
  the provider boundary receives the graded MP4, while the clip lock is held;
  the derived `request_id` and confirmed intent receipt are preserved
  (`test_publish_with_edits_uploads_the_real_composition_and_records_its_intent`).

### P2 — review-before-publish and editorial quality

- [x] [#56](https://github.com/fralapo/clippyme/pull/56): label the Edit
  preview as the saved video and explain that staged changes are not rendered
  live. Apply still starts the background reprocessing flow.
- [x] Operator review now persists per-clip approval, change requests and
  discard state in job metadata. Manual publish fails closed until approval;
  edits revoke approval, failures expose a retry, and the Live Monitor path
  remains automatic. API/UI and Axe coverage added.
- [ ] Optional operator review: evaluate quality with authorized,
  representative talking-head, podcast, gameplay, screen-capture and no-face
  samples. Automated media-signal quality does not prove editorial coherence,
  retention value or caption legibility. The
  [review rubric](editorial-quality-review.md) is ready. Rechecked on
  2026-10-14: no authorized representative samples were supplied; the test
  tree contains no source-media fixtures, so no editorial pass is claimed.
- [x] Optional, categorized approval/rejection feedback now uses bounded local
  storage: only an explicitly selected reason, coarse score and rounded
  duration are retained; repeated selection-relevant reasons add a restrained
  future prompt hint. No clip identifiers, titles, transcripts or free-form
  notes are saved.

### P3 — delivery profiles and operational visibility

- [x] Inventory current platform aspect, subtitle safe-zone, branding and
  output controls in [the platform review](platform-output-inventory.md). The
  concrete gap was TikTok's hard-coded public audience and enabled interaction
  settings; the local Publish modal now loads creator-specific choices and
  blocks submission when options are unavailable. Locally verified; GitHub CI
  and merge remain unavailable while Actions credits are exhausted.
- [x] Audited cost visibility in [the operations review](operations-inventory.md).
  Gemini usage is priced and the UI identifies its preflight value as an
  upper bound; History now labels its stored amount as Gemini-only. Paid cloud
  transcription and optional audio isolation remain unpriced/untracked, so the
  UI explicitly excludes them instead of implying a total bill. No zero-price
  fallback was added.
- [x] Reassessed queue and restart durability in
  [the operations review](operations-inventory.md): the bounded single-process
  asyncio queue is journaled atomically, queued work is restored on restart,
  and checkpoint-capable interrupted jobs resume. The monitor has its own
  persisted pending-publication journal and stable idempotency identity.
  An independent distributed queue is not justified for the supported local
  single-instance deployment; multi-process/shared-storage operation remains
  outside the current contract.

### P4 — optional on-device checks (no staging environment required)

- [ ] Optional operator check: run read-only provider checks against the
  accounts configured on the self-hosted installation, including current LLM
  catalog calls. Generation and audio checks may be billable; local tests use
  deterministic HTTP fixtures. Rechecked on 2026-10-14: host credentials were
  not used and no provider request or social post was made.
- [ ] Optional operator check: run the Live Monitor soak against an already
  configured local instance for 24 hours and review the JSONL report. Rechecked
  locally on 2026-10-14: ports 8000 and 5175 are closed; the persisted monitor
  record has no config, so there is no configured/running monitor to observe.
  CI verifies the anomaly detector, but does not establish live-stream recovery
  or sustained operation.
- [x] Simulated the NVIDIA deployment contract on the host by parsing
  `docker-compose.gpu.yml` and asserting its NVIDIA build runtime, device
  driver and GPU capability. Physical GPU execution is explicitly skipped per
  user request; this static check does not claim a real CUDA workload ran.

## Earlier local verification — 2026-10-14 (before `0c706693`)

This records the previous checkout and host, before the current follow-up
branch. GitHub Actions was not used because the repository's free Actions
credits were exhausted. That checkout passed the CI-equivalent checks then
available on that host:

- Backend host suite: **1,778 passed, 10 skipped, 159 deselected**, with
  **71.09% coverage** against the 68% CI minimum.
- Backend static checks: Ruff bug-class rules and Bandit medium/high scan
  passed. `pip-audit` found no known vulnerabilities in either pinned
  requirements set, with the three documented core advisories ignored as in
  CI.
- Frontend: **374 tests passed across 39 files**. Coverage passed every CI
  floor (71.14% statements, 69.28% branches, 64.86% functions, 76.77% lines);
  ESLint and the Vite production build passed.
- Frontend dependency audit: `npm audit --package-lock-only
  --audit-level=high` found **0 vulnerabilities**.
- Browser journeys: **3 Playwright tests passed** (Create → Processing →
  Results → Edit → Publish; History → Restore; Settings live-provider model
  discovery without a browser Gemini key).
- Local FFmpeg integration subset: **7 real render tests passed** for grading,
  hooks and smart-cut audio; **1 synthetic quality-suite test** and **1 broken
  export rejection test** passed. The subtitle-render suite was also attempted,
  but the installed macOS FFmpeg 8.0.1 build has no `subtitles`/`ass` filters
  (libass), so **147 subtitle-dependent cases failed before rendering**. This
  is an environment limitation, not a passing result; a libass-enabled FFmpeg
  or the CI container is required to verify those cases.
- `git diff --check` passed.

### Recheck on `codex/local-roadmap-follow-up` — 2026-10-14

The local environment differs from the earlier verification above:

- Ruff and ESLint passed. The dashboard suite passed: **374 tests across 39
  files**. The Vite production build passed; it emitted runtime font URL
  warnings for `/fonts/*.ttf`.
- Focused multi-provider LLM request/service tests passed: **40 passed**.
- The two `/api/config/models` route tests passed in the Docker Linux
  container. The same focused route selection stalled in the Windows host
  runner, so the container result is the verified API-route result.
- The focused Docker/FFmpeg libass integration test rendered every subtitle
  preset successfully: **1 passed in 7.69 s**. Docker, OpenCV, PyTorch,
  MediaPipe and FFmpeg's `ass`/`subtitles` filters are available on this host.
  The full integration run was interrupted during the expensive 1080×1920
  render matrix; it produced no failure summary and is **not** counted as a
  pass.
- The full host suite was attempted but did not reach a summary. This virtualenv
  lacks `pytest-timeout`, which CI uses for its 120-second per-test limit;
  PyPI DNS access was unavailable, so the plugin could not be installed. The
  host run made no progress beyond seven reported tests before it was stopped.
  No full host-suite result is claimed for this recheck.
- README, onboarding, deployment and test documentation now describe all five
  analysis providers and treat real-account/GPU checks as optional operator
  checks. The live-provider suite now includes opt-in, read-only catalog checks
  for OpenAI, OpenRouter, Anthropic and DeepSeek. The tracked-document link
  regression suite passed (**42 passed**); no live provider check was run.
- The optional docs-governance scanner also traverses ignored `.worktrees/` and
  `.local/` directories and treats inline code path examples in `CLAUDE.md` as
  links, so its 23 reported path errors are not tracked-document link failures.
  `tests/repository/test_docs.py`, which checks tracked Markdown links, passed.
- GitHub was rechecked on 2026-10-14: there are no open repository issues or
  pull requests. No Actions workflow was rerun.
- Rechecked the optional operator checks: provider credentials are present but
  were not used; ports 8000 and 5175 have no listeners and the persisted monitor
  record has no config. No live provider calls, posts or 24-hour soak were
  performed. No authorized representative media was supplied. The NVIDIA
  contract remains statically verified only; this host has no GPU.

The full Docker integration suite and production proxy smoke test were not run
because the full integration run was interrupted during its render matrix.
Provider generation was tested with deterministic HTTP fixtures; real-account
API calls are optional checks on an operator's self-hosted installation and
some may incur charges. GitHub Actions and PR merge remain deferred while its
credits are exhausted.

## Execution contract

1. Scope a single user-visible defect or measurable improvement.
2. Read canonical architecture, source, tests, and `CLAUDE.md`.
3. Write a regression or acceptance test before editing production when
   feasible. Preserve backward compatibility deliberately.
4. Keep no-secret/no-force-push rules, safe clip resolution, `original_index`,
   atomic file writes, per-clip locks, compose order, and publish idempotency.
5. Run relevant pytest/Ruff, frontend test/lint/build and security audits;
   run real FFmpeg/Docker tests for media/renderer changes.
6. All five GitHub CI jobs green before merge; re-check `main` after merge.
   Do not claim local tests/hooks executed when changes are made via GitHub API.
7. Update completed checkboxes only after the PR is merged and its required
   verification has been observed. Link evidence rather than treating a
   proposed design as implemented.
