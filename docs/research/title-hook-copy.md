# Title & hook copywriting — research behind the Gemini prompt

> Research note — not current documentation. See [the research index](README.md).

Why the prompt writes titles the way it does. Feedback from the streamers whose
lives we clip was blunt: the titles were *summaries*. "Trova una moneta rara"
describes the clip and gives nobody a reason to comment. What they asked for is
the American clip-account register — playful, overstated, argument-starting
("Reda smetterà di fare live dopo aver trovato un cimelio da 10k") — which
almost nobody does in Italy yet.

This is what the research says that register can and cannot be.

## The policy boundary (this shapes every formula)

- YouTube prohibits **malicious clickbait**: "using maliciously misleading
  titles, thumbnails, descriptions, or imagery to trick users into clicking."
  Canonical failure: a title promising a full match over a video that only has
  a clip. Enforcement is warning → strike → termination at 3/90 days.
  <https://support.google.com/youtube/answer/2801973?hl=en>
- The operative test is **delivery, not literalness**: click → does the viewer
  get what was promised? Hyperbole that resolves inside the clip passes; a
  promised event that never happens fails.
  <https://1of10.com/blog/clickbait-thumbnail/>
- TikTok treats **engagement bait** as an integrity violation that makes the
  post **ineligible for the For You feed** — "Like this if you agree", "Comment
  your birth month and I'll…", "Follow me and I'll follow back", "Only 10% can
  answer this".
  <https://www.tiktok.com/community-guidelines/en/fyf-standards>
- Meta demotes vote/comment bait but **explicitly exempts genuine asks for
  opinion, advice or help**.
  <https://transparency.meta.com/features/approach-to-ranking/content-distribution-guidelines/engagement-bait/>

**Net rule encoded in the prompt:** provoke the comment *implicitly* — a claim
people want to correct, a stake they want to judge. Never *mechanically*. The
prompt used to REQUIRE the mechanical form ("ALWAYS include a CTA like 'Follow
me and comment X and I'll send you the workflow'"); that instruction was
shipping every clip into the demoted bucket and has been removed.

## What actually drives comments

- **Cunningham's law** — people correct a wrong answer far faster than they
  answer a question. A debatable valuation or a judgement call outperforms an
  open question. Constraint: keep it a *judgement*, never a fabricated fact
  about a person, health, money or news.
  <https://gobraithwaite.com/thinking/what-is-cunninghams-law-wrong-answers-only/>
- **Open loops, identity, stakes** are the three retention drivers; reveal the
  end state and hide the process ("okay, but *how*?").
  <https://faceless.so/blog/25-hook-formulas-to-boost-short-video-watch-time>
- The hook must land in **1–3s** (~45% leave before 3s), and **two** triggers
  beat one — three reads as spam.
  <https://www.opus.pro/blog/tiktok-hook-formulas>
- **Prediction comments** are the highest-engagement comment class; specific
  prompts beat generic ones.
  <https://www.opus.pro/blog/short-form-video-strategy-2026>
- For streamer clips specifically: fast hook, a genuine emotional reaction, and
  a moment that stands alone without the stream. Titles should be
  moment-specific and searchable, not "momenti epici".
  <https://www.clipspeed.ai/blog/clipping-twitch-streamers-youtube-shorts.html>

## What makes a moment clippable (the selection gate)

Practitioner consensus from clipping operators (SERVIUOS, ~25k-clipper Discord;
Nashifys; Joe Sbiti) — a moment earns a clip only if it hits one of four
things, and the rest of the editing is secondary to that judgement:

- **Unexpected turn** — plot twist / pattern interrupt; retention comes from
  the surprise, not the topic.
- **Strong emotion or polarization** — the share test is "would this get sent
  to a friend / dropped in a group chat". A take half the audience wants to
  argue with beats one everyone agrees with, because arguing is a comment.
- **Relatability** — "this is literally me", specific and everyday.
- **New or useful info** — save-worthy; the save is itself a ranking signal.

Two mechanics ride with it: the hook must land in the first 1–3s (a moment
whose best beat is at 0:20 is a bad clip even if the beat is great), and dead
air is the single biggest retention killer — the reaction beat after the
reveal is *part* of the clip, the silence before it is not.

Encoded in `GEMINI_PROMPT_TEMPLATE` as the `## IS THIS MOMENT EVEN WORTH
CUTTING?` gate, deliberately placed **before** the rubric: the rubric only
ranks moments that already cleared the gate. It pairs with the live monitor's
`clip_selection: auto` floor — both exist so a weak segment yields fewer clips
instead of padding the quota.

Not adopted: those workflows also lean on manual per-clip music beds, sound
effects and CapCut styling — out of scope for an automated pipeline.

## Italian register

- Always `tu` / `voi`, never `lei`; the informal, near-improvised register is
  the norm and corporate phrasing reads as an ad.
  <https://www.mysocialweb.it/copywriting-social-media/>
- `voi` is the pronoun that pulls replies ("voi l'avreste venduta?", "ditemi
  che sbaglio").
- CAPS on one or two words as emphasis, never the whole line; emoji as
  separators, not decoration.
  <https://www.bee-social.it/scrittura-social-microcopy-ads/>
- Use the handle the audience actually uses, never a legal name. Lead with the
  name only when the streamer is the draw — otherwise the moment goes first.

## Where this lives in the code

`pipeline/analysis/gemini_request.py` → `GEMINI_PROMPT_TEMPLATE`, section
`## TITLE & CAPTION COPY`: the nine rules and the rotating pattern list are a
direct encoding of the above. Two guards ride with it:

- **Grounding rule** — exaggerate the framing, never invent the event (the
  delivery test).
- **Speaker attribution** — the live monitor passes the channel owner as
  `CLIPPYME_CREATOR_NAME`, which lets a title name *whose stream this is*, but
  never puts a quote in their mouth: guests and co-streamers share the mic and
  the transcript carries no speaker identity.
