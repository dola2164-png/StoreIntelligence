import cv2
from pathlib import Path

# Resolve video path relative to this script for robust behavior
video_path = Path(__file__).resolve().parent / "data" / "CAM 1.mp4"
print("Trying video:", video_path)
cap = cv2.VideoCapture(str(video_path))
opened = cap.isOpened()
print("Opened?", opened)
if not opened:
	print("Error: failed to open video. Check that the file exists and the path is correct.")
