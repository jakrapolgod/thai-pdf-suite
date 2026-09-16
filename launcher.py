# -*- coding: utf-8 -*-
"""
launcher.py - ตัวเปิดโปรแกรมสำหรับรุ่นที่ติดตั้งแล้ว

เปิดเซิร์ฟเวอร์ในเครื่องแล้วแสดงหน้าต่างเล็ก ๆ บอกสถานะ แทนหน้าต่างดำของ command prompt
ผู้ใช้ปิดโปรแกรมจากหน้าต่างนี้ได้ และถ้าเปิดเซิร์ฟเวอร์ไม่สำเร็จก็เห็นสาเหตุทันที

รันด้วยหน้าต่าง:   python launcher.py
รันแบบ command:    python launcher.py --console
"""
from __future__ import annotations

import os
import sys
import threading
import traceback
import webbrowser

APP_TITLE = "Thai PDF Suite"
ACCENT = "#b4543a"
BG = "#f6f4f0"
CARD = "#ffffff"
TEXT = "#24211d"
MUTED = "#7b736a"
GREEN = "#3f7a4e"
AMBER = "#9a6b18"


def _thai_font(size: int, bold: bool = False):
    """
    ฟอนต์ที่วาดวรรณยุกต์ไทยได้ถูกต้องบน Windows ทุกเครื่อง

    ใช้ฟอนต์หน้าจอ ไม่ใช่ฟอนต์เอกสาร เพราะฟอนต์เอกสารตัวอักษรเตี้ยกว่ามาก
    เมื่อวัดที่ขนาดเท่ากัน ทำให้อ่านบนจอยากกว่าที่ควร
    """
    return ("Leelawadee UI", size, "bold" if bold else "normal")


def log_path() -> str:
    """ที่เก็บบันทึกการทำงาน ไว้ให้ดูย้อนหลังเวลาเปิดโปรแกรมไม่ขึ้น"""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "Thai PDF Suite")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "log.txt")


