# -*- coding: utf-8 -*-
"""
thaitext.py - ชั้นรักษาความถูกต้องของอักขระไทย

ปัญหาไทยเพี้ยนใน PDF -> Word/Excel เกิดจาก 4 สาเหตุหลัก และโมดูลนี้จัดการทั้ง 4:

1. ลำดับอักขระผสมผิด (combining order)
   "น" + "้" + "ั"  ควรเป็น  "น" + "ั" + "้"   (สระบน -> วรรณยุกต์ -> ทัณฑฆาต)
   ถ้าลำดับผิด Word จะวาดวรรณยุกต์ทับสระหรือลอยผิดตำแหน่ง

2. สระอำแตกร่าง (SARA AM decomposition)
   "นํ้า" = น + นิคหิต + ไม้โท + สระอา   ซึ่งควรเป็น  น + ไม้โท + สระอำ
   เป็นมรดกจากฟอนต์ไทยยุค TIS-620 เจอบ่อยมากในเอกสารราชการเก่า

3. สระแอแตกเป็นสระเอสองตัว  เ + เ  ต้องรวมเป็น  แ

4. ช่องว่างปลอมระหว่างตัวอักษร  "ก า ร" (PDF วางตัวอักษรทีละตัว)
   -> แก้ที่ชั้น extract โดยดูระยะห่างจริงของ glyph ไม่ใช่ที่นี่

ทุกการแก้ไขถูกบันทึกเป็น Issue พร้อมตำแหน่งและบริบท เพื่อให้ตรวจสอบย้อนหลังได้
ไม่มีการเดาแล้วแก้เงียบ ๆ
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import List, Tuple

# ---------------------------------------------------------------- ชั้นอักขระ
# ช่วง Unicode ภาษาไทย U+0E00 - U+0E7F
CONSONANTS = {chr(c) for c in range(0x0E01, 0x0E2F)}       # ก .. ฮ
SARA_A = "ะ"           # ะ
MAI_HAN_AKAT = "ั"     # ไม้หันอากาศ
SARA_AA = "า"          # า
SARA_AM = "ำ"          # ำ
PHINTHU = "ฺ"          # พินทุ
LEAD_VOWELS = set("เแโใไ")         # เ แ โ ใ ไ
FOLLOW_VOWELS = set("ะาำๅ")             # ะ า ำ ๅ
ABOVE_VOWELS = set("ัิีึื็")  # ไม้หันอากาศ อิ อี อึ อื ไม้ไต่คู้
BELOW_VOWELS = set("ฺุู")                    # อุ อู พินทุ
TONES = set("่้๊๋")                     # เอก โท ตรี จัตวา
THANTHAKHAT = "์"      # ทัณฑฆาต
NIKHAHIT = "ํ"         # นิคหิต
YAMAKKAN = "๎"         # ยามักการ
SARA_E = "เ"           # เ
SARA_AE = "แ"          # แ
MAIYAMOK = "ๆ"         # ๆ
PAIYANNOI = "ฯ"        # ฯ

THAI_DIGITS = {chr(c) for c in range(0x0E50, 0x0E5A)}
ZERO_WIDTH = "​‌‍﻿­"

# ลำดับมาตรฐานภายในหนึ่งพยางค์ (WTT 2.0):
#   พยัญชนะฐาน -> สระบน/ล่าง -> วรรณยุกต์ -> ทัณฑฆาต
CANON_ORDER = {}
for _c in ABOVE_VOWELS | BELOW_VOWELS:
    CANON_ORDER[_c] = 1
CANON_ORDER[NIKHAHIT] = 1
for _c in TONES:
    CANON_ORDER[_c] = 2
CANON_ORDER[THANTHAKHAT] = 3
CANON_ORDER[YAMAKKAN] = 3

COMBINING = set(CANON_ORDER)

# ฐานที่รับอักขระผสมได้อย่างถูกต้อง (รวม ฤ ฦ)
VALID_BASES = CONSONANTS | {SARA_AA, SARA_A, MAIYAMOK, chr(0x0E24), chr(0x0E26)}


def is_thai(ch: str) -> bool:
    return "฀" <= ch <= "๿"


def thai_ratio(text: str) -> float:
    """สัดส่วนอักขระไทยต่ออักขระที่ไม่ใช่ช่องว่างทั้งหมด"""
    body = [c for c in text if not c.isspace()]
    if not body:
        return 0.0
    return sum(1 for c in body if is_thai(c)) / len(body)


# ---------------------------------------------------------------- รายงานปัญหา
@dataclass
class Issue:
    kind: str                  # รหัสปัญหา
    detail: str                # คำอธิบายภาษาไทย
    index: int                 # ตำแหน่งในข้อความต้นฉบับ
    context: str = ""          # บริบทรอบจุดที่พบ
    severity: str = "fixed"    # fixed | warn | error
    before: str = ""
    after: str = ""


ISSUE_LABELS = {
    "mojibake": "ข้อความถูกถอดรหัสผิดชุดตัวอักษร ซ่อมด้วยการเข้ารหัสใหม่",
    "double_sara_e": "สระเอซ้อนสองตัว รวมเป็นสระแอ",
    "nikhahit_aa": "นิคหิต+สระอา รวมเป็นสระอำ",
    "nikhahit_redundant": "นิคหิตซ้ำซ้อนกับสระอำ ตัดออก",
    "broken_font_map": "ฟอนต์เก็บสระอาผิดเป็นสระอำ กู้คืนจากความกว้างของ glyph",
    "glyph_map": "ตารางแปลงกลับเป็นข้อความของ PDF ผิด กู้ตัวอักษรจริงจากฟอนต์ที่ฝังในไฟล์",
    "sara_am_tone": "วรรณยุกต์อยู่หลังสระอำ ย้ายมาไว้หน้าสระอำ",
    "reorder": "ลำดับสระ/วรรณยุกต์ผิด จัดเรียงใหม่ตามมาตรฐาน",
    "duplicate_mark": "อักขระผสมซ้ำซ้อน ตัดตัวเกินออก",
    "multi_tone": "วรรณยุกต์ซ้อนกันเกินหนึ่งตัว เก็บตัวแรกไว้",
    "multi_vowel": "สระบน/ล่างซ้อนกันเกินหนึ่งตัว เก็บตัวแรกไว้",
    "orphan_mark": "วรรณยุกต์หรือสระลอย ไม่มีพยัญชนะฐาน",
    "mark_on_lead_vowel": "วรรณยุกต์เกาะสระหน้า ย้ายไปพยัญชนะตัวถัดไป",
    "zero_width": "ลบอักขระความกว้างศูนย์",
    "visual_order": "สงสัยว่าไฟล์เก็บข้อความแบบเรียงตามสายตา ไม่ใช่ลำดับตรรกะ",
}


# ---------------------------------------------------------------- ซ่อม mojibake
def repair_encoding(text: str) -> Tuple[str, List[Issue]]:
    """
    ซ่อมกรณีไบต์ UTF-8 ของไทยถูกอ่านเป็น latin-1/cp1252 (เห็นเป็นตัวประหลาด)
    ยอมรับผลลัพธ์ก็ต่อเมื่อซ่อมแล้วได้อักขระไทยจริง เพื่อไม่ให้ทำลายข้อความที่ดีอยู่แล้ว
    """
    if thai_ratio(text) > 0.05:
        return text, []

    def _attempt(wrong: str, right: str):
        try:
            return text.encode(wrong, errors="strict").decode(right, errors="strict")
        except (UnicodeEncodeError, UnicodeDecodeError, LookupError):
            return None

    for wrong, right in (("latin-1", "utf-8"), ("cp1252", "utf-8"), ("cp1252", "cp874")):
        cand = _attempt(wrong, right)
        if cand and thai_ratio(cand) > 0.30:
            return cand, [Issue("mojibake", ISSUE_LABELS["mojibake"], 0,
                                text[:40], "fixed", text[:40], cand[:40])]
    return text, []


# ---------------------------------------------------------------- ตัวจัดระเบียบ
@dataclass
class _Cluster:
    base: str
    marks: List[str] = field(default_factory=list)
    sara_am: bool = False
    index: int = 0

    def render(self) -> str:
        return self.base + "".join(self.marks) + (SARA_AM if self.sara_am else "")


def _ctx(text: str, i: int, width: int = 12) -> str:
    return text[max(0, i - width): i + width]


def normalize(text: str, *, strip_zero_width: bool = True,
              repair_mojibake: bool = True) -> Tuple[str, List[Issue]]:
    """
    ทำให้ข้อความไทยอยู่ในรูปแบบมาตรฐานที่ Word/Excel วาดได้ถูกต้อง
    คืนค่า (ข้อความที่จัดแล้ว, รายการสิ่งที่แก้ไข)
    """
    issues: List[Issue] = []
    if not text:
        return text, issues

    if repair_mojibake:
        text, mj = repair_encoding(text)
        issues.extend(mj)

    text = unicodedata.normalize("NFC", text)

    if strip_zero_width:
        cleaned = "".join(c for c in text if c not in ZERO_WIDTH)
        if cleaned != text:
            issues.append(Issue("zero_width", ISSUE_LABELS["zero_width"], 0, "", "fixed"))
            text = cleaned

    # สระเอซ้อน -> สระแอ (เ+เ ไม่มีทางถูกต้องในภาษาไทย)
    while SARA_E + SARA_E in text:
        pos = text.find(SARA_E + SARA_E)
        issues.append(Issue("double_sara_e", ISSUE_LABELS["double_sara_e"], pos,
                            _ctx(text, pos), "fixed", SARA_E + SARA_E, SARA_AE))
        text = text.replace(SARA_E + SARA_E, SARA_AE, 1)

    clusters: List[_Cluster] = []
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]

        if ch in COMBINING:
            # อักขระผสมที่ไม่มีฐาน - ตัดทิ้งและบันทึกไว้
            issues.append(Issue("orphan_mark", ISSUE_LABELS["orphan_mark"], i,
                                _ctx(text, i), "warn", ch, ""))
            i += 1
            continue

        cl = _Cluster(base=ch, index=i)
        i += 1
        while i < n:
            c = text[i]
            if c in COMBINING:
                cl.marks.append(c)
                i += 1
            elif c == SARA_AM and not cl.sara_am and cl.base in VALID_BASES:
                # วรรณยุกต์ที่ตามหลังสระอำ จะถูกดึงกลับมาไว้หน้าสระอำโดยอัตโนมัติ
                if i + 1 < n and text[i + 1] in TONES:
                    issues.append(Issue("sara_am_tone", ISSUE_LABELS["sara_am_tone"], i,
                                        _ctx(text, i), "fixed",
                                        cl.base + SARA_AM + text[i + 1],
                                        cl.base + text[i + 1] + SARA_AM))
                cl.sara_am = True
                i += 1
            else:
                break

        # นิคหิต + สระอา -> สระอำ
        if NIKHAHIT in cl.marks and i < n and text[i] == SARA_AA:
            cl.marks.remove(NIKHAHIT)
            issues.append(Issue("nikhahit_aa", ISSUE_LABELS["nikhahit_aa"], i,
                                _ctx(text, i), "fixed", NIKHAHIT + SARA_AA, SARA_AM))
            cl.sara_am = True
            i += 1

        # สระอำมีนิคหิตอยู่ในตัวอยู่แล้ว ถ้ามีนิคหิตซ้ำอีกตัวถือว่าเกิน
        if NIKHAHIT in cl.marks and cl.sara_am:
            cl.marks.remove(NIKHAHIT)
            issues.append(Issue("nikhahit_redundant", ISSUE_LABELS["nikhahit_redundant"],
                                cl.index, _ctx(text, cl.index), "fixed",
                                NIKHAHIT + SARA_AM, SARA_AM))

        clusters.append(cl)

    # วรรณยุกต์ที่เกาะสระหน้า ต้องย้ายไปพยัญชนะตัวถัดไป
    for k, cl in enumerate(clusters):
        if cl.base in LEAD_VOWELS and cl.marks:
            if k + 1 < len(clusters) and clusters[k + 1].base in CONSONANTS:
                issues.append(Issue("mark_on_lead_vowel", ISSUE_LABELS["mark_on_lead_vowel"],
                                    cl.index, "".join(cl.marks), "fixed",
                                    cl.base + "".join(cl.marks),
                                    cl.base + clusters[k + 1].base + "".join(cl.marks)))
                clusters[k + 1].marks = cl.marks + clusters[k + 1].marks
                cl.marks = []

    out = []
    for cl in clusters:
        if cl.marks:
            cl.marks = _order_marks(cl, text, issues)
        out.append(cl.render())

    return "".join(out), issues


def _order_marks(cl: _Cluster, text: str, issues: List[Issue]) -> List[str]:
    """ตัดอักขระผสมที่ซ้ำหรือขัดแย้ง แล้วเรียงตามลำดับมาตรฐาน"""
    original = list(cl.marks)

    seen = set()
    dedup = []
    for m in original:
        if m in seen:
            issues.append(Issue("duplicate_mark", ISSUE_LABELS["duplicate_mark"], cl.index,
                                _ctx(text, cl.index), "fixed", m, ""))
            continue
        seen.add(m)
        dedup.append(m)

    # วรรณยุกต์ได้มากสุดหนึ่งตัวต่อพยางค์ สระบน/ล่างก็เช่นกัน
    kept, tone_used, vowel_used = [], False, False
    for m in dedup:
        if m in TONES:
            if tone_used:
                issues.append(Issue("multi_tone", ISSUE_LABELS["multi_tone"], cl.index,
                                    _ctx(text, cl.index), "warn", m, ""))
                continue
            tone_used = True
        elif m in ABOVE_VOWELS or m in BELOW_VOWELS:
            if vowel_used:
                issues.append(Issue("multi_vowel", ISSUE_LABELS["multi_vowel"], cl.index,
                                    _ctx(text, cl.index), "warn", m, ""))
                continue
            vowel_used = True
        kept.append(m)

    ordered = sorted(kept, key=lambda m: CANON_ORDER[m])
    if ordered != original and len(ordered) == len(original):
        issues.append(Issue("reorder", ISSUE_LABELS["reorder"], cl.index,
                            _ctx(text, cl.index), "fixed",
                            cl.base + "".join(original), cl.base + "".join(ordered)))
    return ordered


# ---------------------------------------------------------------- ตรวจสอบผลลัพธ์
def audit(text: str) -> List[Issue]:
    """
    ตรวจข้อความ *หลัง* จัดระเบียบแล้ว ว่ายังเหลือรูปแบบที่เป็นไปไม่ได้ในภาษาไทยหรือไม่
    ถ้าคืนลิสต์ว่าง แปลว่าโครงสร้างอักขระไทยถูกต้องตามกฎทุกตัว
    """
    problems: List[Issue] = []
    prev_base = ""
    run: List[str] = []

    for i, ch in enumerate(text):
        if ch in COMBINING:
            if not prev_base or prev_base not in VALID_BASES:
                problems.append(Issue("orphan_mark", ISSUE_LABELS["orphan_mark"], i,
                                      _ctx(text, i), "error", ch, ""))
            else:
                run.append(ch)
                order = [CANON_ORDER[m] for m in run]
                if order != sorted(order):
                    problems.append(Issue("reorder", ISSUE_LABELS["reorder"], i,
                                          _ctx(text, i), "error", "".join(run), ""))
                if sum(1 for m in run if m in TONES) > 1:
                    problems.append(Issue("multi_tone", ISSUE_LABELS["multi_tone"], i,
                                          _ctx(text, i), "error", "".join(run), ""))
            continue
        run = []
        prev_base = ch

    for pat, kind in ((NIKHAHIT + SARA_AA, "nikhahit_aa"), (SARA_E + SARA_E, "double_sara_e")):
        if pat in text:
            pos = text.find(pat)
            problems.append(Issue(kind, ISSUE_LABELS[kind], pos, _ctx(text, pos), "error"))
    return problems


def detect_visual_order(text: str) -> Tuple[bool, float]:
    """
    PDF บางตัวเก็บข้อความตามที่ตาเห็น ทำให้สระหน้าไปอยู่หลังพยัญชนะ
    ในภาษาไทยที่ลำดับถูกต้อง สระหน้าจะตามด้วยพยัญชนะเสมอ
    คืน (น่าสงสัยหรือไม่, สัดส่วนสระหน้าที่ผิดปกติ)
    """
    leads = [i for i, c in enumerate(text) if c in LEAD_VOWELS]
    if len(leads) < 5:
        return False, 0.0
    bad = sum(1 for i in leads
              if (text[i + 1] if i + 1 < len(text) else "") not in CONSONANTS)
    ratio = bad / len(leads)
    return ratio > 0.5, ratio


def fix_visual_order(text: str) -> Tuple[str, int]:
    """สลับสระหน้าที่ถูกเก็บไว้หลังพยัญชนะกลับเป็นลำดับตรรกะ (ใช้เมื่อผู้ใช้สั่งเท่านั้น)"""
    chars = list(text)
    swaps = 0
    i = 0
    while i < len(chars) - 1:
        if chars[i] in CONSONANTS and chars[i + 1] in LEAD_VOWELS:
            nxt = chars[i + 2] if i + 2 < len(chars) else ""
            if nxt not in CONSONANTS:
                chars[i], chars[i + 1] = chars[i + 1], chars[i]
                swaps += 1
                i += 2
                continue
        i += 1
    return "".join(chars), swaps


def summarize(issues: List[Issue]) -> list:
    """สรุปจำนวนปัญหาแต่ละชนิด สำหรับแสดงผลบนหน้าจอ"""
    out: dict = {}
    for it in issues:
        row = out.setdefault(it.kind, {
            "kind": it.kind,
            "label": ISSUE_LABELS.get(it.kind, it.kind),
            "count": 0,
            "severity": it.severity,
            "samples": [],
        })
        row["count"] += 1
        if it.severity == "error":
            row["severity"] = "error"
        elif it.severity == "warn" and row["severity"] == "fixed":
            row["severity"] = "warn"
        if len(row["samples"]) < 3 and (it.before or it.context):
            row["samples"].append({
                "context": it.context, "before": it.before, "after": it.after,
            })
    return sorted(out.values(), key=lambda r: -r["count"])
