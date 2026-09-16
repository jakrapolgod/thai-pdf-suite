# -*- coding: utf-8 -*-
"""
ทดสอบเส้นทาง OCR ด้วย PDF สแกนจำลอง

วิธีทดสอบ: เอาหน้าเดิมที่รู้ข้อความจริงอยู่แล้ว มาแปลงเป็นภาพล้วน (ไม่มีชั้นข้อความ)
แล้วให้แอปอ่านกลับ จากนั้นวัดความแม่นเทียบกับข้อความจริง
ทำแบบนี้จึงรู้ค่าความแม่นจริง ไม่ใช่เดาเอา

ต้องมี Tesseract + tha.traineddata ก่อน  รันด้วย:  python tests/test_ocr.py
"""
import sys
from difflib import SequenceMatcher
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import ocr as O          # noqa: E402
from core import thaitext as T     # noqa: E402

OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)
SCAN = OUT / "_scan.pdf"

PASS, FAIL = 0, 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ผ่าน] {name}  {extra}")
    else:
        FAIL += 1
        print(f"  [ตก ] {name}  {extra}")


def make_scan(src: Path, dst: Path, dpi: int = 200):
    """แปลง PDF เป็นภาพล้วน เลียนแบบเอกสารที่ถูกสแกนมา"""
    src_doc = fitz.open(src)
    out = fitz.open()
    for page in src_doc:
        pix = page.get_pixmap(dpi=dpi)
        new = out.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, pixmap=pix)
    out.save(dst)
    out.close()
    src_doc.close()


def squash(s: str) -> str:
    return "".join(s.split())


status = O.check_ocr()
print(f"\nเอนจิน: {status.version}  ภาษา: {status.languages}")
if not status.available:
    print("ข้ามการทดสอบ เพราะยังไม่มีภาษาไทยใน Tesseract")
    print(status.hint)
    sys.exit(0)

print("\n=== 1. เตรียม PDF สแกนจำลอง ===")
make_scan(ROOT / "tests" / "sample_thai.pdf", SCAN)
from core.extract import extract_document       # noqa: E402
plain = extract_document(str(SCAN))
check("ไฟล์สแกนไม่มีชั้นข้อความจริง", plain.pages[0].char_count == 0,
      f"อ่านได้ {plain.pages[0].char_count} ตัว")
check("แอปรู้ว่าต้องใช้ OCR", plain.needs_ocr_pages == [1])

print("\n=== 2. อ่านด้วย OCR ===")
result = O.ocr_document(str(SCAN), [1], lang="tha+eng", dpi=300)
page = result["pages"][0]
check("ได้ข้อความกลับมา", page.char_count > 300, f"{page.char_count} ตัวอักษร")
check("ทำเครื่องหมายว่ามาจาก OCR", page.source == "ocr")
check("มีค่าความมั่นใจ", page.ocr_confidence is not None,
      f"เฉลี่ย {page.ocr_confidence}%")

print("\n=== 3. โครงสร้างอักขระไทยของผล OCR ต้องถูกต้อง ===")
text = page.text
problems = T.audit(text)
check("ไม่มีวรรณยุกต์ลอยหรือลำดับผิด", len(problems) == 0,
      f"พบ {len(problems)} จุด")
check("สัดส่วนภาษาไทยสมเหตุสมผล", T.thai_ratio(text) > 0.6,
      f"{T.thai_ratio(text):.0%}")

print("\n=== 4. วัดความแม่นเทียบข้อความจริง ===")
# หมายเหตุสำคัญ: OCR ภาษาไทยไม่มีทางแม่น 100% เกณฑ์ตรงนี้จึงตั้งไว้กันการถอยหลัง
# ไม่ใช่คำรับประกัน ตัวเลขจริงขึ้นกับคุณภาพการสแกนและฟอนต์ของเอกสารแต่ละใบ
truth_doc = extract_document(str(ROOT / "tests" / "sample_thai.pdf"))
truth = squash(truth_doc.text)
got = squash(text)
ratio = SequenceMatcher(None, truth, got).ratio()
print(f"  ความเหมือนระดับตัวอักษร: {ratio:.1%}  ({len(truth)} เทียบ {len(got)} ตัว)")
check("ความแม่นไม่ถอยหลังจากที่วัดไว้ (เกณฑ์กันถอย 60%)", ratio > 0.60,
      f"ได้ {ratio:.1%}")

phrases = ["น้ำมันปาล์มดิบ", "รายการ", "จำนวน", "หน่วย", "บริษัท",
           "ไตรมาส", "รวมทั้งสิ้น", "ปาล์ม", "รายงาน", "ดำเนินงาน"]
hits = [p for p in phrases if squash(p) in got]
print(f"\n  คำสำคัญที่อ่านได้ถูก {len(hits)}/{len(phrases)}: {' '.join(hits)}")
misses = [p for p in phrases if p not in hits]
if misses:
    print(f"  ที่ยังอ่านผิด: {' '.join(misses)}  <- เป็นข้อจำกัดของเอนจิน ไม่ใช่ของตัวจัดระเบียบ")
check("อ่านคำสำคัญถูกเกินครึ่ง", len(hits) >= len(phrases) // 2,
      f"{len(hits)}/{len(phrases)}")

print("\n  ไม่มีช่องว่างแทรกกลางคำไทย:")
# สนใจเฉพาะอักขระผสม (สระบน สระล่าง วรรณยุกต์ ทัณฑฆาต) ที่ต้องเกาะพยัญชนะเสมอ
# ไม่รวมสระหน้าอย่าง เ แ โ ใ ไ ซึ่งขึ้นต้นคำใหม่หลังช่องว่างได้ตามปกติ
bad_spaces = [text[max(0, i - 6):i + 2] for i, c in enumerate(text)
              if c in T.COMBINING and i > 0 and text[i - 1] == " "]
check("    ไม่พบช่องว่างก่อนอักขระผสม", not bad_spaces, f"{bad_spaces[:3]}")

print("\n=== 5. คำที่ความมั่นใจต่ำถูกยกมาให้ตรวจ ===")
suspects = result["suspects"]
print(f"  คำที่ต่ำกว่า 75%: {len(suspects)} คำ")
for s in suspects[:6]:
    print(f"    {s['text']!r}  {s['confidence']}%")
check("รายการคำน่าสงสัยทำงาน", isinstance(suspects, list))
check("ทุกคำน่าสงสัยมีตำแหน่งบนหน้า",
      all(len(s["bbox"]) == 4 for s in suspects))

print("\n" + "=" * 60)
print(f"ผ่าน {PASS} ตก {FAIL}")
print("=" * 60)
sys.exit(1 if FAIL else 0)
