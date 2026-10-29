from typing import Optional
from pydantic import BaseModel


class MergeRequest(BaseModel):
    video_url_1: str
    video_url_2: Optional[str] = None
    music_url: Optional[str] = None
    music_volume: float = 1.0
    video_volume: float = 1.0


class JoinTextRequest(BaseModel):
    image_url: str
    text: str
    max_chars_per_line: Optional[int] = 30
    font_size: Optional[int] = 42
    font_color: Optional[str] = "white"
    border_color: Optional[str] = "black"
    border_width: Optional[int] = 5
    y_position: Optional[str] = "h*0.22"


class ImageToVideoRequest(BaseModel):
    image_url: str
    duration: float = 9.0
    fps: int = 30
    width: int = 1080
    height: int = 1920


class ThumbnailRequest(BaseModel):
    video_url: Optional[str] = None
    image_url: Optional[str] = None
    logo_url: Optional[str] = None
    text: str
    source: Optional[str] = None
    timestamp: float = 0.0
    font_size: int = 49
    upscale: bool = True
    output_format: str = "jpg"
