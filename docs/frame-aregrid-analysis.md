# Comparative analysis: `aregrid/frame` → ClippyMe

Date: 2026-06-17
External repo: <https://github.com/aregrid/frame> @ `main` (single commit `38c5e2b`)
Homepage: <https://cursorfor.video/> · Author: Terry Zhang `<terry@llamagen.ai>`
Fifth external study, after `gauravzazz/smart-reframe`,
`KazKozDev/auto-vertical-reframe`, `obi19999/smart-video-reframe`, and
`mfahsold/montage-ai`.

---

## 0. Verdict up front

**`aregrid/frame` is an announcement-only repository — there is no source code
to study or port.** It markets itself as "an open-source alternative to Video
Cut … a Cursor-level interactive experience" but the published tree is a
marketing README plus screenshots and an empty monorepo skeleton. No
implementation has been committed. This document records the due-diligence
finding and the (one) genuine learning, and explicitly makes **no code changes**
— honouring "Non riscrivere tutto" and the rule against fabricating value.

---

## 1. What the repo actually contains

Full tracked tree (one `main` branch, one commit):

| Path | Size | Substance |
|---|---|---|
| `README.md` | 2.1 KB | Marketing copy + feature bullets + 5 embedded screenshots |
| `public/*.png` | ~5.6 MB | 5 product screenshots (the only large assets) |
| `package.json` | 558 B | `version 1.0.0`, `test` script = `echo … && exit 1` |
| `packages/frame-{android,ios,web,backend,common,env}/README.md` | 5–9 B each | A bare `# heading` — **no package code** |
| `docker/README.md`, `scripts/README.md`, `test/{,unit/,e2e/}README.md`, `cookbook/README.md` | 8–18 B | Empty stubs (`# Docker`, `See Testing`, …) |
| `vercel.json` | 7 B | `{}` |
| `.node-version` | 3 B | `v18` |
| `LICENSE` | 1.1 KB | MIT |

Code files of any language (`.py/.js/.ts/.tsx/.go/.rs/…`): **none.**

The README advertises features that overlap ClippyMe — "Auto-clip videos based
on scene changes, audio peaks, or motion detection", "AI-driven color
correction", "face detection", a chat "Video Agent" — but **none are
implemented in the repo.** They describe the closed product at
`cursorfor.video`, not open source here.

---

## 2. Comparison to ClippyMe

There is nothing to compare structurally — ClippyMe ships a working FastAPI
backend, a reframe pipeline with host-tested pure-math (`reframe_ops.py`), a
React dashboard, Docker, and a real test suite; `aregrid/frame` ships a README.
The only comparison worth recording is **product positioning**: both target
AI-assisted video editing, but `frame`'s differentiators ("Cursor-level"
conversational timeline editing, multi-platform desktop/mobile apps) are
aspirational marketing, not shipped behaviour.

---

## 3. Prioritised improvement list

| Pri | Improvement | Status | Notes |
|---|---|---|---|
| — | (none portable) | n/a | No source exists to adopt patterns from. |
| Low | Idea-only: "auto-clip on audio peaks / motion" as a non-Gemini clip-finder | ⏸ noted | ClippyMe already detects viral moments via Gemini + PySceneDetect. An audio-peak/motion heuristic could be a cheap, offline pre-filter, but `frame` provides zero implementation guidance — this is a generic idea, not a port. Deferred. |

No High/Medium items: a stub repo yields no concrete techniques, configs, error
handling, or tests to learn from.

---

## 4. What was implemented

**Nothing.** There is no upstream code to port, and inventing changes merely to
populate the "implementation" deliverable would violate the verification /
honesty discipline and the "Non riscrivere tutto" instruction. The four prior
studies (smart-reframe, auto-vertical-reframe, smart-video-reframe, montage-ai)
each had real source and produced real, tested ports; this one correctly
produces none.

---

## 5. Learnings & how they were applied

1. **Due-diligence before deep study.** The "open-source AI video editor" space
   contains announcement-first repos that publish a polished README and
   screenshots ahead of (or instead of) code. Before committing to an
   architecture deep-dive, verify substance: `git ls-files` + per-file byte
   counts + a code-extension grep takes seconds and prevents fabricating
   analysis of an empty tree. *Applied here:* the study was scoped down to a
   one-paragraph verdict the moment the file census showed 0 code files.
2. **A negative result is a valid deliverable.** "There is nothing to port, and
   here is the evidence" is an honest, useful outcome — better than padding the
   four required deliverables with invented improvements. *Applied here:* no
   code, test, or `CLAUDE.md` changes were made; this document is the deliverable.
3. **Marketing features ≠ implemented features.** `frame`'s feature list reads
   as a superset of ClippyMe, but none is backed by code. A feature comparison
   table built from a README alone would have been misleading.

---

## 6. Verification

- File census: `git ls-files` → 26 tracked files, 0 with a code extension; all
  `packages/*/README.md` are 5–9 bytes; `vercel.json` = `{}`.
- Branches: only `main`; single commit `38c5e2b "chore: move some basic configs"`.
- No ClippyMe files changed → existing test suite unaffected (host
  `pytest -m "not integration"` baseline remains **248 passed, 2 skipped** from
  the round-4 study; not re-run because nothing in the repo changed).
