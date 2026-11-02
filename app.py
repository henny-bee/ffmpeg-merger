from fastapi import FastAPI
from routers import merge, jointext, image_to_video, thumbnail, render

app = FastAPI()

app.include_router(merge.router)
app.include_router(jointext.router)
app.include_router(image_to_video.router)
app.include_router(thumbnail.router)
app.include_router(render.router)


@app.get("/")
def home():
    return {"status": "FFmpeg API is running!"}
