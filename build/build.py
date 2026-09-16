# -*- coding: utf-8 -*-
"""
สร้างโปรแกรมติดตั้งสำหรับ Windows ตั้งแต่ต้นจนจบ

ขั้นตอน
  1. สร้างไอคอนจากฟอนต์ไทยในเครื่อง
  2. รันชุดทดสอบทั้งหมด (ข้ามได้ด้วย --skip-tests)
  3. แพ็กเป็น .exe ด้วย PyInstaller
  4. ห่อเป็นตัวติดตั้งด้วย Inno Setup

รันด้วย:  python build/build.py
หรือกดไฟล์:  build\build.bat
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
WORK = ROOT / "build" / "work"

ISCC_CANDIDATES = [
    Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe")),
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
]

TESTS = ["test_thaitext.py", "test_pipeline.py", "test_ocr.py", "test_final_audit.py"]


def step(number: int, title: str) -> None:
    print(f"\n{'=' * 62}\n  ขั้นที่ {number}: {title}\n{'=' * 62}")


def run(args, cwd: Path = ROOT, quiet: bool = True) -> int:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if quiet:
        proc = subprocess.run(args, cwd=str(cwd), env=env,
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            print(proc.stdout[-3000:])
            print(proc.stderr[-3000:])
        return proc.returncode
    return subprocess.run(args, cwd=str(cwd), env=env).returncode


def find_iscc() -> Path | None:
    found = shutil.which("ISCC")
    if found:
        return Path(found)
    for path in ISCC_CANDIDATES:
        if path.is_file():
            return path
    return None


def stop_running_app() -> None:
    """ตัวโปรแกรมที่เปิดค้างอยู่จะล็อกไฟล์ไว้ ทำให้แพ็กทับไม่ได้"""
    subprocess.run(["taskkill", "/F", "/IM", "ThaiPDFSuite.exe"],
                   capture_output=True)


def main() -> int:
    started = time.time()
    skip_tests = "--skip-tests" in sys.argv

    step(1, "สร้างไอคอน")
    if run([sys.executable, str(ROOT / "build" / "make_icon.py")]) != 0:
        print("สร้างไอคอนไม่สำเร็จ")
        return 1
    print("เรียบร้อย")

    step(2, "รันชุดทดสอบ")
    if skip_tests:
        print("ข้ามตามที่สั่ง (--skip-tests)")
    else:
        for name in TESTS:
            path = ROOT / "tests" / name
            if not path.is_file():
                continue
            print(f"  {name} ...", end=" ", flush=True)
            if run([sys.executable, str(path)]) != 0:
                print("ไม่ผ่าน")
                print("หยุดการสร้าง เพราะชุดทดสอบไม่ผ่าน")
                return 1
            print("ผ่าน")

    step(3, "แพ็กเป็นไฟล์ .exe")
    stop_running_app()
    code = run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                "--distpath", str(DIST), "--workpath", str(WORK),
                str(ROOT / "build" / "ThaiPDFSuite.spec")])
    exe = DIST / "ThaiPDFSuite" / "ThaiPDFSuite.exe"
    if code != 0 or not exe.is_file():
        print("แพ็กไม่สำเร็จ")
        return 1
    size = sum(f.stat().st_size for f in (DIST / "ThaiPDFSuite").rglob("*") if f.is_file())
    print(f"เรียบร้อย  {exe}  (รวม {size / 1024 / 1024:.1f} MB)")

    step(4, "ห่อเป็นตัวติดตั้ง")
    iscc = find_iscc()
    if not iscc:
        print("ไม่พบ Inno Setup ข้ามขั้นตอนนี้")
        print("ติดตั้งด้วย:  winget install --id JRSoftware.InnoSetup")
        print(f"ยังใช้แบบพกพาได้จาก {DIST / 'ThaiPDFSuite'}")
        return 0

    if run([str(iscc), str(ROOT / "installer" / "ThaiPDFSuite.iss")]) != 0:
        print("สร้างตัวติดตั้งไม่สำเร็จ")
        return 1

    setup = DIST / "installer" / "ThaiPDFSuite-Setup-1.0.exe"
    if setup.is_file():
        print(f"เรียบร้อย  {setup}  ({setup.stat().st_size / 1024 / 1024:.1f} MB)")

    print(f"\nใช้เวลาทั้งหมด {time.time() - started:.0f} วินาที")
    return 0


if __name__ == "__main__":
    sys.exit(main())
