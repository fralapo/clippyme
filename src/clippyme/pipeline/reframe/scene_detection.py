"""Scene detection + video-resolution probes.

Extracted from ``pipeline.main``. Depends on PySceneDetect + cv2 only (no
YOLO/mediapipe), so it imports on a host that has those wheels. The
face/person/saliency scene *strategy* analysis stays in ``main`` because it
pulls YOLO + MediaPipe, which can only be verified in the Docker image.
"""
import cv2
from scenedetect import SceneManager, open_video
from scenedetect.detectors import ContentDetector


def detect_scenes(video_path):
    # PySceneDetect v0.6+ API — VideoManager was removed. `open_video` returns
    # a VideoStream that SceneManager consumes directly.
    video = open_video(video_path)
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector())
    scene_manager.detect_scenes(video=video)
    scene_list = scene_manager.get_scene_list()
    fps = video.frame_rate
    return scene_list, fps


def get_video_resolution(video_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"Could not open video file {video_path}")
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return width, height
