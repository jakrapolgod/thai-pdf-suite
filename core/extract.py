# -*- coding: utf-8 -*-
"""
extract.py - ดึงข้อความจาก PDF แบบรักษาความถูกต้องของภาษาไทย

จุดต่างจากการใช้ get_text("text") ตรง ๆ:

* อ่านทีละ glyph พร้อมพิกัดจริง แล้วตัดสินใจเรื่องช่องว่างจากระยะห่างที่วัดได้
  ไม่ใช่จากตัวอักษรช่องว่างในไฟล์ จึงไม่เกิดอาการ "ก า ร ป ร ะ ชุ ม"
* เชื่อมบรรทัดที่ถูกตัดกลางคำ โดยไม่แทรกช่องว่างเมื่อทั้งสองฝั่งเป็นอักษรไทย
  (ภาษาไทยตัดบรรทัดกลางคำได้ ถ้าใส่ช่องว่างจะได้คำผิด)
* ซ่อมอักขระผสมที่ถูกหั่นข้าม span (วรรณยุกต์หลุดไปอยู่ต้น span ถัดไป)
* ส่งข้อความทุกชิ้นผ่าน thaitext.normalize ก่อนเสมอ
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import List, Optional, Tuple

import fitz  # PyMuPDF

from . import thaitext as T
from .glyphmap import DocumentGlyphMaps, _font_xrefs, lookup_fix, page_corrections

# ระยะห่างระหว่าง glyph ที่เกินกว่านี้ (คูณกับขนาดฟอนต์) ถือว่าเป็นช่องว่างจริง
SPACE_RATIO = 0.20
# ความสูงบรรทัดที่ห่างเกินกว่านี้ (คูณกับความสูงบรรทัดก่อนหน้า) ถือว่าขึ้นย่อหน้าใหม่
PARA_GAP_RATIO = 1.55
# บรรทัดที่สั้นกว่านี้เมื่อเทียบกับความกว้างบล็อก ถือว่าเป็นบรรทัดจบย่อหน้า
LINE_FULL_RATIO = 0.88
# glyph ที่กว้างน้อยกว่านี้ (คูณกับขนาดฟอนต์) ถือว่าไม่กินที่ เป็นอักขระผสมไม่ใช่ช่องว่าง
ZERO_WIDTH_RATIO = 0.05


@dataclass
class Run:
    """ข้อความช่วงหนึ่งที่มีรูปแบบตัวอักษรเดียวกัน"""
    text: str
    font: str = ""
    size: float = 12.0
    bold: bool = False
    italic: bool = False
    color: int = 0

    def style_key(self) -> tuple:
        return (round(self.size, 1), self.bold, self.italic, self.color)


@dataclass
class Line:
    runs: List[Run] = field(default_factory=list)
    bbox: Tuple[float, float, float, float] = (0, 0, 0, 0)

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


@dataclass
class Paragraph:
    runs: List[Run] = field(default_factory=list)
    align: str = "left"          # left | center | right
    bbox: Tuple[float, float, float, float] = (0, 0, 0, 0)
    size: float = 12.0
    bold: bool = False

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


@dataclass
class Table:
    rows: List[List[str]] = field(default_factory=list)
    bbox: Tuple[float, float, float, float] = (0, 0, 0, 0)

    @property
    def text(self) -> str:
        return "\n".join("\t".join(c for c in row) for row in self.rows)


@dataclass
class Page:
    number: int
    width: float
    height: float
    paragraphs: List[Paragraph] = field(default_factory=list)
    tables: List[Table] = field(default_factory=list)
    images: List[dict] = field(default_factory=list)
    char_count: int = 0
    source: str = "text"          # text | ocr | empty
    ocr_confidence: Optional[float] = None

    @property
    def text(self) -> str:
        parts = [p.text for p in self.paragraphs] + [t.text for t in self.tables]
        return "\n".join(parts)


@dataclass
class Document:
    path: str
    pages: List[Page] = field(default_factory=list)
    issues: List[T.Issue] = field(default_factory=list)
    visual_order_suspect: bool = False
    visual_order_ratio: float = 0.0
    producer: str = ""
    fonts: List[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)

    @property
    def needs_ocr_pages(self) -> List[int]:
        return [p.number for p in self.pages if p.source == "empty"]


# ------------------------------------------------------------------ glyph -> ข้อความ
def _chars_to_text(chars: List[dict], size: float, repair_sara_aa: bool = False,
                   fixes: Optional[dict] = None) -> str:
    """
    ประกอบ glyph เป็นข้อความ โดยตัดสินใจเรื่องช่องว่างจากระยะห่างที่วัดได้จริง

    ตัวอักษรช่องว่างที่อยู่ในไฟล์จะถูกมองข้ามทั้งหมด แล้วคำนวณใหม่จากพิกัด
    เพราะ PDF จำนวนมากวาง glyph ไทยทีละตัวโดยไม่มีช่องว่างจริง
    ถ้าเชื่อไฟล์ตรง ๆ จะได้คำที่มีช่องว่างแทรกกลางคำ

    repair_sara_aa ใช้กับฟอนต์ที่ตารางแปลงกลับเป็นยูนิโคดเสียหาย (ดู _broken_sara_fonts)
    ในกรณีนั้น glyph ของสระอาถูกแมปเป็นสระอำ และนิคหิตถูกแมปเป็นช่องว่างกว้างศูนย์
    จึงต้องแปลงกลับทั้งสองอย่างก่อนส่งต่อ
    """
    out: List[str] = []
    prev_x1: Optional[float] = None
    size = size if size and size > 0.1 else 12.0

    for ch in chars:
        c = ch.get("c", "")
        if not c:
            continue
        x0, _, x1, _ = ch.get("bbox", (0, 0, 0, 0))
        width = x1 - x0

        # ตัวอักษรที่ตารางแปลงกลับของ PDF ให้ค่าไม่ตรงกับ glyph ที่วาดจริง
        # ต้องแก้ก่อนทุกขั้น เพราะบางตัวถูกแมปผิดเป็นช่องว่าง
        if fixes:
            real = lookup_fix(fixes, ord(c), ch.get("origin"))
            if real and len(real) > 1:
                # อักขระผสมหลายตัวที่ถูกยุบรวมเหลือตัวเดียว ต้องคืนกลับให้ครบ
                out.extend(real)
                continue
            if real:
                c = real

        if c.isspace():
            if width < size * ZERO_WIDTH_RATIO:
                # ช่องว่างกว้างศูนย์ไม่ใช่ช่องว่างจริง เป็นอักขระผสมที่ถูกแมปผิด
                if repair_sara_aa:
                    out.append(T.NIKHAHIT)
                continue
            # ช่องว่างที่กินที่จริงคือช่องว่างจริง ต้องเชื่อไฟล์
            # ฟอนต์ไทยหลายตัว เช่น Angsana New ใช้ช่องว่างแคบกว่าเกณฑ์เรขาคณิตมาก
            # ถ้ารอให้เกณฑ์ระยะห่างตัดสินอย่างเดียว ช่องว่างจริงจะหายไปทั้งเอกสาร
            if out and not out[-1].isspace():
                out.append(" ")
            prev_x1 = x1
            continue

        if repair_sara_aa and c == T.SARA_AM:
            c = T.SARA_AA

        # อักขระผสมของไทยกว้างเกือบศูนย์และวางทับตัวฐาน จึงไม่นำมาคิดระยะห่าง
        is_mark = c in T.COMBINING

        if not is_mark and prev_x1 is not None:
            gap = x0 - prev_x1
            if gap > size * SPACE_RATIO and out and not out[-1].isspace():
                out.append(" ")

        out.append(c)
        if not is_mark and width > 0.01:
            prev_x1 = x1
        elif not is_mark:
            prev_x1 = max(prev_x1 or x1, x1)

    return "".join(out)


def _broken_sara_fonts(doc: "fitz.Document", skip: set = frozenset()) -> set:
    """
    หาฟอนต์ที่ตารางแปลง glyph กลับเป็นยูนิโคดเสียหาย

    Word บน Windows ส่งออก PDF ด้วยฟอนต์ไทยรุ่นเก่าอย่าง Tahoma, Angsana New,
    Cordia New แล้วแมป glyph ของ "สระอา" กลับเป็นรหัสของ "สระอำ" ทั้งหมด
    ส่วนนิคหิต (หัวกลมบนสระอำ) ถูกแมปเป็นช่องว่างที่กว้างศูนย์
    ผลคือ "ปาล์ม" กลายเป็น "ปำล์ม" และ "รายการ" กลายเป็น "รำยกำร"

    จับได้จากข้อเท็จจริงที่ว่า ข้อความไทยที่มีสระอำอยู่หลายตัวแต่ไม่มีสระอาเลย
    เป็นไปไม่ได้ในทางปฏิบัติ เพราะสระอาใช้บ่อยกว่าสระอำมาก
    เงื่อนไขนี้แคบพอที่จะไม่ไปแตะไฟล์ที่ปกติดีอยู่แล้ว
    """
    stats: dict = {}
    for page in doc:
        try:
            raw = page.get_text("rawdict")
        except Exception:
            continue
        for block in raw.get("blocks", []):
            if block.get("type") != 0:
                continue
            for ln in block.get("lines", []):
                for sp in ln.get("spans", []):
                    font = sp.get("font", "")
                    size = sp.get("size", 12.0) or 12.0
                    st = stats.setdefault(font, {"aa": 0, "am": 0, "zero": 0, "thai": 0})
                    for ch in sp.get("chars", []):
                        c = ch.get("c", "")
                        if not c:
                            continue
                        if c == T.SARA_AA:
                            st["aa"] += 1
                        elif c == T.SARA_AM:
                            st["am"] += 1
                        elif c.isspace():
                            x0, _, x1, _ = ch.get("bbox", (0, 0, 0, 0))
                            if (x1 - x0) < size * ZERO_WIDTH_RATIO:
                                st["zero"] += 1
                        if T.is_thai(c):
                            st["thai"] += 1

    broken = set()
    for font, st in stats.items():
        # ฟอนต์ที่กู้จากชื่อ glyph ได้แล้ว ไม่ต้องใช้วิธีเดาจากความกว้างอีก
        if font in skip:
            continue
        if st["thai"] < 20 or st["am"] == 0 or st["aa"] > 0:
            continue
        if st["zero"] > 0 or st["am"] >= 5:
            broken.add(font)
    return broken


def _heal_runs(runs: List[Run]) -> List[Run]:
    """
    ย้ายอักขระผสมที่ไปโผล่ต้น run ถัดไป กลับไปต่อท้าย run ก่อนหน้า

    PDF มักหั่นข้อความเป็นหลายช่วงตามฟอนต์หรือตำแหน่ง ทำให้วรรณยุกต์
    ถูกแยกจากพยัญชนะของมัน ถ้าไม่ซ่อมก่อน จะกลายเป็นวรรณยุกต์ลอย
    """
    healed: List[Run] = []
    for run in runs:
        text = run.text
        if healed and text and text[0] in T.COMBINING:
            i = 0
            while i < len(text) and text[i] in T.COMBINING:
                i += 1
            healed[-1].text += text[:i]
            text = text[i:]
        if text:
            run.text = text
            healed.append(run)
    return healed


def _merge_runs(runs: List[Run]) -> List[Run]:
    """รวม run ที่มีรูปแบบเหมือนกันติดกัน เพื่อให้ไฟล์ Word ไม่แตกเป็นชิ้นเล็กชิ้นน้อย"""
    merged: List[Run] = []
    for run in runs:
        if merged and merged[-1].style_key() == run.style_key() and merged[-1].font == run.font:
            merged[-1].text += run.text
        else:
            merged.append(run)
    return merged


def _extract_lines(page: "fitz.Page", issues: List[T.Issue],
                   broken_fonts: set = frozenset(),
                   fixes: Optional[dict] = None) -> List[Line]:
    raw = page.get_text("rawdict")
    # เก็บเป็นกลุ่มตามบล็อกก่อน เพื่อให้ซ่อมอักขระผสมที่ตกค้างข้ามบรรทัดได้
    # ก่อนจะจัดระเบียบอักขระไทย มิฉะนั้นวรรณยุกต์ที่อยู่ต้นบรรทัดจะถูกมองว่าลอยแล้วตัดทิ้ง
    blocks: List[List[Line]] = []

    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        group: List[Line] = []
        for ln in block.get("lines", []):
            runs: List[Run] = []
            prev_span_x1: Optional[float] = None

            for span in ln.get("spans", []):
                size = span.get("size", 12.0)
                text = _chars_to_text(span.get("chars", []), size,
                                      span.get("font", "") in broken_fonts, fixes)
                if not text:
                    continue

                # ช่องว่างระหว่าง span ในบรรทัดเดียวกัน
                sx0 = span.get("bbox", (0, 0, 0, 0))[0]
                if prev_span_x1 is not None and runs:
                    gap = sx0 - prev_span_x1
                    if gap > size * SPACE_RATIO and not runs[-1].text.endswith(" ") \
                            and not text.startswith(" "):
                        runs[-1].text += " "
                prev_span_x1 = span.get("bbox", (0, 0, 0, 0))[2]

                flags = span.get("flags", 0)
                runs.append(Run(
                    text=text,
                    font=span.get("font", ""),
                    size=size,
                    bold=bool(flags & 16) or "bold" in span.get("font", "").lower(),
                    italic=bool(flags & 2) or "italic" in span.get("font", "").lower(),
                    color=span.get("color", 0),
                ))

            if not runs:
                continue

            runs = _heal_runs(runs)
            group.append(Line(runs=runs, bbox=tuple(ln.get("bbox", (0, 0, 0, 0)))))

        if group:
            blocks.append(group)

    # ภาษาไทยตัดบรรทัดกลางพยางค์ได้ บรรทัดถัดไปจึงเริ่มด้วยวรรณยุกต์ของพยางค์เดิมได้
    # ต้องต่อกลับไปที่บรรทัดก่อนหน้า ไม่ใช่ตัดทิ้ง และต้องข้ามบล็อกได้ด้วย
    # เพราะตัวแบ่งโครงสร้างของไลบรารีหั่นย่อหน้าเดียวออกเป็นหลายบล็อกได้
    flat: List[Line] = [line for group in blocks for line in group]
    for i in range(1, len(flat)):
        head = flat[i].runs[0]
        tail = flat[i - 1].runs[-1] if flat[i - 1].runs else None
        cut = 0
        while cut < len(head.text) and head.text[cut] in T.COMBINING:
            cut += 1
        # ต่อให้เฉพาะเมื่อปลายบรรทัดก่อนหน้าเป็นตัวที่รับอักขระผสมได้จริง
        # ช่องว่างปิดท้ายบรรทัดเป็นผลจากการจัดหน้า ไม่ใช่เนื้อหา จึงตัดทิ้งก่อนต่อ
        if cut and tail:
            body = tail.text.rstrip()
            if body and body[-1] in T.VALID_BASES:
                tail.text = body + head.text[:cut]
                head.text = head.text[cut:]

    lines: List[Line] = []
    for line in flat:
        for run in line.runs:
            fixed, run_issues = T.normalize(run.text)
            run.text = fixed
            issues.extend(run_issues)
        line.runs = _merge_runs([r for r in line.runs if r.text])
        if line.runs:
            lines.append(line)

    return lines


# ------------------------------------------------------------------ บรรทัด -> ย่อหน้า
def _needs_space(prev: str, nxt: str) -> bool:
    """
    ตัดสินใจว่าจะแทรกช่องว่างตอนต่อบรรทัดหรือไม่

    ภาษาไทยตัดบรรทัดกลางคำได้โดยไม่มีเครื่องหมายใด ๆ
    ถ้าต่อบรรทัดแล้วใส่ช่องว่างทุกครั้ง คำจะถูกผ่าเป็นสองคำ
    จึงต่อแบบไม่มีช่องว่างเมื่อรอยต่อเป็นอักษรไทยทั้งสองฝั่ง
    """
    if not prev or not nxt:
        return False
    a, b = prev[-1], nxt[0]
    if a.isspace() or b.isspace():
        return False
    if T.is_thai(a) and T.is_thai(b):
        return False
    return True


def _guess_align(line_bbox, block_left: float, block_right: float) -> str:
    x0, _, x1, _ = line_bbox
    width = block_right - block_left
    if width <= 0:
        return "left"
    left_gap = x0 - block_left
    right_gap = block_right - x1
    if left_gap > width * 0.15 and abs(left_gap - right_gap) < width * 0.10:
        return "center"
    if left_gap > width * 0.30 and right_gap < width * 0.05:
        return "right"
    return "left"


def _lines_to_paragraphs(lines: List[Line]) -> List[Paragraph]:
    if not lines:
        return []

    block_left = min(l.bbox[0] for l in lines)
    block_right = max(l.bbox[2] for l in lines)

    # เอกสารที่เว้นระยะระหว่างย่อหน้า ใช้ระยะห่างตัดสินได้แม่นอยู่แล้ว
    # ส่วนเอกสารที่วางบรรทัดชิดเท่ากันหมด ต้องอาศัยความยาวบรรทัดเป็นตัวบอกแทน
    # วัดจากเอกสารจริงสามฟอนต์: ระยะภายในย่อหน้าไม่เกิน 0.39 เท่าของความสูงบรรทัด
    # ส่วนระยะระหว่างย่อหน้าต่ำสุด 0.73 เท่า เกณฑ์ตรงกลางจึงแยกสองกรณีได้ชัด
    def _is_para_gap(i: int) -> bool:
        prev_line = lines[i - 1]
        height = max(prev_line.bbox[3] - prev_line.bbox[1], 1.0)
        return (lines[i].bbox[1] - prev_line.bbox[3]) > height * (PARA_GAP_RATIO - 1.0)

    uses_spacing = any(_is_para_gap(i) for i in range(1, len(lines)))

    paragraphs: List[Paragraph] = []
    current: List[Line] = []

    def flush():
        if not current:
            return
        runs: List[Run] = []
        for idx, ln in enumerate(current):
            if idx > 0 and runs and ln.runs and _needs_space(runs[-1].text, ln.runs[0].text):
                runs[-1].text += " "
            runs.extend(replace(r) for r in ln.runs)

        runs = _merge_runs([r for r in runs if r.text])
        # Word ใส่ช่องว่างปิดท้ายบรรทัดสุดท้ายของย่อหน้ามาด้วย ซึ่งไม่ใช่เนื้อหา
        if runs:
            runs[0].text = runs[0].text.lstrip()
            runs[-1].text = runs[-1].text.rstrip()
        runs = [r for r in runs if r.text]
        if not runs:
            return
        sizes = [r.size for r in runs if r.text.strip()]
        para = Paragraph(
            runs=runs,
            align=_guess_align(current[0].bbox, block_left, block_right),
            bbox=(min(l.bbox[0] for l in current), current[0].bbox[1],
                  max(l.bbox[2] for l in current), current[-1].bbox[3]),
            size=max(sizes) if sizes else 12.0,
            bold=all(r.bold for r in runs if r.text.strip()),
        )
        paragraphs.append(para)

    for ln in lines:
        if not current:
            current = [ln]
            continue

        prev = current[-1]
        prev_h = max(prev.bbox[3] - prev.bbox[1], 1.0)
        v_gap = ln.bbox[1] - prev.bbox[3]
        prev_width = prev.bbox[2] - prev.bbox[0]
        block_width = max(block_right - block_left, 1.0)

        new_para = False
        if v_gap > prev_h * (PARA_GAP_RATIO - 1.0):
            new_para = True                      # เว้นระยะมากกว่าจังหวะปกติของเอกสาร
        elif not uses_spacing and prev_width < block_width * LINE_FULL_RATIO:
            new_para = True                      # บรรทัดก่อนหน้าสั้น = จบย่อหน้า
        elif abs(ln.bbox[0] - prev.bbox[0]) > 18:
            new_para = True                      # ย่อหน้าใหม่จากการเยื้อง
        elif ln.runs and prev.runs and abs(ln.runs[0].size - prev.runs[0].size) > 1.5:
            new_para = True                      # ขนาดตัวอักษรเปลี่ยน

        if new_para:
            flush()
            current = [ln]
        else:
            current.append(ln)

    flush()
    return paragraphs


# ------------------------------------------------------------------ ตาราง
def _cell_text(page: "fitz.Page", rect, broken_fonts: set = frozenset(),
               fixes: Optional[dict] = None) -> str:
    """อ่านข้อความในกรอบหนึ่งช่องตาราง ผ่านตัวอ่าน glyph ชุดเดียวกับข้อความปกติ"""
    raw = page.get_text("rawdict", clip=rect)
    pieces: List[str] = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for ln in block.get("lines", []):
            runs = [Run(_chars_to_text(sp.get("chars", []), sp.get("size", 12.0),
                                       sp.get("font", "") in broken_fonts, fixes))
                    for sp in ln.get("spans", [])]
            runs = _heal_runs([r for r in runs if r.text])
            line_text = "".join(r.text for r in runs).strip()
            if line_text:
                if pieces and not _needs_space(pieces[-1], line_text):
                    pieces[-1] += line_text
                else:
                    pieces.append(line_text)
    value, _ = T.normalize(" ".join(pieces).strip())
    return value


def _extract_tables(page: "fitz.Page", broken_fonts: set = frozenset(),
                    fixes: Optional[dict] = None) -> List[Table]:
    """
    ใช้ PyMuPDF หาโครงตาราง แล้วดึงข้อความในแต่ละช่องด้วยตัวอ่าน glyph ของเราเอง
    เพื่อให้ข้อความในตารางผ่านการจัดระเบียบภาษาไทยเหมือนกับข้อความปกติ
    """
    tables: List[Table] = []
    try:
        found = page.find_tables()
    except Exception:
        return tables

    for tbl in found:
        rows: List[List[str]] = []
        try:
            for row in tbl.rows:
                rows.append([_cell_text(page, fitz.Rect(c), broken_fonts, fixes)
                             if c else "" for c in row.cells])
        except Exception:
            # ถ้าโครงตารางอ่านทีละช่องไม่ได้ ใช้ผลของไลบรารีแล้วจัดระเบียบไทยต่อ
            try:
                rows = [[T.normalize((c or "").replace("\n", " ").strip())[0] for c in row]
                        for row in tbl.extract()]
            except Exception:
                continue

        if rows and any(any(c for c in r) for r in rows):
            tables.append(Table(rows=rows, bbox=tuple(tbl.bbox)))
    return tables


def _rects_overlap(a, b, tol: float = 2.0) -> bool:
    return not (a[2] < b[0] + tol or b[2] < a[0] + tol or
                a[3] < b[1] + tol or b[3] < a[1] + tol)


# ------------------------------------------------------------------ ทางเข้าหลัก
def extract_document(pdf_path: str, *, detect_tables: bool = True,
                     extract_images: bool = False,
                     password: str = "") -> Document:
    doc = fitz.open(pdf_path)
    if doc.needs_pass:
        if not doc.authenticate(password):
            doc.close()
            raise ValueError("ไฟล์ PDF ถูกใส่รหัสผ่าน และรหัสที่ให้มาเปิดไม่ได้")

    meta = doc.metadata or {}
    out = Document(path=pdf_path, producer=meta.get("producer", "") or "")
    font_names = set()

    # อ่านฟอนต์ที่ฝังมาในไฟล์ เพื่อกู้ตัวอักษรจากชื่อ glyph ซึ่งเชื่อถือได้กว่าตาราง ToUnicode
    glyph_maps = DocumentGlyphMaps(doc)
    covered = set()
    for pno in range(len(doc)):
        for name, xref in _font_xrefs(doc[pno]).items():
            if glyph_maps.for_xref(xref):
                covered.add(name)
    fixed_chars = 0

    # ฟอนต์ที่กู้จากชื่อ glyph ไม่ได้ ยังต้องอาศัยการเดาจากความกว้างของ glyph
    broken_fonts = _broken_sara_fonts(doc, covered)
    if broken_fonts:
        out.issues.append(T.Issue(
            "broken_font_map",
            "ฟอนต์ " + ", ".join(sorted(broken_fonts)) +
            " เก็บสระอาผิดเป็นสระอำ กู้คืนจากความกว้างของ glyph แล้ว",
            0, "", "fixed"))

    for pno in range(len(doc)):
        page = doc[pno]
        rect = page.rect
        issues: List[T.Issue] = []

        fixes = page_corrections(page, glyph_maps)
        fixed_chars += sum(len(bucket) for bucket in fixes.values())

        lines = _extract_lines(page, issues, broken_fonts, fixes)
        tables = _extract_tables(page, broken_fonts, fixes) if detect_tables else []

        # ข้อความที่อยู่ในกรอบตารางแล้ว ไม่ต้องซ้ำในย่อหน้า
        if tables:
            table_boxes = [t.bbox for t in tables]
            lines = [l for l in lines
                     if not any(_rects_overlap(l.bbox, tb) for tb in table_boxes)]

        paragraphs = _lines_to_paragraphs(lines)

        for ln in lines:
            for r in ln.runs:
                if r.font:
                    font_names.add(r.font)

        char_count = sum(len(p.text) for p in paragraphs) + sum(len(t.text) for t in tables)
        source = "text" if char_count > 0 else "empty"

        images = []
        if extract_images:
            for img in page.get_images(full=True):
                try:
                    pix = fitz.Pixmap(doc, img[0])
                    if pix.n - pix.alpha >= 4:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    images.append({"xref": img[0], "png": pix.tobytes("png"),
                                   "width": pix.width, "height": pix.height})
                except Exception:
                    continue

        out.pages.append(Page(
            number=pno + 1, width=rect.width, height=rect.height,
            paragraphs=paragraphs, tables=tables, images=images,
            char_count=char_count, source=source,
        ))
        out.issues.extend(issues)

    doc.close()
    out.fonts = sorted(font_names)
    if fixed_chars:
        out.issues.append(T.Issue(
            "glyph_map", T.ISSUE_LABELS["glyph_map"], 0,
            f"{fixed_chars} ตัว", "fixed"))

    full = out.text
    out.visual_order_suspect, out.visual_order_ratio = T.detect_visual_order(full)
    return out
