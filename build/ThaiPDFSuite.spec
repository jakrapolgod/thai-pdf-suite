# -*- mode: python ; coding: utf-8 -*-
"""
สคริปต์แพ็กโปรแกรมเป็นไฟล์ .exe ด้วย PyInstaller

ใช้โหมดโฟลเดอร์ (ไม่ใช่ไฟล์เดียว) เพราะเปิดเร็วกว่ามาก
โหมดไฟล์เดียวต้องแตกไฟล์ลงโฟลเดอร์ชั่วคราวทุกครั้งที่เปิด ซึ่งกับ PyMuPDF ใช้เวลาหลายวินาที
และตัวติดตั้งก็ห่อทั้งโฟลเดอร์ให้อยู่แล้ว ผู้ใช้จึงเห็นแค่ทางลัดอันเดียวเหมือนกัน
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent

# uvicorn กับ fontTools โหลดโมดูลย่อยแบบไดนามิก ตัวตรวจการอ้างอิงจึงมองไม่เห็น
# ถ้าไม่ระบุไว้ โปรแกรมจะแพ็กผ่านแต่พังตอนเปิดใช้งานจริง
hidden = (collect_submodules("uvicorn")
          + collect_submodules("fontTools")
          + ["multipart", "python_multipart", "anyio", "email.mime.multipart"])

datas = [
    (str(ROOT / "web"), "web"),
]

# ไฟล์ภาษาไทยของ OCR ใส่มาด้วยถ้ามี ตัวติดตั้งเปิดให้เลือกได้ว่าจะเอาหรือไม่
tessdata = ROOT / "tessdata"
if tessdata.is_dir():
    datas.append((str(tessdata), "tessdata"))

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "matplotlib", "scipy", "pandas", "numpy",
        "PyQt5", "PyQt6", "PySide2", "PySide6",
        "IPython", "notebook", "pytest", "setuptools._distutils",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ThaiPDFSuite",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # แสดงหน้าต่างสถานะของตัวเองแทนหน้าต่างดำของ command prompt
    disable_windowed_traceback=False,
    icon=str(ROOT / "web" / "app.ico"),
    version=str(ROOT / "build" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ThaiPDFSuite",
)
