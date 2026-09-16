# -*- coding: utf-8 -*-
"""
สร้างไอคอนของโปรแกรมจากฟอนต์ไทยที่มีในเครื่อง

ออกแบบให้เหลือแค่พยัญชนะตัวเดียวบนพื้นสีเข้ม เพราะไอคอนถูกย่อลงเหลือ 16 จุด
ในบางมุมของ Windows ถ้าใส่ข้อความยาวกว่านี้จะกลายเป็นรอยเปื้อนอ่านไม่ออก
"""
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT_ICO = ROOT / "web" / "app.ico"
OUT_PNG = ROOT / "web" / "app.png"

ACCENT = (180, 84, 58, 255)
WHITE = (255, 255, 255, 255)
SIZE = 512
SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]

FONT_CANDIDATES = [
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts\THSarabunNew Bold.ttf"),
    r"C:\Windows\Fonts\tahomabd.ttf",
    r"C:\Windows\Fonts\leelawdb.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
]


def pick_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    raise SystemExit("ไม่พบฟอนต์ไทยสำหรับสร้างไอคอน")


def build() -> None:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = SIZE // 16
    draw.rounded_rectangle([pad, pad, SIZE - pad, SIZE - pad],
                           radius=SIZE // 6, fill=ACCENT)

    glyph = "ท"
    font = pick_font(int(SIZE * 0.62))
    box = draw.textbbox((0, 0), glyph, font=font)
    x = (SIZE - (box[2] - box[0])) / 2 - box[0]
    y = (SIZE - (box[3] - box[1])) / 2 - box[1]
    draw.text((x, y), glyph, font=font, fill=WHITE)

    OUT_ICO.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT_ICO, format="ICO", sizes=SIZES)
    img.resize((256, 256), Image.LANCZOS).save(OUT_PNG)
    print(f"สร้างไอคอนแล้ว: {OUT_ICO}")
    print(f"                {OUT_PNG}")


if __name__ == "__main__":
    build()
