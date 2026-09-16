# -*- coding: utf-8 -*-
"""
paths.py - หาที่อยู่ของไฟล์ประกอบ ทั้งตอนรันจากซอร์สและตอนถูกแพ็กเป็นโปรแกรมติดตั้ง

ตอนรันจากซอร์ส ไฟล์ประกอบอยู่ข้าง ๆ โฟลเดอร์ core
ตอนถูกแพ็กด้วย PyInstaller ไฟล์ถูกย้ายไปอยู่ในโฟลเดอร์ _internal ข้างตัวโปรแกรม
ถ้าเขียนโค้ดอ้าง __file__ ตรง ๆ จะหาไม่เจอหลังติดตั้ง
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List


def is_frozen() -> bool:
    """กำลังทำงานจากโปรแกรมที่แพ็กแล้วหรือไม่"""
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """โฟลเดอร์ที่เก็บไฟล์ประกอบซึ่งมากับตัวโปรแกรม เช่น web และ tessdata"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", None) or Path(sys.executable).parent)
    return Path(__file__).resolve().parent.parent


def app_dir() -> Path:
    """โฟลเดอร์ที่ตัวโปรแกรมอยู่ ใช้หาไฟล์ที่ผู้ใช้วางเพิ่มเองภายหลัง"""
    if is_frozen():
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def data_dirs(name: str) -> List[Path]:
    """
    ที่ที่ควรไปหาโฟลเดอร์ข้อมูลชื่อหนึ่ง เรียงตามลำดับความสำคัญ

    ข้างตัวโปรแกรมมาก่อน เพื่อให้ผู้ใช้วางไฟล์เพิ่มเองแล้วมีผลทันที
    โดยไม่ต้องติดตั้งโปรแกรมใหม่
    """
    seen, out = set(), []
    for base in (app_dir(), resource_dir()):
        candidate = base / name
        key = str(candidate).lower()
        if key not in seen:
            seen.add(key)
            out.append(candidate)
    env = os.environ.get(f"THAI_PDF_SUITE_{name.upper()}")
    if env:
        out.insert(0, Path(env))
    return out


def find_data_dir(name: str, must_contain: str = "") -> Path | None:
    """โฟลเดอร์ข้อมูลตัวแรกที่มีอยู่จริง และมีไฟล์ที่ระบุอยู่ข้างใน"""
    for path in data_dirs(name):
        if not path.is_dir():
            continue
        if must_contain and not (path / must_contain).is_file():
            continue
        return path
    return None
