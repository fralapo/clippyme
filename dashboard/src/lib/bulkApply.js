// Pure helpers for applying one clip's edit settings to many clips — used by
// the per-card "Apply to all" button and the multi-select bulk editor.
//
// Two rules the UI promised the user:
//   1. The *manual transcript trim* (drop_ranges) is per-clip content — it is
//      NEVER copied across clips. A bulk apply always sends an empty drop list.
//   2. The *hook text* is per-clip content too (Gemini suggests a different
//      opener per clip). A bulk apply keeps each target's own hook text and
//      only copies the hook STYLE (colour / outline / banner / font / size).
//
// Everything else (reframe mode, smart-cut toggle, subtitle params, hook
// style, logo params) is shared config and is copied verbatim.
//
// Kept dependency-free + pure so it can be host-unit-tested with node:test.
import { seedToggles, seedHookParams, seedSubtitleParams, seedLogoParams } from './seedClipParams.js';

/**
 * Collapse a clip's saved per-clip state (which may be empty if the clip was
 * never edited) into the shared `params` shape reprocessClip expects. Falls
 * back to the global pre-selection seeds so an unedited source clip still
 * carries the user's defaults.
 *
 * @param {object|undefined} state  clipStates[idx]
 * @param {object|undefined} preselections
 * @param {object} clip
 */
export function clipStateToParams(state, preselections, clip) {
  return {
    reframeMode: state?.reframeMode || clip?.reframe_mode || 'auto',
    toggles: state?.toggles || seedToggles(preselections),
    subtitleParams: state?.subtitleParams || seedSubtitleParams(preselections),
    hookParams: state?.hookParams || seedHookParams(clip, preselections),
    logoParams: state?.logoParams || seedLogoParams(preselections),
  };
}

/**
 * The target clip's own hook text (preserved across a bulk apply), falling back
 * to the Gemini suggestion, then to the source text if neither exists.
 */
function targetHookText(srcParams, targetClip, targetState) {
  return (
    targetState?.hookParams?.text ||
    targetClip?.viral_hook_text ||
    targetClip?.hook_text ||
    srcParams?.hookParams?.text ||
    ''
  );
}

/**
 * Build the full reprocess params for ONE target clip from shared source
 * params, honouring the two per-clip exclusions (drop_ranges + hook text).
 *
 * @param {object} srcParams  output of clipStateToParams / the modal's staged params
 * @param {object} targetClip clips[i]
 * @param {object|undefined} targetState clipStates[i]
 * @returns params for reprocessClip (with baseMode for the reframe diff)
 */
export function buildClipParams(srcParams, targetClip, targetState) {
  const baseMode = targetState?.reframeMode || targetClip?.reframe_mode || 'auto';
  return {
    reframeMode: srcParams.reframeMode,
    baseMode,
    toggles: { ...srcParams.toggles },
    subtitleParams: { ...srcParams.subtitleParams },
    // Copy the hook STYLE but keep this clip's own text.
    hookParams: { ...srcParams.hookParams, text: targetHookText(srcParams, targetClip, targetState) },
    logoParams: { ...srcParams.logoParams },
    // Manual trim is never propagated.
    dropRanges: [],
  };
}

/**
 * Build a {idx, clip, params} plan for applying `srcParams` to every target in
 * `targets` (each `{ i, c }`), skipping `skipIdx` (the source clip itself).
 *
 * @param {object} srcParams
 * @param {Array<{i:number, c:object}>} targets
 * @param {object} clipStates
 * @param {number} [skipIdx]
 */
export function buildBulkPlan(srcParams, targets, clipStates = {}, skipIdx = -1) {
  return targets
    .filter(({ i }) => i !== skipIdx)
    .map(({ i, c }) => ({ idx: i, clip: c, params: buildClipParams(srcParams, c, clipStates[i]) }));
}
