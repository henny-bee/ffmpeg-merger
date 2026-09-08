import os
import uuid
import shutil
import subprocess
import httpx
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI()

class MergeRequest(BaseModel):
    video_url_1: str
    video_url_2: str

@app.get("/")
def home():
    return {"status": "FFmpeg API is running!"}

@app.post("/merge")
async def merge_videos(data: MergeRequest, background_tasks: BackgroundTasks):
    task_id = str(uuid.uuid4())
    work_dir = f"/tmp/{task_id}"
    os.makedirs(work_dir, exist_ok=True)

    v1_path = os.path.join(work_dir, "v1.mp4")
    v2_path = os.path.join(work_dir, "v2.mp4")
    list_path = os.path.join(work_dir, "list.txt")
    out_path = os.path.join(work_dir, "merged.mp4")

    try:
        
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            r1 = await client.get(data.video_url_1)
            if r1.status_code != 200:
                raise HTTPException(status_code=400, detail="Gagal mengunduh video 1")
            with open(v1_path, "wb") as f:
                f.write(r1.content)

            r2 = await client.get(data.video_url_2)
            if r2.status_code != 200:
                raise HTTPException(status_code=400, detail="Gagal mengunduh video 2")
            with open(v2_path, "wb") as f:
                f.write(r2.content)

        
        with open(list_path, "w") as f:
            f.write(f"file '{v1_path}'\nfile '{v2_path}'\n")

        
        cmd_copy = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", list_path, "-c", "copy", out_path
        ]
        res = subprocess.run(cmd_copy, capture_output=True, text=True)

        
        if res.returncode != 0:
            cmd_fallback = [
                "ffmpeg", "-y", "-i", v1_path, "-i", v2_path,
                "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]",
                "-map", "[v]", out_path
            ]
            res_fallback = subprocess.run(cmd_fallback, capture_output=True, text=True)
            if res_fallback.returncode != 0:
                raise HTTPException(status_code=500, detail=f"FFmpeg error: {res_fallback.stderr}")

        
        background_tasks.add_task(shutil.rmtree, work_dir, ignore_errors=True)

        return FileResponse(out_path, media_type="video/mp4", filename="merged.mp4")

    except Exception as e:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))