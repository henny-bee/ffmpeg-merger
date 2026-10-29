import os
import gc
import re
import uuid
import shutil
import tempfile
import subprocess
import numpy as np
import onnxruntime as ort
from PIL import Image, ImageFont

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_ESRGAN_ONNX = os.path.join(_BASE_DIR, "models", "realesr-animevideov3.onnx")

FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE_BIN = os.getenv("FFPROBE_BIN", "ffprobe")


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


def upscale_to_720p(img: Image.Image) -> Image.Image:
    if not os.path.exists(REAL_ESRGAN_ONNX):
        return img.resize((1280, 720), Image.Resampling.LANCZOS)

    rgb = img.convert("RGB")
    if rgb.width > 720:
        rgb = rgb.resize((720, 405), Image.Resampling.LANCZOS)

    arr = np.asarray(rgb, dtype=np.float32) / 255.0
    h, w, _ = arr.shape
    mid = w // 2
    pad = 16

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 2
    opts.inter_op_num_threads = 1
    opts.enable_cpu_mem_arena = False
    sess = ort.InferenceSession(REAL_ESRGAN_ONNX, sess_options=opts, providers=["CPUExecutionProvider"])

    try:
        # Proses 2 tile (kiri & kanan) supaya puncak pemakaian RAM di VM 4GB tetap rendah
        t1 = np.transpose(arr[:, :mid + pad, :], (2, 0, 1))[None, ...]
        o1 = sess.run(["output"], {"input": t1})[0][0, :, :, :mid * 4]

        t2 = np.transpose(arr[:, mid - pad:, :], (2, 0, 1))[None, ...]
        o2 = sess.run(["output"], {"input": t2})[0][0, :, :, pad * 4:]

        merged = np.concatenate([o1, o2], axis=2)
        out_arr = np.clip(np.transpose(merged, (1, 2, 0)) * 255.0, 0, 255).astype(np.uint8)
        return Image.fromarray(out_arr).resize((1280, 720), Image.Resampling.LANCZOS).convert("RGBA")
    finally:
        del sess
        gc.collect()
