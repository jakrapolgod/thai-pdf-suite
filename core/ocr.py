# -*- coding: utf-8 -*-
"""
ocr.py - อ่านข้อความจากหน้า PDF ที่เป็นภาพสแกน

ข้อเท็จจริงที่ต้องพูดตรง ๆ:
หน้าที่มีชั้นข้อความจริงแปลงได้ตรงทุกตัวอักษร และตรวจสอบย้อนกลับได้
แต่หน้าที่เป็นภาพสแกนต้องพึ่ง OCR ซึ่งไม่มีเอนจินใดรับประกันความถูกต้อง 100%
โมดูลนี้จึงรายงานค่าความมั่นใจรายคำออกมาเสมอ และทำเครื่องหมายคำที่น่าสงสัยไว้
เพื่อให้คนตรวจซ้ำได้ตรงจุด แทนที่จะส่งข้อความที่อาจผิดออกไปเงียบ ๆ

ใช้ Tesseract เป็นเอนจิน เพราะทำงานออฟไลน์ทั้งหมด เอกสารไม่หลุดออกนอกเครื่อง
"""
from __future__ import annotations

import csv
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import List, Optional, Tuple

import fitz

from . import thaitext as T
from .paths import app_dir, find_data_dir
from .extract import Line, Page, Paragraph, Run, _lines_to_paragraphs

# ระยะห่างระหว่างชิ้นข้อความที่เกินกว่านี้ (คูณกับความสูงเฉลี่ยของบรรทัด) จึงนับเป็นช่องว่างจริง
# Tesseract หั่นข้อความไทยเป็นชิ้นเล็กมาก ถ้าตั้งต่ำกว่านี้จะได้ช่องว่างแทรกกลางคำ
# วัดจากเอกสารทดสอบแล้ว 0.60 ให้ผลดีที่สุด แลกกับการที่ช่องว่างจริงบางจุดหายไป
WORD_GAP_RATIO = 0.60

WINDOWS_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    os.path.expandvars(r"%USERPROFILE%\scoop\shims\tesseract.exe"),
]

INSTALL_HINT = (
    "ยังไม่พบ Tesseract ในเครื่อง หน้าที่เป็นภาพสแกนจึงอ่านไม่ได้\n"
    "ติดตั้งด้วยคำสั่ง:  winget install --id UB-Mannheim.TesseractOCR\n"
    "แล้วดาวน์โหลดไฟล์ภาษาไทย tha.traineddata จาก "
    "https://github.com/tesseract-ocr/tessdata_best "
    "ไปวางในโฟลเดอร์ tessdata ของแอปนี้"
)

# โฟลเดอร์ไฟล์ภาษาของแอปเอง ทำให้ไม่ต้องเขียนลง Program Files ซึ่งต้องใช้สิทธิ์ผู้ดูแลเครื่อง
# และทำให้เลือกใช้ไฟล์ภาษารุ่น best ได้โดยไม่กระทบไฟล์ที่ติดมากับตัวติดตั้ง
LOCAL_TESSDATA = str(app_dir() / "tessdata")


def find_tessdata() -> Optional[str]:
    """โฟลเดอร์ไฟล์ภาษาที่จะใช้ คืน None แปลว่าให้ Tesseract ใช้ของตัวเอง"""
    found = find_data_dir("tessdata", "tha.traineddata")
    if found:
        return str(found)
    env = os.environ.get("TESSDATA_PREFIX")
    if env and os.path.isfile(os.path.join(env, "tha.traineddata")):
        return env
    return None


def _data_args() -> List[str]:
    path = find_tessdata()
    return ["--tessdata-dir", path] if path else []


@dataclass
class OcrStatus:
    available: bool
    binary: Optional[str] = None
    version: str = ""
    languages: List[str] = None
    has_thai: bool = False
    hint: str = ""

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "binary": self.binary,
            "version": self.version,
            "languages": self.languages or [],
            "has_thai": self.has_thai,
            "hint": self.hint,
        }


def find_tesseract() -> Optional[str]:
    found = shutil.which("tesseract")
    if found:
        return found
    for path in WINDOWS_CANDIDATES:
        if path and os.path.isfile(path):
            return path
    return None