def ensure_streams() -> None:
    """
    โปรแกรมที่แพ็กแบบไม่มีหน้าต่าง command prompt จะไม่มี stdout และ stderr
    ไลบรารีที่ตั้งค่าระบบบันทึกโดยเขียนลง stdout จะพังทันทีตั้งแต่เริ่มทำงาน
    จึงต้องต่อปลายทางให้เป็นไฟล์ก่อน แล้วยังได้บันทึกไว้ตรวจปัญหาเป็นของแถม
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        stream = open(log_path(), "a", encoding="utf-8", buffering=1)
    except OSError:
        stream = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def run_console() -> int:
    ensure_streams()
    import app
    app.main()
    return 0


def run_window() -> int:
    ensure_streams()

    import tkinter as tk
    from tkinter import scrolledtext

    import uvicorn

    import app as appmod
    from core import glyphmap as glyph_mod
    from core import ocr as ocr_mod

    port = appmod.free_port()
    if not port:
        port = 0
    url = f"http://127.0.0.1:{port}"

    root = tk.Tk()
    root.title(APP_TITLE)
    root.configure(bg=BG)
    root.resizable(False, False)
    try:
        icon = os.path.join(appmod.ROOT, "web", "app.ico")
        if os.path.isfile(icon):
            root.iconbitmap(icon)
    except Exception:
        pass

    wrap = tk.Frame(root, bg=BG, padx=28, pady=24)
    wrap.pack(fill="both", expand=True)

    head = tk.Frame(wrap, bg=BG)
    head.pack(fill="x")
    mark = tk.Label(head, text="ไทย", bg=ACCENT, fg="white",
                    font=_thai_font(17, True), width=4, height=2)
    mark.pack(side="left", padx=(0, 16))
    titles = tk.Frame(head, bg=BG)
    titles.pack(side="left", anchor="w")
    tk.Label(titles, text=APP_TITLE, bg=BG, fg=TEXT,
             font=_thai_font(18, True)).pack(anchor="w")
    tk.Label(titles, text="แปลง PDF ภาษาไทยเป็น Word / Excel และรวมรูปเป็น PDF",
             bg=BG, fg=MUTED, font=_thai_font(11)).pack(anchor="w")

    status_var = tk.StringVar(value="กำลังเปิดโปรแกรม…")
    card = tk.Frame(wrap, bg=CARD, padx=18, pady=16,
                    highlightbackground="#e3ded6", highlightthickness=1)
    card.pack(fill="x", pady=(20, 14))
    tk.Label(card, textvariable=status_var, bg=CARD, fg=TEXT,
             font=_thai_font(13), justify="left", anchor="w").pack(fill="x")

    detail = scrolledtext.ScrolledText(wrap, height=7, width=52, bg=CARD, fg=MUTED,
                                       font=_thai_font(12), relief="flat", wrap="word",
                                       highlightbackground="#e3ded6", highlightthickness=1)
    detail.pack(fill="x")
    detail.configure(state="disabled")

    def log(line: str):
        detail.configure(state="normal")
        detail.insert("end", line + "\n")
        detail.see("end")
        detail.configure(state="disabled")

    buttons = tk.Frame(wrap, bg=BG)
    buttons.pack(fill="x", pady=(18, 0))

    open_btn = tk.Button(buttons, text="เปิดหน้าโปรแกรม", bg=ACCENT, fg="white",
                         font=_thai_font(14, True), relief="flat", cursor="hand2",
                         activebackground="#9c4832", activeforeground="white",
                         padx=26, pady=13, state="disabled",
                         command=lambda: webbrowser.open(url))
    open_btn.pack(side="left")

    server_holder = {}

    def quit_app():
        server = server_holder.get("server")
        if server is not None:
            server.should_exit = True
        root.after(250, root.destroy)

    tk.Button(buttons, text="ปิดโปรแกรม", bg=BG, fg=MUTED, font=_thai_font(13),
              relief="flat", cursor="hand2", padx=20, pady=13,
              command=quit_app).pack(side="right")

    root.protocol("WM_DELETE_WINDOW", quit_app)

    def serve():
        try:
            # log_config=None สำคัญ เพราะค่าเริ่มต้นของไลบรารีจะตั้งระบบบันทึกใหม่
            # โดยเขียนลง stdout ซึ่งโปรแกรมแบบไม่มีหน้าต่าง command prompt ไม่มี
            config = uvicorn.Config(appmod.app, host="127.0.0.1", port=port,
                                    log_level="warning", log_config=None)
            server = uvicorn.Server(config)
            server_holder["server"] = server
            server.run()
        except Exception:
            server_holder["error"] = traceback.format_exc()

    def watch():
        """รอจนเซิร์ฟเวอร์เริ่มทำงานจริง ไม่ใช่แค่สั่งให้เริ่ม"""
        server = server_holder.get("server")
        if server is not None and getattr(server, "started", False):
            on_started()
            return
        if server_holder.get("error"):
            on_failed(server_holder["error"])
            return
        if not worker.is_alive():
            on_failed(server_holder.get("error")
                      or "เซิร์ฟเวอร์หยุดทำงานโดยไม่ทราบสาเหตุ")
            return
        root.after(200, watch)

    def on_started():
        status_var.set(f"กำลังทำงานอยู่ที่  {url}\nปิดหน้าต่างนี้เมื่อใช้งานเสร็จ")
        open_btn.configure(state="normal")

        if glyph_mod.HAVE_FONTTOOLS:
            log("พร้อม: ตัวกู้ตัวอักษรจากฟอนต์ที่ฝังใน PDF")
        else:
            log("ไม่พร้อม: ไม่พบไลบรารี fonttools")
            log("  ไฟล์ที่ส่งออกจาก Excel อาจอ่านวรรณยุกต์หาย")

        try:
            st = ocr_mod.check_ocr()
        except Exception as exc:
            log(f"ตรวจ OCR ไม่สำเร็จ: {exc}")
            st = None

        if st and st.available:
            log(f"พร้อม: OCR ภาษาไทย ({st.version})")
        else:
            log("ยังไม่มี OCR สำหรับไฟล์สแกน")
            log("  ไฟล์ PDF ที่มีชั้นข้อความยังแปลงได้ตามปกติ")
            log("  ติดตั้งเพิ่มด้วย: winget install --id UB-Mannheim.TesseractOCR")

        root.after(600, lambda: webbrowser.open(url))

    def on_failed(message: str):
        status_var.set("เปิดโปรแกรมไม่สำเร็จ")
        card.configure(highlightbackground=ACCENT)
        for line in message.strip().splitlines()[-8:]:
            log(line)
        log("")
        log(f"บันทึกการทำงานอยู่ที่ {log_path()}")

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    root.after(200, watch)

    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 3
    root.geometry(f"+{x}+{y}")

    root.mainloop()
    return 0


def main() -> int:
    if "--console" in sys.argv:
        return run_console()
    try:
        return run_window()
    except Exception:
        # ถ้าเปิดหน้าต่างไม่ได้ ยังต้องใช้งานแบบ command ได้อยู่
        traceback.print_exc()
        return run_console()


if __name__ == "__main__":
    sys.exit(main())
