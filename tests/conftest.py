"""Shared pytest configuration.

Some test modules import ``clippyme.pipeline.main`` (and transitively
``ultralytics`` / ``cv2`` / ``mediapipe``) at module load time. Those modules
are marked ``@pytest.mark.integration`` so they only run in the Docker image
that ships the heavy CV/ML runtime — but a marker cannot stop a *collection*
import error: on a host without those wheels, pytest fails to import the module
before the marker is ever consulted, which breaks even ``-m "not integration"``.

We skip collecting those modules when the heavy runtime is unavailable so the
host suite (``pytest -m "not integration"``) stays green. In Docker, where the
wheels are present, the modules collect and run normally.
"""
import importlib.util

# Heavy deps that the pipeline integration tests import at module load.
_HEAVY_DEPS = ("ultralytics", "cv2", "mediapipe", "scenedetect")


def _heavy_runtime_available() -> bool:
    if not all(importlib.util.find_spec(dep) is not None for dep in _HEAVY_DEPS):
        return False
    # Presence isn't enough: main.py uses the legacy ``mediapipe.solutions`` API
    # (pinned 0.10.14). Newer host wheels (e.g. 0.10.35, the only one with a
    # Windows build) drop that attribute, so collecting the pipeline tests would
    # crash on import. Treat a wrong-API mediapipe as "runtime unavailable" so
    # the host suite stays green; the Docker image (0.10.14) passes this check.
    try:
        import mediapipe  # noqa: PLC0415
        return hasattr(mediapipe, "solutions")
    except Exception:
        return False


# When the runtime is missing, don't even try to collect the pipeline tests
# that import it at the top level.
collect_ignore_glob = []
if not _heavy_runtime_available():
    collect_ignore_glob.append("pipeline/test_main_*.py")
