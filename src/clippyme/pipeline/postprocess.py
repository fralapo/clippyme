"""FFmpeg-based per-clip post-processing (audio normalize + Ken Burns zoom).

Extracted from ``pipeline.main`` as part of the decomposition: these stages use
only ``subprocess``/``os``/``json`` (no cv2/torch), so the module imports and is
exercisable on the host. cv2-dependent post-processing (cover-frame selection)
stays in ``main`` until it can be verified against the Docker integration suite.

Both functions operate **in place**: they render to a temp file next to the
input and atomically replace it, leaving the original untouched on any failure.
"""
import json
import os
import subprocess


def normalize_audio(video_path):
    """
    Two-pass EBU R128 loudness normalization to -14 LUFS (social media standard).
    Normalizes in-place by creating a temp file and replacing.
    """
    temp_out = video_path + ".norm.mp4"
    try:
        # Pass 1: Analyze
        analyze_cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-af', 'loudnorm=I=-14:TP=-1.5:LRA=7:print_format=json',
            '-f', 'null', os.devnull
        ]
        result = subprocess.run(analyze_cmd, capture_output=True, text=True)
        # Parse measured values from stderr (loudnorm outputs JSON at the end)
        stderr = result.stderr
        json_start = stderr.rfind('{')
        json_end = stderr.rfind('}') + 1
        if json_start < 0 or json_end <= json_start:
            print("⚠️  Audio normalization: could not parse loudnorm analysis, skipping")
            return
        measured = json.loads(stderr[json_start:json_end])

        # Pass 2: Apply
        apply_cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-af', (
                f"loudnorm=I=-14:TP=-1.5:LRA=7"
                f":measured_I={measured['input_i']}"
                f":measured_TP={measured['input_tp']}"
                f":measured_LRA={measured['input_lra']}"
                f":measured_thresh={measured['input_thresh']}"
                f":offset={measured['target_offset']}"
                f":linear=true"
            ),
            '-c:v', 'copy',
            '-c:a', 'aac', '-b:a', '192k',
            temp_out
        ]
        norm_result = subprocess.run(apply_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if norm_result.returncode == 0 and os.path.exists(temp_out):
            os.replace(temp_out, video_path)
            print(f"🔊 Audio normalized to -14 LUFS: {os.path.basename(video_path)}")
        else:
            print(f"⚠️  Audio normalization failed, keeping original audio")
            if os.path.exists(temp_out):
                os.remove(temp_out)
    except Exception as e:
        print(f"⚠️  Audio normalization error: {e}")
        if os.path.exists(temp_out):
            os.remove(temp_out)


def apply_subtle_zoom(video_path, zoom_end=1.05):
    """
    Apply a subtle Ken Burns zoom (1.0x → zoom_end over the clip duration).
    Creates visual motion even on static shots, improving viewer retention.
    Operates in-place.
    """
    temp_out = video_path + ".zoom.mp4"
    try:
        # Get video info
        probe = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=width,height,r_frame_rate,nb_frames',
             '-of', 'csv=s=x:p=0', video_path],
            capture_output=True, text=True
        )
        parts = probe.stdout.strip().split('x')
        if len(parts) < 3:
            return
        w, h = int(parts[0]), int(parts[1])
        # r_frame_rate is like "30/1" or "30000/1001"
        fps_parts = parts[2].split('/')
        fps = int(fps_parts[0]) / int(fps_parts[1]) if len(fps_parts) == 2 else float(fps_parts[0])
        total_frames = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0

        if total_frames <= 0 or fps <= 0:
            return

        # Zoom increment per frame: from 1.0 to zoom_end over total_frames
        zoom_per_frame = (zoom_end - 1.0) / total_frames

        zoom_filter = (
            f"zoompan=z='1+{zoom_per_frame:.8f}*on'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:s={w}x{h}:fps={fps}"
        )

        cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-vf', zoom_filter,
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'fast', '-crf', '23',
            '-c:a', 'copy', temp_out
        ]
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if result.returncode == 0 and os.path.exists(temp_out):
            os.replace(temp_out, video_path)
            print(f"🔍 Subtle zoom applied (1.0→{zoom_end}x): {os.path.basename(video_path)}")
        else:
            if os.path.exists(temp_out):
                os.remove(temp_out)
    except Exception as e:
        print(f"⚠️  Subtle zoom failed (non-critical): {e}")
        if os.path.exists(temp_out):
            os.remove(temp_out)
