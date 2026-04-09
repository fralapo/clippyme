"""Regression tests for bugs identified in main.py review.

Each test is tagged with the bug number from the plan so failures are
traceable. Run inside the Docker backend image (host typically lacks
the cv2/mediapipe/yt-dlp runtime deps).
"""
import os
import pytest
