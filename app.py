# -*- coding: utf-8 -*-
"""
Thai PDF Suite - แอปรวมรูปเป็น PDF และแปลง PDF ภาษาไทยเป็น Word / Excel

รันด้วย:  python app.py
ทุกอย่างทำงานในเครื่อง ไม่มีการส่งไฟล์ออกไปที่ใด
"""
from __future__ import annotations

import io
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from urllib.parse import quote
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

import fitz
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from core import glyphmap as glyph_mod
from core import ocr as ocr_mod
from core import thaitext as T
from core import verify as verify_mod
from core.build_docx import build_docx
from core.build_xlsx import build_xlsx
from core.extract import Document, extract_document
from core.images_to_pdf import PAGE_SIZES_MM, images_to_pdf
from core.paths import is_frozen, resource_dir

ROOT = resource_dir()
WEB = ROOT / "web"
WORK = Path(tempfile.gettempdir()) / "thai-pdf-suite"
WORK.mkdir(parents=True, exist_ok=True)

APP_NAME = "Thai PDF Suite"
APP_VERSION = "1.0"
JOB_TTL_SECONDS = 6 * 3600

app = FastAPI(title=APP_NAME, docs_url=None, redoc_url=None)


# ------------------------------------------------------------------ คลังงาน
class Job:
    def __init__(self, job_id: str):
        self.id = job_id
        self.dir = WORK / job_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.created = time.time()
        self.document: Optional[Document] = None
        self.pdf_path: Optional[str] = None
        self.source_name: str = ""
        self.ocr_suspects: List[dict] = []
        self.ocr_engine: str = ""


JOBS: Dict[str, Job] = {}


def new_job() -> Job:
    _sweep()
    job = Job(uuid.uuid4().hex[:12])
    JOBS[job.id] = job
    return job


def get_job(job_id: str) -> Job:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "ไม่พบงานนี้แล้ว อาจหมดอายุ กรุณาอัปโหลดไฟล์ใหม่")
    return job


def _sweep():
    """ลบงานที่เก่ากว่ากำหนด เพื่อไม่ให้ไฟล์ชั่วคราวค้างในเครื่อง"""
    now = time.time()
    for jid in [j for j, job in JOBS.items() if now - job.created > JOB_TTL_SECONDS]:
        job = JOBS.pop(jid, None)
        if job:
            shutil.rmtree(job.dir, ignore_errors=True)


def safe_name(name: str) -> str:
    base = os.path.basename(name or "file")
    keep = "".join(c for c in base if c not in '<>:"/\\|?*').strip()
    return keep or "file"


# ------------------------------------------------------------------ ฟอนต์ไทย
THAI_FONTS = [
    ("TH Sarabun New", ["THSarabunNew.ttf", "THSarabun.ttf"],
     "ฟอนต์มาตรฐานราชการไทย แนะนำที่สุดสำหรับเอกสารทางการ"),
    ("Sarabun", ["Sarabun-Regular.ttf"], "รุ่นใหม่ของสารบรรณ รองรับน้ำหนักหลายระดับ"),
    ("Angsana New", ["angsana.ttc", "angsa.ttf"], "ฟอนต์ติดมากับ Windows ทุกเครื่อง"),
    ("Cordia New", ["cordia.ttc", "cordia.ttf"], "ฟอนต์ไม่มีหัว ติดมากับ Windows"),
    ("Browallia New", ["browa.ttc", "browa.ttf"], "ฟอนต์ไม่มีหัว ติดมากับ Windows"),
    ("Leelawadee UI", ["leelawui.ttf", "LeelaUIb.ttf"], "ฟอนต์หน้าจอของ Windows รุ่นใหม่"),
    ("Noto Sans Thai", ["NotoSansThai-Regular.ttf"], "ฟอนต์โอเพนซอร์สจาก Google"),
    ("Tahoma", ["tahoma.ttf"], "มีทุกเครื่อง อ่านง่าย แต่หน้าตาไม่เป็นทางการ"),
]