def check_ocr() -> OcrStatus:
    binary = find_tesseract()
    if not binary:
        return OcrStatus(available=False, hint=INSTALL_HINT, languages=[])

    def run(args):
        return subprocess.run([binary] + args, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30)

    try:
        ver = run(["--version"]).stdout.splitlines()[0].strip()
        langs_out = run(_data_args() + ["--list-langs"]).stdout
        langs = [l.strip() for l in langs_out.splitlines()[1:] if l.strip()]
    except Exception as exc:
        return OcrStatus(available=False, binary=binary,
                         hint=f"เรียก Tesseract ไม่สำเร็จ: {exc}", languages=[])

    has_thai = "tha" in langs
    hint = "" if has_thai else (
        "พบ Tesseract แล้วแต่ยังไม่มีภาษาไทย ดาวน์โหลด tha.traineddata จาก "
        f"https://github.com/tesseract-ocr/tessdata_best แล้ววางในโฟลเดอร์ {LOCAL_TESSDATA}"
    )
    return OcrStatus(available=has_thai, binary=binary, version=ver,
                     languages=langs, has_thai=has_thai, hint=hint)


def _render(page: "fitz.Page", dpi: int) -> bytes:
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
    return pix.tobytes("png")


def _run_tesseract(binary: str, png: bytes, lang: str, psm: int) -> List[dict]:
    """เรียก Tesseract แล้วอ่านผลแบบ TSV ซึ่งให้ค่าความมั่นใจรายคำมาด้วย"""
    with tempfile.TemporaryDirectory() as tmp:
        img_path = os.path.join(tmp, "page.png")
        out_base = os.path.join(tmp, "out")
        with open(img_path, "wb") as fh:
            fh.write(png)

        # สั่งสร้าง TSV ด้วยพารามิเตอร์ ไม่ใช่ชื่อไฟล์ config ("tsv")
        # เพราะเมื่อชี้ --tessdata-dir ไปโฟลเดอร์ของแอป Tesseract จะหาไฟล์ config ไม่เจอ
        cmd = [binary] + _data_args() + [
            img_path, out_base, "-l", lang, "--psm", str(psm),
            "-c", "preserve_interword_spaces=1",
            "-c", "tessedit_create_tsv=1"]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=300)
        tsv_path = out_base + ".tsv"
        if not os.path.exists(tsv_path):
            raise RuntimeError(proc.stderr.strip() or "Tesseract ไม่ได้สร้างไฟล์ผลลัพธ์")

        with open(tsv_path, encoding="utf-8", errors="replace", newline="") as fh:
            rows = list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))

    words = []
    for row in rows:
        text = (row.get("text") or "").strip()
        if not text:
            continue
        try:
            conf = float(row.get("conf", -1))
        except ValueError:
            conf = -1.0
        if conf < 0:
            continue
        words.append({
            "text": text,
            "conf": conf,
            "left": int(row["left"]), "top": int(row["top"]),
            "width": int(row["width"]), "height": int(row["height"]),
            "block": int(row["block_num"]), "par": int(row["par_num"]),
            "line": int(row["line_num"]),
        })
    return words


