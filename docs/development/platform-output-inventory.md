# Platform output and publishing controls

Reviewed locally on 2026-10-14 against the Create, Edit, Publish and Settings
surfaces, the composition API, FFmpeg subtitle renderer and vendored Zernio
OpenAPI contract. This inventory records shipped behavior; it does not claim
that a human has reviewed representative videos.

| Output concern | Current control | Scope and finding |
|---|---|---|
| Aspect ratio | 9:16, 1:1 and 16:9 | Selected per job and honored by the renderer. There is no destination-specific override. The three current manual publishing destinations accept the selected short-form output; no evidence here justifies silently changing it per platform. |
| Subtitle placement | Shared top, center or bottom placement, alignment and vertical nudge | Rendered through ASS margins and composition geometry. Existing safe-zone placement accounts for common social controls; settings are shared across destinations. |
| Branding | Optional logo placement/size and source-platform attribution banner | Applied during composition with safe-zone and letterbox handling. These are explicit edit choices, not destination presets. |
| TikTok audience | Previously hard-coded to public | The account API exposes creator-specific privacy values, but the UI did not. The Publish modal now loads those values and lets the operator choose one. |
| TikTok interactions | Previously hard-coded on | The Publish modal now displays the account's supported comment, Duet and Stitch switches and submits the chosen values. |
| TikTok posting availability and duration | Not shown | The modal now blocks TikTok submission when creator info says the account cannot post more or a selected clip exceeds the account's maximum video duration. |

The app intentionally keeps subtitle, aspect and branding edits at the clip
level, where operators can preview/review them, rather than inferring a
destination-specific render profile. TikTok account-specific policy controls
are provider options and are therefore selected in the publishing step.
