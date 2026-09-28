# VideoLingo analysis

> Research note — not current documentation. See [the research index](README.md).

Source: [Huanshere/VideoLingo](https://github.com/Huanshere/VideoLingo) — "Hyper-localize videos: end-to-end subtitle translation + dubbing."

Evaluated against ClippyMe to decide what (if anything) is worth porting. Verdict up front: **VideoLingo is a translation/dubbing tool — a different product from ClippyMe (viral vertical shorts). Almost everything overlaps with something ClippyMe already does better, except one transferable idea: semantic subtitle line-splitting.** That idea is now ported (see below) as a pure, dependency-free engine.

## What VideoLingo is

| Aspect | VideoLingo |
|---|---|
| Goal | Localize a long video into another language: translate + dub, then re-mux |
| Runtime | Python + Streamlit one-click app |
| ASR | WhisperX (word-level timestamps + alignment) |
| Subtitle segmentation | spaCy NLP + an LLM "meaning" split into Netflix single-line captions |
| Translation | 3-step translate → reflect → adapt, with custom/AI terminology glossaries |
| Dubbing | TTS (GPT-SoVITS / Azure / OpenAI / edge-TTS) + duration-aligned re-mux |
| Pipeline | numbered stages `_1_ytdlp … _12_dub_to_vid`, resumable |

## Capability-by-capability vs ClippyMe

| Capability | VideoLingo | ClippyMe | Winner |
|---|---|---|---|
| Download | yt-dlp | yt-dlp (+ Deno bot-bypass, cookies, cache) | **ClippyMe** |
| ASR | WhisperX local | Deepgram Nova-3 cloud (EN+IT code-switch) + faster-whisper fallback, audio-only FLAC, URL-cached | **ClippyMe** |
| Terminology consistency | custom + AI glossary | Deepgram `DEEPGRAM_KEYTERMS` (brand/jargon boost, Nova-3) | tie — same idea, different layer |
| Pause / resume / stop | Streamlit task control | `job_control` state machine (psutil process-tree suspend, graceful stop keeps clips) | **ClippyMe** |
| **Subtitle line-splitting** | spaCy clause/connector/mark split → Netflix single-line | **was blind** — fixed N-words or char-cap only, cuts mid-clause | **VideoLingo** → **ported** |
| Translation (cross-language) | ✅ core feature | ❌ none (shorts stay in source language) | **VideoLingo** — but out of scope |
| Dubbing / TTS | ✅ core feature | ❌ none | **VideoLingo** — out of scope |
| 9:16 reframe | none | YOLOv8 + MediaPipe, comfort mode, global-smooth | **ClippyMe** |
| Viral moment detection | none | Gemini 5-axis rubric | **ClippyMe** |
| Publishing | none | Zernio multi-platform + SmartScheduler | **ClippyMe** |

### Why translation/dubbing are *not* worth porting

ClippyMe's product is **viral vertical shorts**, kept in the creator's own voice and language (EN+IT). Translation and TTS dubbing serve a different goal (reaching a foreign-language audience) and would drag in a large dependency + cost surface (an LLM translate/reflect/adapt loop, a TTS backend, duration-stretch re-muxing) for a feature the shorts workflow doesn't ask for. Out of scope by product design, not by capability.

## The one idea worth taking — semantic subtitle splitting

VideoLingo's genuine differentiator is `core/spacy_utils/`: a battery of splitters (`split_by_mark`, `split_by_comma`, `split_by_connector`, `split_long_by_root`) whose only job is to break a transcript into caption lines that end at **natural language boundaries** — sentence marks, clause punctuation, and *before* coordinating/subordinating connectors — so a subtitle line never cuts mid-phrase. This is the "Netflix single-line" readability standard.

ClippyMe's caption grouping (`subtitles.py:_group_words` / `_group_words_by_count`) split **blind**: every-N-words for karaoke, or a flat char/duration cap for full lines. On real speech that produces lines like `the very | best of | all time` or two sentences sharing one karaoke line — readable, but visibly worse than a clause-aware split on a fast-moving vertical video.

**Pros of adding it**
- Direct readability win on the most-watched surface (burned-in captions on a 9:16 short).
- Composes with everything — same word-timestamp inputs, same ASS/SRT output, just smarter break points.
- **No new dependency.** VideoLingo needs spaCy because WhisperX hands it raw text; ClippyMe's Deepgram `smart_format` (and Whisper) already attach punctuation to each word token, so the same boundaries are found with a pure lexical pass.

**Cons / why it stayed scoped to a lexical port**
- VideoLingo's spaCy version uses POS/dependency tags (e.g. only split `that` when it's a clause marker, skip relative pronouns acting as determiners). A lexical pass can't see POS, so it leans on a soft-length guard instead: a connector only triggers a break once the line is already substantial. Slightly less precise, but zero model load and good enough for short captions.
- An LLM "meaning" split (`_3_2_split_meaning.py`) was rejected outright — per-clip LLM calls just to place line breaks isn't worth the latency/cost on top of the Gemini viral pass.

## What was ported

`src/clippyme/editing/subtitles.py` — pure, host-unit-tested (`tests/domain/test_subtitle_split.py`), no spaCy / ffmpeg / model load:

- `_SUB_CONNECTORS` — coordinating/subordinating connectors in EN/IT/ES/FR/DE (mirrors ClippyMe's existing filler-word language coverage). Break happens *before* the connector (VideoLingo-style), so a new line opens on it.
- `_ends_sentence` / `_ends_soft` / `_is_connector` — glyph/lexeme predicates, tolerant of trailing quotes/brackets and accented Italian.
- `_group_words(...)` (full_line mode) — closes a line on a hard char/duration cap (unchanged ceiling), **always** on a sentence-final mark (never merges two sentences), and **preferentially** at a comma/clause mark or before a connector once the line passes a soft-length ratio.
- `_group_words_by_count(...)` (word_group karaoke mode) — keeps the punchy ~N-word feel but snaps the break to a sentence end, and lets a comma close a chunk one word early, so a fragment never straddles a period.
- `generate_srt(...)` (legacy SRT path) — same sentence-final early-close rule, for consistency.

All three rendering paths (`generate_ass_karaoke` full-line + word-group, and `generate_srt`) now break at language boundaries. Output is byte-identical on input with no internal punctuation/connectors (e.g. a single short phrase), so the change only ever *improves* a line that would otherwise have cut mid-clause — a net-positive, like the reframe weighted-object follow.
