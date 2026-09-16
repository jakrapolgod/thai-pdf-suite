# -*- coding: utf-8 -*-
"""
verify.py - ตรวจสอบย้อนกลับว่าไฟล์ที่สร้างออกมาตรงกับต้นฉบับจริง

หลักการ: อย่าเชื่อว่าแปลงถูก ให้เปิดไฟล์ผลลัพธ์ขึ้นมาอ่านใหม่ แล้วเทียบกับ
ข้อความต้นทางทีละชิ้นในระดับ code point

เทียบระดับ code point ไม่ใช่ระดับสายตา เพราะข้อความสองชุดที่พิมพ์ออกมาหน้าตา
เหมือนกันเป๊ะ อาจเก็บลำดับวรรณยุกต์ต่างกันจนแสดงผลเพี้ยนบนเครื่องอื่น
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import thaitext as T
from .build_docx import read_docx_text
from .build_xlsx import read_xlsx_text
from .extract import Document


@dataclass
class Mismatch:
    index: int
    expected: str
    got: str
    expected_cp: str
    got_cp: str
    note: str = ""


@dataclass
class VerifyReport:
    target: str                       # docx | xlsx
    exact: bool = False
    items_total: int = 0
    items_matched: int = 0
    chars_source: int = 0
    chars_output: int = 0
    thai_problems: List[dict] = field(default_factory=list)
    mismatches: List[Mismatch] = field(default_factory=list)
    note: str = ""

    @property
    def match_percent(self) -> float:
        if self.items_total == 0:
            return 100.0
        return round(self.items_matched * 100.0 / self.items_total, 4)

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "exact": self.exact,
            "items_total": self.items_total,
            "items_matched": self.items_matched,
            "match_percent": self.match_percent,
            "chars_source": self.chars_source,
            "chars_output": self.chars_output,
            "thai_problems": self.thai_problems,
            "note": self.note,
            "mismatches": [
                {"index": m.index, "expected": m.expected, "got": m.got,
                 "expected_cp": m.expected_cp, "got_cp": m.got_cp, "note": m.note}
                for m in self.mismatches[:12]
            ],
        }


def codepoints(s: str, limit: int = 30) -> str:
    out = " ".join(f"U+{ord(c):04X}" for c in s[:limit])
    return out + (" ..." if len(s) > limit else "")


def source_items(document: Document) -> List[str]:
    """
    รายการข้อความต้นทางเรียงตามลำดับเดียวกับที่ตัวสร้างไฟล์เขียนออกไป
    ย่อหน้าหนึ่งชิ้น ตารางหนึ่งแถวหนึ่งชิ้น
    """
    items: List[str] = []
    for page in document.pages:
        ordered = [("p", p.bbox[1], p) for p in page.paragraphs]
        ordered += [("t", t.bbox[1], t) for t in page.tables]
        ordered.sort(key=lambda it: it[1])
        for kind, _, obj in ordered:
            if kind == "p":
                if obj.text.strip():
                    items.append(obj.text)
            else:
                cols = max((len(r) for r in obj.rows), default=0)
                for row in obj.rows:
                    padded = list(row) + [""] * (cols - len(row))
                    if any(c.strip() for c in padded):
                        items.append("\t".join(padded))
    return items


def _squash(s: str) -> str:
    """ยุบช่องว่างซ้ำและตัดหัวท้าย ใช้เทียบเฉพาะเรื่องการจัดวาง ไม่ใช่ตัวอักษร"""
    return re.sub(r"[ \t]+", " ", s).strip()


def verify_docx(document: Document, docx_path: str) -> VerifyReport:
    report = VerifyReport(target="docx")

    expected = source_items(document)
    got_raw = read_docx_text(docx_path)
    got = [line for line in got_raw.split("\n") if line.strip()]

    report.items_total = len(expected)
    report.chars_source = sum(len(x) for x in expected)
    report.chars_output = sum(len(x) for x in got)

    for i, exp in enumerate(expected):
        actual = got[i] if i < len(got) else ""
        if exp == actual:
            report.items_matched += 1
        elif _squash(exp) == _squash(actual):
            report.items_matched += 1   # ต่างแค่ช่องว่างซ้ำ ตัวอักษรครบถ้วน
        else:
            report.mismatches.append(Mismatch(
                index=i, expected=exp[:120], got=actual[:120],
                expected_cp=codepoints(exp), got_cp=codepoints(actual),
                note="ข้อความไม่ตรงกัน" if actual else "ไม่พบข้อความชิ้นนี้ในไฟล์ผลลัพธ์",
            ))

    if len(got) > len(expected):
        report.mismatches.append(Mismatch(
            index=len(expected), expected="", got=got[len(expected)][:120],
            expected_cp="", got_cp=codepoints(got[len(expected)]),
            note="มีข้อความเกินมาในไฟล์ผลลัพธ์",
        ))

    report.exact = not report.mismatches
    report.thai_problems = T.summarize(T.audit(got_raw))
    return report


def _num(s: str) -> Optional[float]:
    t = s.strip().replace(",", "")
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def verify_xlsx(document: Document, xlsx_path: str, *,
                numbers_as_values: bool = True) -> VerifyReport:
    """
    Excel แปลงข้อความตัวเลขเป็นตัวเลขจริง ("1,234" -> 1234) ตามที่ตั้งค่าไว้
    การเทียบจึงยอมรับความต่างนี้เมื่อค่าทางตัวเลขเท่ากัน แต่ข้อความไทยต้องตรงเป๊ะ
    """
    report = VerifyReport(target="xlsx")

    expected: List[str] = []
    for page in document.pages:
        for table in page.tables:
            for row in table.rows:
                expected.extend(c for c in row if c is not None)
        for para in page.paragraphs:
            if para.text.strip():
                expected.append(para.text.strip())

    got = read_xlsx_text(xlsx_path)
    got_pool = list(got)

    report.items_total = len(expected)
    report.chars_source = sum(len(x) for x in expected)
    report.chars_output = sum(len(x) for x in got)

    for i, exp in enumerate(expected):
        if not exp.strip():
            report.items_matched += 1
            continue
        found = False
        for j, actual in enumerate(got_pool):
            if actual == exp or _squash(actual) == _squash(exp):
                found = True
            elif numbers_as_values:
                a, b = _num(exp), _num(actual)
                if a is not None and b is not None and abs(a - b) < 1e-9:
                    found = True
            if found:
                got_pool.pop(j)
                break
        if found:
            report.items_matched += 1
        else:
            report.mismatches.append(Mismatch(
                index=i, expected=exp[:120], got="",
                expected_cp=codepoints(exp), got_cp="",
                note="ไม่พบค่านี้ในไฟล์ Excel",
            ))

    report.exact = not report.mismatches
    report.thai_problems = T.summarize(T.audit("\n".join(got)))
    if numbers_as_values:
        report.note = "ข้อความที่เป็นตัวเลขถูกแปลงเป็นค่าตัวเลขจริงตามที่ตั้งค่าไว้"
    return report


def document_quality(document: Document) -> dict:
    """สรุปคุณภาพการดึงข้อความทั้งเอกสาร สำหรับแสดงบนหน้าจอ"""
    full = document.text
    remaining = T.audit(full)
    pages = []
    for p in document.pages:
        pages.append({
            "number": p.number,
            "chars": p.char_count,
            "paragraphs": len(p.paragraphs),
            "tables": len(p.tables),
            "source": p.source,
            "confidence": p.ocr_confidence,
        })
    return {
        "pages": pages,
        "total_chars": len(full),
        "thai_ratio": round(T.thai_ratio(full), 4),
        "fixed": T.summarize(document.issues),
        "remaining": T.summarize(remaining),
        "clean": len(remaining) == 0,
        "visual_order_suspect": document.visual_order_suspect,
        "visual_order_ratio": round(document.visual_order_ratio, 3),
        "needs_ocr_pages": document.needs_ocr_pages,
        "fonts": document.fonts,
    }
