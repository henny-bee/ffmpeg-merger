import os
import re
import uuid
import shutil
import tempfile
import subprocess
from PIL import ImageFont

_WIN_FFMPEG_DIR = r"C:\Users\TiarNurAzhar\AppData\Local\hermes\tools\ffmpeg-9.0.1-win32-x64\bin"

FFMPEG_BIN = shutil.which("ffmpeg") or (
    os.path.join(_WIN_FFMPEG_DIR, "ffmpeg.exe")
    if os.path.exists(os.path.join(_WIN_FFMPEG_DIR, "ffmpeg.exe"))
    else "ffmpeg"
)

FFPROBE_BIN = shutil.which("ffprobe") or (
    os.path.join(_WIN_FFMPEG_DIR, "ffprobe.exe")
    if os.path.exists(os.path.join(_WIN_FFMPEG_DIR, "ffprobe.exe"))
    else "ffprobe"
)


def create_work_dir() -> str:
    work_dir = os.path.join(tempfile.gettempdir(), str(uuid.uuid4()))
    os.makedirs(work_dir, exist_ok=True)
    return work_dir


def load_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def check_has_audio(file_path: str) -> bool:
    cmd = [
        FFPROBE_BIN, "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "csv=p=0", file_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return "audio" in res.stdout


def get_video_duration(file_path: str) -> float:
    cmd = [
        FFPROBE_BIN, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    val = res.stdout.strip()
    if val and val != "N/A":
        try:
            return float(val)
        except ValueError:
            pass

    cmd = [
        FFPROBE_BIN, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return float(res.stdout.strip())
