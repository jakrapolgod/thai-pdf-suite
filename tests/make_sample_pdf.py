# -*- coding: utf-8 -*-
"""
สร้าง PDF ภาษาไทยสำหรับทดสอบ พร้อมเก็บ "ข้อความต้นฉบับที่ถูกต้อง" ไว้เทียบ
ทำให้ทดสอบได้ว่าแปลงกลับมาแล้วตรงกันทุก code point จริงหรือไม่
"""
import json
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
OUT_PDF = ROOT / "tests" / "sample_thai.pdf"
OUT_JSON = ROOT / "tests" / "sample_thai_truth.json"

FONT = "C:/Windows/Fonts/tahoma.ttf"
FONT_BOLD = "C:/Windows/Fonts/tahomabd.ttf"

TITLE = "รายงานผลการดำเนินงานประจำไตรมาส"
SUBTITLE = "บริษัท Thai PDF Suite จำกัด"

PARAS = [
    "ในไตรมาสที่ผ่านมา บริษัทมีผลประกอบการเติบโตขึ้นอย่างต่อเนื่อง "
    "โดยมียอดขายน้ำมันปาล์มดิบรวมทั้งสิ้น ๑,๒๓๔ ตัน เพิ่มขึ้นจากช่วงเดียวกันของปีก่อน",
    "ปัจจัยสำคัญที่ทำให้ผลงานดีขึ้น คือ ราคาผลปาล์มสดที่ปรับตัวสูงขึ้น "
    "และการบริหารจัดการต้นทุนที่มีประสิทธิภาพมากขึ้นกว่าเดิม",
    "ทั้งนี้ ฝ่ายบริหารได้ตั้งเป้าหมายไว้ว่าจะรักษาอัตราการเติบโตนี้ให้ต่อเนื่องไปถึงสิ้นปี",
]

TABLE = [
    ["รายการ", "จำนวน", "หน่วย", "มูลค่า (บาท)"],
    ["น้ำมันปาล์มดิบ", "1,234", "ตัน", "45,678,900.00"],
    ["เมล็ดในปาล์ม", "567", "ตัน", "12,345,600.00"],
    ["กะลาปาล์ม", "89", "ตัน", "1,234,500.00"],
    ["ทะลายเปล่า", "456", "ตัน", "567,800.00"],
    ["รวมทั้งสิ้น", "2,346", "ตัน", "59,826,800.00"],
]

FOOTER = "จัดทำโดย ฝ่ายบัญชีและการเงิน ณ วันที่ ๓๐ กันยายน ๒๕๖๙"


def build():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)   # A4
    page.insert_font(fontname="TH", fontfile=FONT)
    page.insert_font(fontname="THB", fontfile=FONT_BOLD)

    y = 90
    page.insert_text((72, y), TITLE, fontname="THB", fontsize=18)
    y += 28
    page.insert_text((72, y), SUBTITLE, fontname="TH", fontsize=14)
    y += 40

    # ย่อหน้าแบบตัดบรรทัดเอง เพื่อทดสอบการต่อบรรทัดที่ถูกตัดกลางคำ
    for para in PARAS:
        wrapped = _wrap(para, 62)
        for line in wrapped:
            page.insert_text((72, y), line, fontname="TH", fontsize=12)
            y += 19
        y += 12

    # ตารางพร้อมเส้นตาราง เพื่อให้ตัวตรวจจับตารางเห็นโครง
    col_x = [72, 250, 330, 410, 523]
    row_h = 24
    top = y
    for r, row in enumerate(TABLE):
        for c, cell in enumerate(row):
            fname = "THB" if r == 0 or r == len(TABLE) - 1 else "TH"
            page.insert_text((col_x[c] + 5, top + r * row_h + 16), cell,
                             fontname=fname, fontsize=11)
    bottom = top + len(TABLE) * row_h
    for i in range(len(TABLE) + 1):
        page.draw_line(fitz.Point(col_x[0], top + i * row_h),
                       fitz.Point(col_x[-1], top + i * row_h), width=0.7)
    for x in col_x:
        page.draw_line(fitz.Point(x, top), fitz.Point(x, bottom), width=0.7)

    page.insert_text((72, bottom + 46), FOOTER, fontname="TH", fontsize=11)

    doc.save(str(OUT_PDF))
    doc.close()

    truth = {
        "title": TITLE,
        "subtitle": SUBTITLE,
        "paragraphs": PARAS,
        "table": TABLE,
        "footer": FOOTER,
    }
    OUT_JSON.write_text(json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"สร้างแล้ว: {OUT_PDF}")
    print(f"ข้อมูลอ้างอิง: {OUT_JSON}")


def _wrap(text: str, width: int):
    """ตัดบรรทัดแบบหยาบ ๆ ให้ยาวใกล้เคียงกัน รวมถึงตัดกลางคำไทยด้วยโดยตั้งใจ"""
    lines, buf = [], ""
    for ch in text:
        buf += ch
        if len(buf) >= width and ch != " ":
            lines.append(buf)
            buf = ""
    if buf:
        lines.append(buf)
    return lines


if __name__ == "__main__":
    build()
