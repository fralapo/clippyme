"""Host tests for domain.smartcut_ops — the pure half of Smart Cut.

Focuses on _build_v3_timeline, which had ZERO coverage before the smartcut
decomposition: it maps keep-segments (seconds) onto an auto-editor v3 JSON
timeline (frames), and a rounding/offset bug there would silently produce a
mis-synced or empty render. The transcript/drop-range logic is exercised by
test_smartcut_manual_trim.py (which imports the same names via smartcut).
"""
import json
import os

from clippyme.editing import smartcut_ops as ops


_PROBE = {"fps_num": 30, "fps_den": 1, "width": 1080, "height": 1920, "samplerate": 48000}


# --- _build_v3_timeline -------------------------------------------------------

def test_v3_timeline_top_level_shape():
    tl = ops._build_v3_timeline("/clips/a.mp4", [(0.0, 1.0)], _PROBE)
    assert tl["version"] == "3"
    assert tl["timebase"] == "30/1"
    assert tl["resolution"] == [1080, 1920]
    assert tl["samplerate"] == 48000
    # v/a are each a single track (list of one clip-list).
    assert len(tl["v"]) == 1 and len(tl["a"]) == 1
    # Must be JSON-serialisable (it's written to a temp file for auto-editor).
    json.loads(json.dumps(tl))


def test_v3_timeline_frame_conversion_and_offsets():
    # 30fps: [0.5s, 1.5s) → offset 15 frames, dur 30 frames, output starts at 0.
    tl = ops._build_v3_timeline("/clips/a.mp4", [(0.5, 1.5)], _PROBE)
    clip = tl["v"][0][0]
    assert clip["offset"] == 15          # 0.5 * 30, source-relative
    assert clip["dur"] == 30             # 1.0s * 30
    assert clip["start"] == 0            # first clip lands at output frame 0
    assert clip["name"] == "video"
    # Absolutised, but the drive-letter form on Windows is not "/"-prefixed.
    assert clip["src"].endswith("a.mp4") and os.path.isabs(clip["src"])


def test_v3_timeline_output_positions_are_cumulative():
    # Two kept spans → the second clip's output `start` = first clip's dur,
    # while each `offset` stays source-relative (the bug this guards against is
    # output frames drifting or overlapping).
    tl = ops._build_v3_timeline("/clips/a.mp4", [(0.0, 1.0), (2.0, 2.5)], _PROBE)
    v = tl["v"][0]
    assert [c["start"] for c in v] == [0, 30]     # 0, then after a 30-frame clip
    assert [c["dur"] for c in v] == [30, 15]
    assert [c["offset"] for c in v] == [0, 60]    # 0s and 2.0s at 30fps
    # Audio track mirrors video frame-for-frame, only the name differs.
    a = tl["a"][0]
    assert [c["start"] for c in a] == [0, 30]
    assert all(c["name"] == "audio" for c in a)


def test_v3_timeline_drops_subframe_segments():
    # A span shorter than one frame (<1/30s here) rounds to 0 duration and must
    # be skipped, not emitted as a zero-length clip that auto-editor rejects.
    tl = ops._build_v3_timeline("/clips/a.mp4", [(0.0, 0.01), (0.0, 1.0)], _PROBE)
    assert len(tl["v"][0]) == 1
    assert tl["v"][0][0]["dur"] == 30


def test_v3_timeline_empty_segments_yield_empty_tracks():
    # The renderer keys on `timeline["v"][0]` being falsy to bail out before
    # spawning auto-editor — so no segments must give an empty track list.
    tl = ops._build_v3_timeline("/clips/a.mp4", [], _PROBE)
    assert tl["v"] == [[]]
    assert tl["a"] == [[]]


def test_v3_timeline_respects_fractional_fps():
    # 30000/1001 (29.97) timebase must be carried verbatim, and frame counts
    # computed from the derived float fps.
    probe = {**_PROBE, "fps_num": 30000, "fps_den": 1001}
    tl = ops._build_v3_timeline("/clips/a.mp4", [(0.0, 1.0)], probe)
    assert tl["timebase"] == "30000/1001"
    assert tl["v"][0][0]["dur"] == 30   # round(1.0 * 29.97)
