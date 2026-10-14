# Editorial quality review

This review complements `tests/pipeline/quality/`: FFprobe/FFmpeg can check
duration, aspect ratio, black/frozen frames and audio levels, but they cannot
decide whether a cut preserves a thought or a hook pays off.

## Sample set

Use at least three source videos in each group before drawing conclusions:

1. Talking head
2. Multi-speaker podcast or interview
3. Gameplay
4. Screen capture or tutorial
5. No-face footage or B-roll

For each source, keep the source and generated exports together outside the
repository. Record a stable local sample ID, content class, source duration,
language, ClippyMe commit, selected settings and generated clip filenames.
Do not put source URLs, transcripts, titles, faces or media in Git. Reviewers
must be allowed to use the source material.

## Rating form

Rate each generated clip from 1 (unusable) to 5 (ready to publish):

| Dimension | Review question |
|---|---|
| Narrative coherence | Does the clip preserve a complete, understandable thought or event? |
| Hook payoff | Does the opening earn attention and does the clip deliver what it promises? |
| Cut and pacing | Are starts, endings and internal cuts natural for this content type? |
| Subject framing | Is the speaker, gameplay action, screen content or relevant scene kept visible? |
| Caption readability | Are captions accurate, timed to speech and clear of important on-screen content? Mark N/A when captions are off. |
| Attribution and audio | Are speakers attributed correctly, and is speech audible without clipping? |

Record one concrete defect for every rating below 4. Label defects as
`selection`, `cut`, `hook`, `framing`, `caption`, `audio`, or `other`; do not
rewrite a source transcript or retain free-form viewer information in the
evaluation report.

## Acceptance for a review round

- No critical error: fabricated attribution, a materially misleading hook,
  or an export that omits the promised speech/action.
- The median for narrative coherence, framing and caption readability is at
  least 4/5 in each applicable content class.
- Hook payoff and cut/pacing medians are at least 3/5 in each content class.
- Publish-ready rate and the most common defect are reported per class; do not
  combine all five classes into one average that hides a weak category.

If a class misses a threshold, keep its failed sample IDs and defect categories
for a focused follow-up. Re-run the same settings after a change and compare
the same samples before claiming improvement. Automated signal-QA results are
reported separately and never substitute for these ratings.

## Current status

No representative media samples are included in the checkout, and this review
does not invent editorial results from synthetic test video. The rubric is
ready; the evaluation remains open until real, permitted samples are supplied
and reviewed.
