# -*- coding: utf-8 -*-
"""
images_to_pdf.py - รวมรูปภาพเป็นไฟล์ PDF

โหมดคุณภาพ:
* original  - ฝังไฟล์ JPEG เดิมลง PDF ตรง ๆ ไม่บีบอัดซ้ำ คุณภาพเท่าต้นฉบับเป๊ะ
              (ใช้ได้เมื่อไฟล์เป็น JPEG ที่ไม่ต้องหมุนตาม EXIF)
* balanced  - แปลงเป็น JPEG คุณภาพสูง ไฟล์เล็กลงพอสมควร
* compact   - ย่อความละเอียดลงตามค่าที่กำหนด เหมาะกับการส่งทางแชต

รูปที่มีข้อมูลหมุนใน EXIF จะถูกหมุนให้ตรงก่อนเสมอ มิฉะนั้นรูปจากมือถือจะนอนผิดด้าน
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import fitz
from PIL import Image, ImageOps

PAGE_SIZES_MM = {
    "A4": (210.0, 297.0),
    "A5": (148.0, 210.0),
    "A3": (297.0, 420.0),
    "Letter": (215.9, 279.4),
    "Legal": (215.9, 355.6),
}

MM_TO_PT = 72.0 / 25.4
SUPPORTED = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"}


@dataclass
class ImageResult:
    pages: int
    path: str
    size_bytes: int
    skipped: List[str]
    notes: List[str]


def _load(data: bytes) -> Tuple[Image.Image, bool]:
    """เปิดรูปและหมุนตาม EXIF คืน (รูป, ถูกหมุนหรือไม่)"""
    img = Image.open(io.BytesIO(data))
    img.load()
    fixed = ImageOps.exif_transpose(img)
    rotated = fixed is not img and fixed.size != img.size
    return fixed, rotated


def _to_jpeg(img: Image.Image, quality: int, max_px: Optional[int]) -> bytes:
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        canvas = Image.new("RGB", img.size, (255, 255, 255))
        canvas.paste(img, mask=img.split()[-1])
        img = canvas
    elif img.mode != "RGB":
        img = img.convert("RGB")

    if max_px and max(img.size) > max_px:
        ratio = max_px / max(img.size)
        img = img.resize((max(1, int(img.width * ratio)), max(1, int(img.height * ratio))),
                         Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue()


def _page_rect(page_w: float, page_h: float, img_w: int, img_h: int,
               margin_pt: float, fill_page: bool) -> fitz.Rect:
    """คำนวณกรอบวางรูปโดยรักษาสัดส่วนเดิมไว้เสมอ"""
    avail_w = max(page_w - margin_pt * 2, 1.0)
    avail_h = max(page_h - margin_pt * 2, 1.0)
    scale = (max if fill_page else min)(avail_w / img_w, avail_h / img_h)
    w, h = img_w * scale, img_h * scale
    x0 = (page_w - w) / 2
    y0 = (page_h - h) / 2
    return fitz.Rect(x0, y0, x0 + w, y0 + h)


def images_to_pdf(images: Sequence[Tuple[str, bytes]], out_path: str, *,
                  page_size: str = "fit",
                  orientation: str = "auto",
                  margin_mm: float = 0.0,
                  quality_mode: str = "balanced",
                  jpeg_quality: int = 92,
                  max_pixels: Optional[int] = None,
                  fit_dpi: int = 150,
                  fill_page: bool = False) -> ImageResult:
    """
    images      : ลำดับของ (ชื่อไฟล์, ข้อมูลไบต์) เรียงตามลำดับหน้าที่ต้องการ
    page_size   : "fit" = ขนาดหน้าเท่ารูป หรือชื่อขนาดกระดาษใน PAGE_SIZES_MM
    orientation : auto | portrait | landscape
    fill_page   : True = ขยายรูปจนเต็มหน้า (ส่วนเกินถูกตัด), False = ใส่ให้พอดีทั้งรูป
    """
    doc = fitz.open()
    skipped: List[str] = []
    notes: List[str] = []
    margin_pt = margin_mm * MM_TO_PT
    pages = 0

    for name, data in images:
        try:
            img, rotated = _load(data)
        except Exception as exc:
            skipped.append(f"{name} (เปิดไม่ได้: {exc})")
            continue

        is_jpeg = (img.format or "").upper() in ("JPEG", "MPO")
        use_original = quality_mode == "original" and is_jpeg and not rotated

        if use_original:
            payload = data
            img_w, img_h = img.size
        else:
            if quality_mode == "original" and is_jpeg and rotated:
                notes.append(f"{name}: หมุนตาม EXIF จึงต้องบันทึกใหม่หนึ่งครั้ง")
            q = 96 if quality_mode == "original" else jpeg_quality
            cap = max_pixels if quality_mode == "compact" else None
            payload = _to_jpeg(img, q, cap)
            with Image.open(io.BytesIO(payload)) as probe:
                img_w, img_h = probe.size

        if page_size == "fit":
            pw = img_w * 72.0 / max(fit_dpi, 1)
            ph = img_h * 72.0 / max(fit_dpi, 1)
            pw += margin_pt * 2
            ph += margin_pt * 2
        else:
            mm_w, mm_h = PAGE_SIZES_MM.get(page_size, PAGE_SIZES_MM["A4"])
            pw, ph = mm_w * MM_TO_PT, mm_h * MM_TO_PT
            landscape = (orientation == "landscape") or \
                        (orientation == "auto" and img_w > img_h)
            if landscape:
                pw, ph = ph, pw

        page = doc.new_page(width=pw, height=ph)
        rect = _page_rect(pw, ph, img_w, img_h, margin_pt, fill_page)
        page.insert_image(rect, stream=payload, keep_proportion=True)
        pages += 1
        img.close()

    if pages == 0:
        doc.close()
        raise ValueError("ไม่มีรูปที่ใช้งานได้เลย")

    doc.save(out_path, garbage=3, deflate=True)
    doc.close()

    return ImageResult(pages=pages, path=out_path,
                       size_bytes=os.path.getsize(out_path),
                       skipped=skipped, notes=notes)
