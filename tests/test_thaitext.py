# -*- coding: utf-8 -*-
"""
ชุดทดสอบความถูกต้องของอักขระไทย
รันด้วย:  python tests/test_thaitext.py
ทุกเคสเทียบที่ระดับ code point ไม่ใช่ระดับสายตา เพราะข้อความสองชุดที่ดูเหมือนกัน
อาจเก็บ code point ต่างกันจนทำให้ Word วาดวรรณยุกต์เพี้ยน
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import thaitext as T  # noqa: E402

PASS, FAIL = 0, 0


def cp(s: str) -> str:
    """แสดงข้อความเป็นรายการ code point เพื่อให้เห็นความต่างที่ตามองไม่เห็น"""
    return " ".join(f"U+{ord(c):04X}" for c in s)


def check(name: str, got: str, want: str):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  [ผ่าน] {name}")
    else:
        FAIL += 1
        print(f"  [ตก ] {name}")
        print(f"         ได้     {got!r}  {cp(got)}")
        print(f"         ต้องการ {want!r}  {cp(want)}")


def check_true(name: str, cond: bool):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ผ่าน] {name}")
    else:
        FAIL += 1
        print(f"  [ตก ] {name}")


print("\n=== 1. สระอำแตกร่าง (มรดกฟอนต์ TIS-620) ===")
# "นํ้า" ที่พิมพ์จากฟอนต์เก่า: น + นิคหิต + ไม้โท + สระอา
legacy = "นํ้า"
check("นํ้า -> น้ำ", T.normalize(legacy)[0], "น้ำ")
# นิคหิตธรรมดา + สระอา (ไม่มีวรรณยุกต์)
check("นํา -> นำ", T.normalize("นํา")[0], "นำ")
# วรรณยุกต์วางหลังสระอำ
check("นำ+ไม้โท -> น้ำ", T.normalize("นำ้")[0], "น้ำ")

print("\n=== 2. สระแอแตกเป็นสระเอสองตัว ===")
check("เเละ -> และ", T.normalize("เเละ")[0], "และ")
check("เเต่ -> แต่", T.normalize("เเต่")[0], "แต่")

print("\n=== 3. ลำดับสระ/วรรณยุกต์สลับที่ ===")
# ไม้โท มาก่อน ไม้หันอากาศ -> ต้องสลับ
check("ก+โท+หันอากาศ -> กั้", T.normalize("ก้ั")[0], "กั้")
# ไม้โท มาก่อน สระอิ
check("ท+โท+อิ -> ทิ้", T.normalize("ท้ิ")[0], "ทิ้")
# ทัณฑฆาต ต้องอยู่ท้ายสุด
check("ทัณฑฆาตอยู่ท้าย", T.normalize("ร์์")[0], "ร์")
# ลำดับถูกอยู่แล้ว ต้องไม่ถูกแตะ
already = "กั้ว"   # กั้ว
check("ลำดับถูกแล้วไม่เปลี่ยน", T.normalize(already)[0], already)

print("\n=== 4. อักขระซ้ำซ้อน / ขัดแย้ง ===")
check("วรรณยุกต์ซ้ำ -> เหลือตัวเดียว", T.normalize("ก้้")[0], "ก้")
check("วรรณยุกต์สองชนิด -> เก็บตัวแรก", T.normalize("ก่้")[0], "ก่")

print("\n=== 5. วรรณยุกต์ลอย / เกาะผิดตัว ===")
check("วรรณยุกต์ลอยหน้าข้อความ -> ตัดทิ้ง", T.normalize("้กา")[0], "กา")
# เ + ไม้เอก + ก + ง  ->  เ + ก + ไม้เอก + ง   (เก่ง)
check("วรรณยุกต์เกาะสระหน้า -> ย้ายไปพยัญชนะ",
      T.normalize("เ่กง")[0], "เก่ง")

print("\n=== 6. ข้อความไทยปกติต้องไม่ถูกแก้ ===")
for sample in [
    "สวัสดีครับ ผมชื่อจักรพล",
    "บริษัท Thai PDF Suite จำกัด",
    "ใบกำกับภาษี เลขที่ INV-2569/001",
    "ยอดรวมทั้งสิ้น 1,234,567.89 บาท",
    "ก้าวไกลไปกับเทคโนโลยี ๙๙ ปีที่แล้ว",
    "น้ำมันปาล์มดิบ CPO คุณภาพสูง",
]:
    out, issues = T.normalize(sample)
    check(f"คงเดิม: {sample[:28]}", out, sample)
    check_true(f"  ไม่มีปัญหาค้าง: {sample[:20]}", len(T.audit(out)) == 0)

print("\n=== 7. audit จับของเสียได้จริง ===")
check_true("audit เจอวรรณยุกต์ลอย", len(T.audit("้ก")) > 0)
check_true("audit เจอลำดับผิด", len(T.audit("ก้ั")) > 0)
check_true("audit เจอนิคหิต+สระอา", len(T.audit("นํา")) > 0)
check_true("audit ผ่านข้อความสะอาด", len(T.audit("น้ำใจงดงาม")) == 0)

print("\n=== 8. ตรวจจับการเรียงตามสายตา ===")
ok_logical = "เก่งมากเลยเพื่อนเรา เธอเดินเร็วเหลือเกิน"
suspect, ratio = T.detect_visual_order(ok_logical)
check_true(f"ข้อความปกติไม่ถูกเตือน (ratio={ratio:.2f})", not suspect)
visual = "กเ่งมากลเยพเ่ือนรเา ธเอดเินรเ็วหลเือกิเน"
suspect2, ratio2 = T.detect_visual_order(visual)
check_true(f"ข้อความเรียงตามสายตาถูกจับได้ (ratio={ratio2:.2f})", suspect2)

print("\n=== 9. ซ่อมข้อความที่ถอดรหัสผิด ===")
broken = "สวัสดีครับ".encode("utf-8").decode("latin-1")
check("UTF-8 ที่ถูกอ่านเป็น latin-1", T.normalize(broken)[0], "สวัสดีครับ")

print("\n=== 10. ครบวงจร: เอกสารเสียหนัก ===")
# รวมทุกโรคไว้ในบรรทัดเดียว
sick = ("เเบบ"          # เเบบ -> แบบ
        "นํ้า"          # นํ้า -> น้ำ
        "ท้ิ้ง")   # ท+โท+อิ+โท+ง -> ทิ้ง
want = "แบบน้ำทิ้ง"
check("แบบน้ำทิ้ง", T.normalize(sick)[0], want)
check_true("ผลลัพธ์ผ่าน audit", len(T.audit(T.normalize(sick)[0])) == 0)

print("\n" + "=" * 60)
print(f"ผ่าน {PASS} ตก {FAIL}")
print("=" * 60)
sys.exit(1 if FAIL else 0)
