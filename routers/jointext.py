import os
import shutil
import subprocess
import textwrap
import httpx
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from core.media import FFMPEG_BIN, create_work_dir
from schemas.requests import JoinTextRequest

router = APIRouter()


@router.post("/jointext")
async def join_text(data: JoinTextRequest, background_tasks: BackgroundTasks):
    work_dir = create_work_dir()
    input_img_path = os.path.join(work_dir, "input.jpg")
    output_img_path = os.path.join(work_dir, "output.jpg")
    text_file_path = os.path.join(work_dir, "text.txt")

    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(data.image_url)
            if resp.status_code != 200:
                raise HTTPException(status_code=400, detail="Gagal mengunduh gambar")
            with open(input_img_path, "wb") as f:
                f.write(resp.content)

        lines = data.text.split("\n")
        wrapped_lines = []
        for line in lines:
            if line.strip():
                wrapped_lines.extend(textwrap.wrap(line, width=data.max_chars_per_line))
            else:
                wrapped_lines.append("")

        with open(text_file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(wrapped_lines))

        drawtext_filter = (
            f"drawtext=textfile='{text_file_path}':"
            f"fontsize={data.font_size}:"
            f"fontcolor={data.font_color}:"
            f"borderw={data.border_width}:"
            f"bordercolor={data.border_color}:"
            f"line_spacing=12:"
            f"x=(w-text_w)/2:"
            f"y={data.y_position}"
        )

        cmd = [
            FFMPEG_BIN, "-y",
            "-i", input_img_path,
            "-vf", drawtext_filter,
            output_img_path
        ]

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise HTTPException(status_code=500, detail=f"FFmpeg text error: {res.stderr}")

        background_tasks.add_task(shutil.rmtree, work_dir, ignore_errors=True)
        return FileResponse(output_img_path, media_type="image/jpeg", filename="captioned.jpg")

    except HTTPException:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))