FONT_DIRS = [
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
    Path(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts")),
]


def installed_fonts() -> List[dict]:
    present = set()
    for d in FONT_DIRS:
        if d.is_dir():
            try:
                present.update(f.name.lower() for f in d.iterdir())
            except OSError:
                pass
    out = []
    for name, files, note in THAI_FONTS:
        found = any(f.lower() in present for f in files)
        out.append({"name": name, "installed": found, "note": note})
    return out


# ------------------------------------------------------------------ เส้นทาง
@app.get("/", response_class=HTMLResponse)
def index():
    # ไม่ให้เบราว์เซอร์เก็บหน้าเว็บไว้ มิฉะนั้นผู้ใช้ที่อัปเดตโปรแกรมแล้ว
    # จะยังเห็นหน้าจอรุ่นเก่าค้างอยู่จนกว่าจะล้างแคชเอง
    return HTMLResponse(
        (WEB / "index.html").read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store, must-revalidate"})


@app.get("/api/status")
def status():
    st = ocr_mod.check_ocr()
    fonts = installed_fonts()
    recommended = next((f["name"] for f in fonts if f["installed"]), "Tahoma")
    return {
        "app": APP_NAME, "version": APP_VERSION,
        "ocr": st.to_dict(),
        "glyph_recovery": glyph_mod.HAVE_FONTTOOLS,
        "fonts": fonts,
        "recommended_font": recommended,
        "page_sizes": ["fit"] + list(PAGE_SIZES_MM.keys()),
    }


# ---------------------------------------------------------- รวมรูปเป็น PDF
@app.post("/api/images-to-pdf")
async def api_images_to_pdf(
    files: List[UploadFile] = File(...),
    page_size: str = Form("fit"),
    orientation: str = Form("auto"),
    margin_mm: float = Form(0.0),
    quality_mode: str = Form("balanced"),
    jpeg_quality: int = Form(92),
    max_pixels: int = Form(2000),
    fill_page: bool = Form(False),
    out_name: str = Form("รวมรูป.pdf"),
):
    if not files:
        raise HTTPException(400, "ยังไม่ได้เลือกรูป")

    job = new_job()
    payload = []
    for up in files:
        data = await up.read()
        if data:
            payload.append((up.filename or "image", data))
    if not payload:
        raise HTTPException(400, "ไฟล์ที่เลือกว่างเปล่า")

    name = safe_name(out_name)
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    out_path = job.dir / name

    try:
        result = images_to_pdf(
            payload, str(out_path), page_size=page_size, orientation=orientation,
            margin_mm=margin_mm, quality_mode=quality_mode,
            jpeg_quality=jpeg_quality, max_pixels=max_pixels or None,
            fill_page=fill_page)
    except Exception as exc:
        raise HTTPException(400, f"รวมรูปไม่สำเร็จ: {exc}")

    return {
        "job_id": job.id, "filename": name, "pages": result.pages,
        "size_bytes": result.size_bytes,
        "size_text": human_size(result.size_bytes),
        "skipped": result.skipped, "notes": result.notes,
        "download": f"/api/file/{job.id}/{quote(name)}",
    }


def human_size(n: int) -> str:
    for unit in ("ไบต์", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "ไบต์" else f"{n:.1f} {unit}"
        n /= 1024.0
    return str(n)


# ---------------------------------------------------------- วิเคราะห์ PDF
@app.post("/api/analyze")
async def api_analyze(
    file: UploadFile = File(...),
    password: str = Form(""),
    detect_tables: bool = Form(True),
    fix_visual_order: bool = Form(False),
):
    data = await file.read()
    if not data:
        raise HTTPException(400, "ไฟล์ว่างเปล่า")

    job = new_job()
    job.source_name = safe_name(file.filename or "document.pdf")
    pdf_path = job.dir / job.source_name
    pdf_path.write_bytes(data)
    job.pdf_path = str(pdf_path)

    try:
        document = extract_document(str(pdf_path), detect_tables=detect_tables,
                                    password=password)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(400, f"เปิดไฟล์ไม่สำเร็จ: {exc}")

    if fix_visual_order and document.visual_order_suspect:
        swaps = 0
        for page in document.pages:
            for para in page.paragraphs:
                for run in para.runs:
                    run.text, n = T.fix_visual_order(run.text)
                    swaps += n
            for table in page.tables:
                table.rows = [[T.fix_visual_order(c)[0] for c in row] for row in table.rows]
        if swaps:
            document.issues.append(T.Issue(
                "visual_order", f"สลับสระหน้ากลับเป็นลำดับตรรกะ {swaps} จุด", 0, "", "warn"))

    job.document = document
    return build_analysis(job)


def build_analysis(job: Job) -> dict:
    document = job.document
    quality = verify_mod.document_quality(document)
    preview = []
    for page in document.pages[:3]:
        items = [{"type": "para", "text": p.text, "align": p.align,
                  "size": round(p.size, 1), "bold": p.bold}
                 for p in page.paragraphs[:12]]
        items += [{"type": "table", "rows": t.rows[:8]} for t in page.tables[:3]]
        preview.append({"page": page.number, "source": page.source,
                        "confidence": page.ocr_confidence, "items": items})

    return {
        "job_id": job.id,
        "filename": job.source_name,
        "page_count": len(document.pages),
        "quality": quality,
        "preview": preview,
        "ocr_suspects": job.ocr_suspects[:80],
        "ocr_engine": job.ocr_engine,
        "ocr_status": ocr_mod.check_ocr().to_dict(),
    }


@app.post("/api/ocr")
async def api_ocr(
    job_id: str = Form(...),
    pages: str = Form(""),
    lang: str = Form("tha+eng"),
    dpi: int = Form(300),
    psm: int = Form(3),
    password: str = Form(""),
):
    job = get_job(job_id)
    if not job.document or not job.pdf_path:
        raise HTTPException(400, "ยังไม่มีเอกสารในงานนี้")

    if pages.strip():
        wanted = parse_pages(pages, len(job.document.pages))
    else:
        wanted = job.document.needs_ocr_pages or \
            list(range(1, len(job.document.pages) + 1))
    if not wanted:
        raise HTTPException(400, "ไม่มีหน้าที่ต้องอ่านด้วย OCR")

    try:
        result = ocr_mod.ocr_document(job.pdf_path, wanted, lang=lang, dpi=dpi,
                                      psm=psm, password=password)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(400, f"OCR ไม่สำเร็จ: {exc}")

    by_number = {p.number: p for p in result["pages"]}
    for i, page in enumerate(job.document.pages):
        if page.number in by_number:
            job.document.pages[i] = by_number[page.number]
    job.document.issues.extend(result["issues"])
    job.ocr_suspects = result["suspects"]
    job.ocr_engine = result["engine"]

    out = build_analysis(job)
    out["ocr_pages_done"] = wanted
    return out


def parse_pages(spec: str, total: int) -> List[int]:
    """รับรูปแบบ  1,3,5-8  แล้วคืนรายการเลขหน้า"""
    result: List[int] = []
    for chunk in spec.replace(" ", "").split(","):
        if not chunk:
            continue
        if "-" in chunk:
            a, _, b = chunk.partition("-")
            try:
                result.extend(range(int(a), int(b) + 1))
            except ValueError:
                continue
        else:
            try:
                result.append(int(chunk))
            except ValueError:
                continue
    return sorted({p for p in result if 1 <= p <= total})


# ---------------------------------------------------------- แปลงเป็นไฟล์
@app.post("/api/convert")
async def api_convert(
    job_id: str = Form(...),
    target: str = Form("docx"),
    font_name: str = Form("TH Sarabun New"),
    font_scale: float = Form(1.0),
    base_size: float = Form(12.0),
    keep_page_size: bool = Form(True),
    page_break: bool = Form(True),
    numbers_as_values: bool = Form(True),
    sheet_per_table: bool = Form(True),
    include_text_sheet: bool = Form(True),
    out_name: str = Form(""),
):
    job = get_job(job_id)
    if not job.document:
        raise HTTPException(400, "ยังไม่มีเอกสารในงานนี้")

    stem = Path(out_name or job.source_name or "document").stem or "document"
    stem = safe_name(stem)

    if target == "docx":
        name = f"{stem}.docx"
        path = job.dir / name
        build_docx(job.document, str(path), font_name=font_name,
                   font_scale=font_scale, keep_page_size=keep_page_size,
                   page_break_between_pages=page_break, base_size=base_size)
        report = verify_mod.verify_docx(job.document, str(path))
    elif target == "xlsx":
        name = f"{stem}.xlsx"
        path = job.dir / name
        build_xlsx(job.document, str(path), font_name=font_name,
                   font_size=base_size + 2, numbers_as_values=numbers_as_values,
                   separate_sheet_per_table=sheet_per_table,
                   include_text_sheet=include_text_sheet)
        report = verify_mod.verify_xlsx(job.document, str(path),
                                        numbers_as_values=numbers_as_values)
    else:
        raise HTTPException(400, "รูปแบบปลายทางต้องเป็น docx หรือ xlsx")

    ocr_pages = [p.number for p in job.document.pages if p.source == "ocr"]
    return {
        "filename": name,
        "download": f"/api/file/{job.id}/{quote(name)}",
        "size_text": human_size(os.path.getsize(path)),
        "verify": report.to_dict(),
        "ocr_pages": ocr_pages,
        "guaranteed": report.exact and not ocr_pages,
    }


@app.get("/api/file/{job_id}/{filename}")
def api_file(job_id: str, filename: str):
    job = get_job(job_id)
    path = job.dir / safe_name(filename)
    if not path.is_file():
        raise HTTPException(404, "ไม่พบไฟล์")
    return FileResponse(str(path), filename=path.name,
                        media_type="application/octet-stream")


@app.get("/api/page-image/{job_id}/{page}")
def api_page_image(job_id: str, page: int, width: int = 900):
    """ภาพหน้ากระดาษต้นฉบับ ไว้เทียบกับข้อความที่อ่านได้"""
    job = get_job(job_id)
    if not job.pdf_path:
        raise HTTPException(404, "ไม่มีไฟล์ต้นฉบับ")
    doc = fitz.open(job.pdf_path)
    if page < 1 or page > len(doc):
        doc.close()
        raise HTTPException(404, "ไม่มีหน้านี้")
    p = doc[page - 1]
    zoom = max(0.2, min(width / max(p.rect.width, 1), 3.0))
    pix = p.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    png = pix.tobytes("png")
    doc.close()
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "max-age=600"})


@app.get("/api/text/{job_id}")
def api_text(job_id: str):
    """ข้อความล้วนทั้งเอกสาร เผื่อผู้ใช้อยากคัดลอกไปใช้ต่อ"""
    job = get_job(job_id)
    if not job.document:
        raise HTTPException(400, "ยังไม่มีเอกสารในงานนี้")
    return Response(content=job.document.text,
                    media_type="text/plain; charset=utf-8")


@app.post("/api/check-text")
async def api_check_text(text: str = Form(...)):
    """เครื่องมือช่วยตรวจข้อความไทยทีละชิ้น ใช้ตรวจงานที่แปลงจากที่อื่นมาก็ได้"""
    fixed, issues = T.normalize(text)
    remaining = T.audit(fixed)
    suspect, ratio = T.detect_visual_order(text)
    return {
        "original": text,
        "fixed": fixed,
        "changed": fixed != text,
        "original_cp": verify_mod.codepoints(text, 200),
        "fixed_cp": verify_mod.codepoints(fixed, 200),
        "fixed_list": T.summarize(issues),
        "remaining": T.summarize(remaining),
        "clean": not remaining,
        "visual_order_suspect": suspect,
        "visual_order_ratio": round(ratio, 3),
    }


class FreshStaticFiles(StaticFiles):
    """
    บังคับให้เบราว์เซอร์ถามเซิร์ฟเวอร์ทุกครั้งว่าไฟล์เปลี่ยนหรือยัง

    ไฟล์ทั้งหมดอยู่ในเครื่องเดียวกัน การถามซ้ำจึงแทบไม่มีต้นทุน
    แต่ถ้าปล่อยให้แคชไว้ ผู้ใช้ที่อัปเดตโปรแกรมจะยังเห็นหน้าจอรุ่นเก่าค้างอยู่
    """

    def is_not_modified(self, response_headers, request_headers) -> bool:
        return False

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


app.mount("/web", FreshStaticFiles(directory=str(WEB)), name="web")


# ------------------------------------------------------------------ เริ่มทำงาน
def free_port(preferred: int = 8756) -> int:
    for port in range(preferred, preferred + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return 0


def main():
    port = 0
    if "--port" in sys.argv:
        try:
            port = int(sys.argv[sys.argv.index("--port") + 1])
        except (IndexError, ValueError):
            port = 0
    port = port or int(os.environ.get("PORT") or 0) or free_port()
    url = f"http://127.0.0.1:{port}"
    print("=" * 58)
    print(f"  {APP_NAME} {APP_VERSION}")
    print(f"  เปิดใช้งานที่ {url}")
    print("  ปิดโปรแกรมด้วย Ctrl+C")
    print("=" * 58)

    st = ocr_mod.check_ocr()
    if st.available:
        print(f"  OCR พร้อมใช้งาน: {st.version}")
    else:
        print("  OCR ยังไม่พร้อม (ใช้ได้เฉพาะ PDF ที่มีชั้นข้อความ)")

    if not glyph_mod.HAVE_FONTTOOLS:
        print("  คำเตือน: ไม่พบไลบรารี fonttools")
        print("  ไฟล์ที่ตาราง ToUnicode เสียหาย เช่น PDF ที่ส่งออกจาก Excel")
        print("  จะอ่านวรรณยุกต์หาย ติดตั้งด้วย: python -m pip install fonttools")

    if "--no-browser" not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
