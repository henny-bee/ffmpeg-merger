import os
import shutil
import subprocess
import httpx
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from core.media import FFMPEG_BIN, create_work_dir
from schemas.requests import ImageToVideoRequest

router = APIRouter()


@router.post("/image-to-video")
async def image_to_video(data: ImageToVideoRequest, background_tasks: BackgroundTasks):
    work_dir = create_work_dir()
    input_img_path = os.path.join(work_dir, "input.jpg")
    output_mp4_path = os.path.join(work_dir, "output.mp4")

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True, headers=headers) as client:
            resp = await client.get(data.image_url)
            if resp.status_code != 200:
                raise HTTPException(status_code=400, detail="Gagal mengunduh gambar")
            with open(input_img_path, "wb") as f:
                f.write(resp.content)

        vf_filter = (
            f"scale={data.width}:{data.height}:force_original_aspect_ratio=decrease,"
            f"pad={data.width}:{data.height}:(ow-iw)/2:(oh-ih)/2,"
            f"setsar=1,"
            f"fps={data.fps},"
            f"format=yuv420p"
        )

        cmd = [
            FFMPEG_BIN, "-y",
            "-loop", "1",
            "-t", str(data.duration),
            "-i", input_img_path,
            "-f", "lavfi",
            "-t", str(data.duration),
            "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-vf", vf_filter,
            "-c:v", "libx264",
            "-tune", "stillimage",
            "-preset", "ultrafast",
            "-crf", "20",
            "-threads", "2",
            "-c:a", "aac",
            "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            output_mp4_path
        ]

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise HTTPException(status_code=500, detail=f"FFmpeg image-to-video error: {res.stderr}")

        background_tasks.add_task(shutil.rmtree, work_dir, ignore_errors=True)
        return FileResponse(output_mp4_path, media_type="video/mp4", filename=f"video_hd_{int(data.duration)}s.mp4")

    except HTTPException:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))
