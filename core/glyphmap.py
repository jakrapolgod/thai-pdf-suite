# -*- coding: utf-8 -*-
"""
glyphmap.py - กู้ตัวอักษรจริงจากฟอนต์ที่ฝังอยู่ใน PDF

ทำไมต้องมีโมดูลนี้
------------------
PDF เก็บ "รูปตัวอักษร" (glyph) กับ "ตารางแปลงกลับเป็นข้อความ" (ToUnicode) แยกกัน
ตัวแปลงทั่วไปอ่านจากตาราง ToUnicode อย่างเดียว ซึ่งโปรแกรมต้นทางเขียนผิดได้บ่อยมาก
กับภาษาไทย เพราะฟอนต์ไทยใช้ glyph รูปแปรของสระและวรรณยุกต์หลายแบบ
(วรรณยุกต์ตัวเดียวกันมีหลายรูป ขึ้นกับว่าอยู่เหนือสระหรือเหนือพยัญชนะ)
รูปแปรเหล่านี้มักไม่มีในตาราง ToUnicode โปรแกรมจึงใส่ค่ามั่ว ๆ ลงไป

ที่พบจริงจากการทดสอบบนเครื่องนี้
* Excel ส่งออก PDF ด้วย TH Sarabun New แล้วแมปไม้โทเป็น "ช่องว่าง"
  ทำให้ "ทั้งสิ้น" กลายเป็น "ทั งสิ น"
* Word ส่งออก PDF ด้วย Tahoma/Angsana แล้วแมปสระอาเป็นสระอำ
  ทำให้ "ปาล์ม" กลายเป็น "ปำล์ม"

ทั้งสองกรณี **ตัว glyph ในไฟล์ถูกต้องทุกตัว** เสียแค่ตารางแปลงกลับ
โมดูลนี้จึงไปอ่านชื่อ glyph จากไฟล์ฟอนต์ที่ฝังมาใน PDF โดยตรง
ซึ่งเป็นแหล่งข้อมูลที่ตรงกับสิ่งที่ถูกวาดออกมาจริง แล้วใช้ค่านั้นแทน

ถ้าไม่มีไลบรารี fontTools หรือฟอนต์ไม่ได้ฝังมา โมดูลจะคืนค่าว่าง
แล้วตัวอ่านหลักจะถอยไปใช้วิธีเดิมโดยไม่พัง
"""
from __future__ import annotations

import io
from typing import Dict, Optional, Tuple

try:
    from fontTools.agl import toUnicode as _agl_to_unicode
    from fontTools.ttLib import TTFont
    HAVE_FONTTOOLS = True
except ImportError:      # ยังใช้งานได้ เพียงแต่กู้จากชื่อ glyph ไม่ได้
    HAVE_FONTTOOLS = False

# ค่าที่โปรแกรมต้นทางมักใส่มั่วเมื่อไม่รู้ว่า glyph นี้คือตัวอะไร
SUSPICIOUS = {0x0020, 0x0000, 0xFFFD, 0x00A0}


def _unicode_from_name(name: str) -> Optional[str]:
    """แปลงชื่อ glyph เป็นตัวอักษร รองรับทั้งชื่อมาตรฐานและรูปแบบ uniXXXX พร้อมส่วนขยาย"""
    if not name:
        return None
    try:
        text = _agl_to_unicode(name)
    except Exception:
        return None
    return text if len(text) == 1 else None


class FontGlyphMap:
    """ตารางแปลงหมายเลข glyph เป็นตัวอักษร ของฟอนต์หนึ่งตัวใน PDF"""

    def __init__(self, gid_to_char: Dict[int, str]):
        self.gid_to_char = gid_to_char

    def get(self, gid: int) -> Optional[str]:
        return self.gid_to_char.get(gid)

    def __bool__(self) -> bool:
        return bool(self.gid_to_char)


def _is_thai(ch: str) -> bool:
    return "฀" <= ch <= "๿"


