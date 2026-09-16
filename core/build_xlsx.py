# -*- coding: utf-8 -*-
"""
build_xlsx.py - สร้างไฟล์ Excel จากเอกสารที่ดึงมา

Excel ไม่มีปัญหา complex script แบบ Word แต่มีกับดักอื่น:
* ฟอนต์เริ่มต้น (Calibri) ไม่มี glyph ไทย Excel จะสลับฟอนต์เอง
  ทำให้ความสูงแถวเพี้ยนและวรรณยุกต์ถูกตัด จึงต้องตั้งฟอนต์ไทยให้ทุกเซลล์
* ข้อความที่ขึ้นต้นด้วย = + - @ จะถูกตีความเป็นสูตร ต้องบังคับให้เป็นข้อความ
* ตัวเลขที่มีคอมมาคั่นหลักถ้าปล่อยเป็นข้อความจะคำนวณต่อไม่ได้
  จึงแปลงเป็นตัวเลขจริงพร้อมรูปแบบแสดงผลที่เหมือนต้นฉบับ
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .extract import Document

NUMBER_RE = re.compile(r"^-?\(?\s*\d{1,3}(,\d{3})*(\.\d+)?\s*\)?$|^-?\d+(\.\d+)?$")
FORMULA_START = ("=", "+", "-", "@")

THIN = Side(style="thin", color="D0D0D0")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEADER_FILL = PatternFill("solid", fgColor="EFEAE2")


def _as_number(value: str) -> Optional[Tuple[float, str]]:
    """
    ถ้าข้อความเป็นตัวเลข คืน (ค่าตัวเลข, รูปแบบแสดงผล) มิฉะนั้นคืน None
    รูปแบบแสดงผลถูกสร้างให้ตรงกับต้นฉบับ เพื่อให้ตาเห็นเหมือนเดิมทุกตัว
    """
    s = value.strip()
    if not s or not NUMBER_RE.match(s):
        return None
    negative = s.startswith("-") or (s.startswith("(") and s.endswith(")"))
    body = s.strip("()-").strip()
    try:
        num = float(body.replace(",", ""))
    except ValueError:
        return None
    if negative:
        num = -num

    decimals = len(body.split(".")[1]) if "." in body else 0
    grouped = "," in body
    fmt = ("#,##0" if grouped else "0")
    if decimals:
        fmt += "." + "0" * decimals
    return num, fmt


def _write_cell(ws, row: int, col: int, value: str, *, font: Font,
                numbers_as_values: bool, header: bool = False):
    cell = ws.cell(row=row, column=col)
    text = value if value is not None else ""

    parsed = _as_number(text) if (numbers_as_values and not header) else None
    if parsed:
        cell.value, cell.number_format = parsed
        cell.alignment = Alignment(horizontal="right", vertical="center")
    else:
        # กันไม่ให้ Excel ตีความข้อความเป็นสูตร
        cell.value = text
        if text.startswith(FORMULA_START):
            cell.data_type = "s"
            cell.quotePrefix = True
        cell.alignment = Alignment(vertical="center", wrap_text=True)

    cell.font = font
    cell.border = BORDER
    if header:
        cell.fill = HEADER_FILL
    return cell


def _autosize(ws, max_width: int = 60):
    widths = {}
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is None:
                continue
            length = max(len(line) for line in str(cell.value).split("\n"))
            widths[cell.column] = min(max(widths.get(cell.column, 8), length + 3), max_width)
    for col, width in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = width


def _safe_title(name: str, used: set) -> str:
    """ชื่อชีตของ Excel ห้ามยาวเกิน 31 ตัว และห้ามมีอักขระบางตัว"""
    clean = re.sub(r"[\\/*?\[\]:]", "-", name)[:31] or "Sheet"
    base, n = clean, 2
    while clean in used:
        suffix = f" ({n})"
        clean = base[:31 - len(suffix)] + suffix
        n += 1
    used.add(clean)
    return clean


def build_xlsx(document: Document, out_path: str, *,
               font_name: str = "TH Sarabun New",
               font_size: float = 14.0,
               numbers_as_values: bool = True,
               separate_sheet_per_table: bool = True,
               include_text_sheet: bool = True) -> str:
    wb = Workbook()
    wb.remove(wb.active)

    body_font = Font(name=font_name, size=font_size)
    head_font = Font(name=font_name, size=font_size, bold=True)
    used_titles: set = set()

    table_count = 0
    for page in document.pages:
        if not page.tables:
            continue
        if separate_sheet_per_table:
            for ti, table in enumerate(page.tables, start=1):
                table_count += 1
                title = _safe_title(f"หน้า {page.number} ตาราง {ti}", used_titles)
                ws = wb.create_sheet(title)
                for ri, row in enumerate(table.rows, start=1):
                    for ci, value in enumerate(row, start=1):
                        _write_cell(ws, ri, ci, value,
                                    font=head_font if ri == 1 else body_font,
                                    numbers_as_values=numbers_as_values,
                                    header=(ri == 1))
                ws.freeze_panes = "A2"
                _autosize(ws)
        else:
            title = _safe_title(f"หน้า {page.number}", used_titles)
            ws = wb.create_sheet(title)
            row_cursor = 1
            for table in page.tables:
                table_count += 1
                for ri, row in enumerate(table.rows):
                    for ci, value in enumerate(row, start=1):
                        _write_cell(ws, row_cursor, ci, value,
                                    font=head_font if ri == 0 else body_font,
                                    numbers_as_values=numbers_as_values,
                                    header=(ri == 0))
                    row_cursor += 1
                row_cursor += 1
            _autosize(ws)

    if include_text_sheet:
        ws = wb.create_sheet(_safe_title("ข้อความ", used_titles), 0 if table_count == 0 else None)
        ws.append(["หน้า", "ลำดับ", "ข้อความ"])
        for c in range(1, 4):
            cell = ws.cell(row=1, column=c)
            cell.font = head_font
            cell.fill = HEADER_FILL
            cell.border = BORDER
        row = 2
        for page in document.pages:
            for i, para in enumerate(page.paragraphs, start=1):
                text = para.text.strip()
                if not text:
                    continue
                _write_cell(ws, row, 1, str(page.number), font=body_font,
                            numbers_as_values=False)
                _write_cell(ws, row, 2, str(i), font=body_font, numbers_as_values=False)
                _write_cell(ws, row, 3, text, font=body_font, numbers_as_values=False)
                row += 1
        ws.freeze_panes = "A2"
        ws.column_dimensions["A"].width = 8
        ws.column_dimensions["B"].width = 8
        ws.column_dimensions["C"].width = 100

    if not wb.sheetnames:
        ws = wb.create_sheet("ว่าง")
        ws["A1"] = "ไม่พบข้อความในไฟล์ต้นทาง"
        ws["A1"].font = body_font

    wb.save(out_path)
    return out_path


def read_xlsx_text(path: str) -> List[str]:
    """อ่านค่าทุกเซลล์กลับมา สำหรับใช้ตรวจสอบความตรงกัน"""
    wb = load_workbook(path, data_only=True)
    values: List[str] = []
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is None:
                    continue
                values.append(str(cell.value))
    wb.close()
    return values
