"""图片 EXIF 提取（时间 / GPS），失败安全返回空（纯函数，IO 仅读内存字节）。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.core.config import settings


def _to_degrees(value) -> Optional[float]:
    """将 EXIF GPS 的 (度,分,秒) rational 元组转为十进制度数。"""
    try:
        d = float(value[0][0]) / float(value[0][1])
        m = float(value[1][0]) / float(value[1][1])
        s = float(value[2][0]) / float(value[2][1])
        return d + (m / 60.0) + (s / 3600.0)
    except Exception:
        return None


def extract_exif(image_bytes: bytes) -> dict:
    """提取 EXIF 时间与 GPS。

    返回 {"datetime": datetime|None, "gps": "lat,lng"|None}；解析失败均返回 None。
    """
    result: dict = {"datetime": None, "gps": None}
    try:
        from PIL import Image
        from PIL.ExifTags import GPSTAGS, TAGS

        img = Image.open(__import__("io").BytesIO(image_bytes))
        exif = getattr(img, "_getexif", lambda: None)()
        if not exif:
            return result

        exif_dict = {TAGS.get(k, k): v for k, v in exif.items()}

        # 时间
        dt_raw = exif_dict.get("DateTimeOriginal") or exif_dict.get("DateTime")
        if dt_raw:
            try:
                result["datetime"] = datetime.strptime(str(dt_raw), "%Y:%m:%d %H:%M:%S")
            except Exception:
                result["datetime"] = None

        # GPS
        gps_info = exif_dict.get("GPSInfo")
        if gps_info and isinstance(gps_info, dict):
            gps = {GPSTAGS.get(k, k): v for k, v in gps_info.items()}
            lat = _to_degrees(gps.get("GPSLatitude"))
            lng = _to_degrees(gps.get("GPSLongitude"))
            if lat is not None and lng is not None:
                if gps.get("GPSLatitudeRef") == "S":
                    lat = -lat
                if gps.get("GPSLongitudeRef") == "W":
                    lng = -lng
                result["gps"] = f"{lat:.6f},{lng:.6f}"
    except Exception:
        # 任何解析异常均兜底为空，不阻塞发布
        return {"datetime": None, "gps": None}
    return result