def _variant_to_base(tt) -> Dict[str, str]:
    """
    ฟอนต์ไทยมี glyph รูปแปรของวรรณยุกต์และสระหลายแบบ เช่น วรรณยุกต์รูปเตี้ยที่ใช้
    เมื่อวางเหนือสระ รูปแปรเหล่านี้มักถูกตั้งชื่อเป็นรหัสพื้นที่ใช้งานส่วนตัว (uniF70x)
    ซึ่งบอกไม่ได้ว่าเป็นตัวอะไร

    ตาราง GSUB ของฟอนต์เก็บไว้อยู่แล้วว่ารูปแปรตัวไหนแทนตัวฐานตัวไหน
    จึงอ่านจากตรงนั้นแทนการเดา ซึ่งได้คำตอบที่ตรงกับฟอนต์นั้น ๆ จริง
    """
    mapping: Dict[str, str] = {}
    try:
        gsub = tt.get("GSUB")
        if gsub is None or not getattr(gsub, "table", None):
            return mapping
        for lookup in gsub.table.LookupList.Lookup:
            for sub in getattr(lookup, "SubTable", []) or []:
                pairs = getattr(sub, "mapping", None)
                if isinstance(pairs, dict):
                    for base, variant in pairs.items():
                        if isinstance(variant, str):
                            mapping.setdefault(variant, base)
    except Exception:
        return {}
    return mapping


def _build_font_map(font_bytes: bytes) -> FontGlyphMap:
    gid_to_char: Dict[int, str] = {}
    try:
        tt = TTFont(io.BytesIO(font_bytes), fontNumber=0, lazy=True,
                    ignoreDecompileErrors=True)
        order = tt.getGlyphOrder()
    except Exception:
        return FontGlyphMap({})

    # ตาราง cmap ของฟอนต์เป็นแหล่งที่น่าเชื่อถือที่สุดสำหรับ glyph พื้นฐาน
    name_to_char: Dict[str, str] = {}
    try:
        for code, gname in (tt.getBestCmap() or {}).items():
            name_to_char.setdefault(gname, chr(code))
    except Exception:
        pass

    variants = _variant_to_base(tt)

    def resolve(gname: str, depth: int = 0) -> Optional[str]:
        ch = name_to_char.get(gname) or _unicode_from_name(gname)
        # รหัสพื้นที่ใช้งานส่วนตัวไม่ได้บอกว่าเป็นตัวอะไร ต้องไล่กลับไปหาตัวฐาน
        if ch and not _is_thai(ch) and "" <= ch <= "" and depth < 4:
            base = variants.get(gname)
            if base:
                return resolve(base, depth + 1)
            return None
        if ch is None and depth < 4:
            base = variants.get(gname)
            if base:
                return resolve(base, depth + 1)
        return ch

    for gid, gname in enumerate(order):
        ch = resolve(gname)
        if ch:
            gid_to_char[gid] = ch

    try:
        tt.close()
    except Exception:
        pass
    return FontGlyphMap(gid_to_char)


class DocumentGlyphMaps:
    """เก็บตารางของทุกฟอนต์ในเอกสาร โหลดครั้งเดียวแล้วใช้ซ้ำทุกหน้า"""

    def __init__(self, doc):
        self.doc = doc
        self._cache: Dict[int, FontGlyphMap] = {}
        self.available = HAVE_FONTTOOLS

    def for_xref(self, xref: int) -> FontGlyphMap:
        if xref in self._cache:
            return self._cache[xref]
        fmap = FontGlyphMap({})
        if HAVE_FONTTOOLS and xref:
            try:
                _, _, _, buf = self.doc.extract_font(xref)
                if buf:
                    fmap = _build_font_map(buf)
            except Exception:
                fmap = FontGlyphMap({})
        self._cache[xref] = fmap
        return fmap


def _font_xrefs(page) -> Dict[str, int]:
    """ชื่อฟอนต์ที่ปรากฏในข้อความ -> หมายเลขอ้างอิงของไฟล์ฟอนต์ในเอกสาร"""
    out: Dict[str, int] = {}
    try:
        entries = page.get_fonts(full=True)
    except Exception:
        return out
    # จำนวนช่องของแต่ละรายการต่างกันไปตามรุ่นของไลบรารี จึงอ้างด้วยดัชนีแทนการแตกทูเพิล
    for item in entries:
        if len(item) < 4:
            continue
        xref, basefont = item[0], item[3]
        if not basefont:
            continue
        # PDF ใส่คำนำหน้าแบบ ABCDEF+ ให้ฟอนต์ที่ฝังมาเพียงบางส่วน
        out.setdefault(basefont, xref)
        out.setdefault(basefont.split("+")[-1], xref)
    return out