def ocr_page(page: "fitz.Page", page_number: int, *, binary: str,
             lang: str = "tha+eng", dpi: int = 300, psm: int = 3,
             low_conf: float = 75.0) -> Tuple[Page, List[T.Issue], List[dict]]:
    """
    อ่านหนึ่งหน้าด้วย OCR คืน (หน้าเอกสาร, รายการที่จัดระเบียบไทย, คำที่ความมั่นใจต่ำ)
    """
    png = _render(page, dpi)
    words = _run_tesseract(binary, png, lang, psm)

    scale = 72.0 / dpi
    issues: List[T.Issue] = []
    suspects: List[dict] = []

    grouped: dict = {}
    for w in words:
        grouped.setdefault((w["block"], w["par"], w["line"]), []).append(w)

    lines: List[Line] = []
    confs: List[float] = []

    for key in sorted(grouped):
        group = sorted(grouped[key], key=lambda w: w["left"])

        # Tesseract แยกข้อความไทยออกเป็นชิ้นเล็กมาก และวรรณยุกต์กับสระบน/ล่าง
        # มักถูกส่งมาเป็น "คำ" ของตัวเองโดยไม่มีพยัญชนะฐานติดมาด้วย
        # จึงต้องต่อทั้งบรรทัดให้ครบก่อน แล้วค่อยจัดระเบียบอักขระไทยทีเดียว
        # ถ้าจัดระเบียบทีละชิ้น วรรณยุกต์ที่มาลอย ๆ จะถูกมองว่าเป็นของเสียแล้วตัดทิ้ง
        heights = [w["height"] for w in group if w["height"] > 0]
        unit = (sum(heights) / len(heights)) if heights else 1.0

        raw = ""
        prev_right = None
        for w in group:
            token = w["text"]
            mark_only = all(c in T.COMBINING or c == T.SARA_AM for c in token)
            if raw and not mark_only and prev_right is not None:
                if (w["left"] - prev_right) > unit * WORD_GAP_RATIO:
                    raw += " "
            raw += token
            prev_right = max(prev_right or 0, w["left"] + w["width"])
            confs.append(w["conf"])

            if w["conf"] < low_conf and not mark_only:
                suspects.append({
                    "page": page_number, "text": token,
                    "confidence": round(w["conf"], 1),
                    "bbox": [round(w["left"] * scale, 1), round(w["top"] * scale, 1),
                             round((w["left"] + w["width"]) * scale, 1),
                             round((w["top"] + w["height"]) * scale, 1)],
                })

        line_text, line_issues = T.normalize(raw)
        issues.extend(line_issues)
        if not line_text.strip():
            continue

        x0 = min(w["left"] for w in group) * scale
        y0 = min(w["top"] for w in group) * scale
        x1 = max(w["left"] + w["width"] for w in group) * scale
        y1 = max(w["top"] + w["height"] for w in group) * scale
        size = max(8.0, (y1 - y0) * 0.86)

        lines.append(Line(runs=[Run(text=line_text, font="OCR", size=round(size, 1))],
                          bbox=(x0, y0, x1, y1)))

    paragraphs: List[Paragraph] = _lines_to_paragraphs(lines)
    rect = page.rect
    out = Page(
        number=page_number, width=rect.width, height=rect.height,
        paragraphs=paragraphs, tables=[], images=[],
        char_count=sum(len(p.text) for p in paragraphs),
        source="ocr",
        ocr_confidence=round(sum(confs) / len(confs), 1) if confs else None,
    )
    return out, issues, suspects


def ocr_document(pdf_path: str, page_numbers: Optional[List[int]] = None, *,
                 lang: str = "tha+eng", dpi: int = 300, psm: int = 3,
                 low_conf: float = 75.0, password: str = "") -> dict:
    """
    อ่านทั้งไฟล์ (หรือเฉพาะหน้าที่ระบุ) ด้วย OCR
    page_numbers นับเริ่มที่ 1 ถ้าไม่ระบุจะอ่านทุกหน้า
    """
    status = check_ocr()
    if not status.available:
        raise RuntimeError(status.hint or INSTALL_HINT)

    doc = fitz.open(pdf_path)
    if doc.needs_pass and not doc.authenticate(password):
        doc.close()
        raise ValueError("ไฟล์ PDF ถูกใส่รหัสผ่าน และรหัสที่ให้มาเปิดไม่ได้")

    targets = page_numbers or list(range(1, len(doc) + 1))
    pages, issues, suspects = [], [], []

    for pno in targets:
        if pno < 1 or pno > len(doc):
            continue
        page_obj, page_issues, page_suspects = ocr_page(
            doc[pno - 1], pno, binary=status.binary, lang=lang,
            dpi=dpi, psm=psm, low_conf=low_conf)
        pages.append(page_obj)
        issues.extend(page_issues)
        suspects.extend(page_suspects)

    doc.close()
    return {"pages": pages, "issues": issues, "suspects": suspects,
            "engine": f"Tesseract {status.version}", "lang": lang, "dpi": dpi}