# ระยะคลาดเคลื่อนของพิกัดที่ยอมรับได้ตอนจับคู่ข้อมูลสองชุดจากหน้าเดียวกัน
MATCH_TOLERANCE = 0.4


def page_corrections(page, maps: DocumentGlyphMaps,
                     only_suspicious: bool = False) -> dict:
    """
    หาตัวอักษรที่ตารางแปลงกลับของ PDF ให้ค่าไม่ตรงกับ glyph ที่ถูกวาดจริง

    การจับคู่ใช้ (ตัวอักษรเดิมที่ตารางให้มา, แถว, ตำแหน่งแนวนอน) เป็นกุญแจ
    ใช้พิกัดอย่างเดียวไม่ได้ เพราะอักขระผสมของไทยวาดที่จุดเดียวกับพยัญชนะฐาน
    และข้อมูลสองชุดรายงานพิกัดต่างกันเล็กน้อยระดับ 0.02 หน่วย
    """
    fixes: dict = {}
    if not maps.available:
        return fixes

    xrefs = _font_xrefs(page)
    try:
        trace = page.get_texttrace()
    except Exception:
        return fixes

    for span in trace:
        if span.get("type") != 0:
            continue
        font_name = span.get("font", "")
        xref = xrefs.get(font_name) or xrefs.get(font_name.split("+")[-1])
        if not xref:
            continue
        fmap = maps.for_xref(xref)
        if not fmap:
            continue

        for item in span.get("chars", []):
            try:
                ucs, gid, origin = item[0], item[1], item[2]
            except (IndexError, TypeError):
                continue
            real = fmap.get(gid)
            if not real or ord(real) == ucs:
                continue
            if only_suspicious and ucs not in SUSPICIOUS:
                continue
            # แก้เฉพาะเมื่อ glyph จริงเป็นอักษรไทย หรือค่าเดิมเป็นค่าที่เห็นได้ชัดว่ามั่ว
            # ฟอนต์สัญลักษณ์บางตัวตั้งชื่อ glyph ตามระบบอื่น ถ้าเชื่อหมดจะกลายเป็นทำพัง
            if not (_is_thai(real) or ucs in SUSPICIOUS):
                continue
            fixes.setdefault((ucs, round(origin[1], 1)), []).append((origin[0], real))

    # ตัวอ่านแบบมีโครงสร้างยุบอักขระที่ซ้อนตำแหน่งกันเหลือตัวเดียว
    # เช่น "น้ำ" ที่เก็บวรรณยุกต์กับนิคหิตเป็นช่องว่างสองตัวติดกัน จะเหลือช่องว่างเดียว
    # จึงรวมการแก้ที่อยู่ตำแหน่งเดียวกันไว้เป็นค่าเดียวที่มีหลายตัวอักษร
    # เพื่อให้แทนที่กลับได้ครบทั้งสองตัวจากอักขระที่เหลืออยู่ตัวเดียว
    merged: dict = {}
    for key, entries in fixes.items():
        entries.sort(key=lambda e: e[0])
        bucket: list = []
        for x, ch in entries:
            if bucket and abs(bucket[-1][0] - x) <= 1.0:
                bucket[-1] = (bucket[-1][0], bucket[-1][1] + ch)
            else:
                bucket.append((x, ch))
        merged[key] = bucket
    return merged


def lookup_fix(fixes: dict, ucs: int, origin) -> Optional[str]:
    """หาตัวอักษรที่ถูกต้องของอักขระหนึ่งตัว จากตารางที่ page_corrections สร้างไว้"""
    if not fixes or not origin:
        return None
    bucket = fixes.get((ucs, round(origin[1], 1)))
    if not bucket:
        return None
    x = origin[0]
    best, best_dist = None, MATCH_TOLERANCE
    for fx, ch in bucket:
        dist = abs(fx - x)
        if dist < best_dist:
            best, best_dist = ch, dist
    return best
