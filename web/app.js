/* Thai PDF Suite - ส่วนติดต่อผู้ใช้ */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

let STATUS = null;
let JOB = null;          // งานแปลง PDF ปัจจุบัน
let ANALYSIS = null;
let CUR_PAGE = 1;

/* ------------------------------------------------------------ ตัวช่วย */
function toast(msg, bad = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast" + (bad ? " bad" : "");
  el.hidden = false;
  clearTimeout(el._t);
  el._t = setTimeout(() => (el.hidden = true), bad ? 6000 : 3200);
}

function busy(on, text) {
  $("#overlay").hidden = !on;
  if (text) $("#overlay-text").textContent = text;
}

async function post(url, formData) {
  const res = await fetch(url, { method: "POST", body: formData });
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch { data = { detail: text }; }
  if (!res.ok) throw new Error(data.detail || "ทำงานไม่สำเร็จ");
  return data;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* ------------------------------------------------------------ ขนาดตัวอักษร */
// ขนาดทั้งหน้าจออ้างอิงขนาดรากค่าเดียว การปรับจึงขยับทุกจุดพร้อมกันโดยสัดส่วนไม่เพี้ยน
const FONT_STEPS = [15, 16, 17, 19, 21, 23];
const FONT_DEFAULT = 2; // 17px
let fontStep = FONT_DEFAULT;

function applyFontStep(save = true) {
  fontStep = Math.max(0, Math.min(fontStep, FONT_STEPS.length - 1));
  document.documentElement.style.fontSize = FONT_STEPS[fontStep] + "px";
  $("#fs-down").disabled = fontStep === 0;
  $("#fs-up").disabled = fontStep === FONT_STEPS.length - 1;
  if (save) {
    try { localStorage.setItem("thaipdf.fontStep", String(fontStep)); } catch { /* ไม่มีผลกับการใช้งาน */ }
  }
}

(function initFontSize() {
  try {
    const saved = parseInt(localStorage.getItem("thaipdf.fontStep"), 10);
    if (!Number.isNaN(saved)) fontStep = saved;
  } catch { /* เปิดแบบไม่จำค่าก็ยังใช้งานได้ */ }
  applyFontStep(false);
})();

$("#fs-down").onclick = () => { fontStep -= 1; applyFontStep(); };
$("#fs-up").onclick = () => { fontStep += 1; applyFontStep(); };

/* ------------------------------------------------------------ แท็บ */
$$(".tab").forEach((btn) => {
  btn.onclick = () => {
    $$(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    $$(".panel").forEach((p) =>
      p.classList.toggle("active", p.id === "tab-" + btn.dataset.tab));
  };
});

/* ------------------------------------------------------------ สถานะแอป */
async function loadStatus() {
  try {
    STATUS = await (await fetch("/api/status")).json();
  } catch {
    toast("ติดต่อเซิร์ฟเวอร์ในเครื่องไม่ได้", true);
    return;
  }
  const b = $("#badge-ocr");
  if (STATUS.ocr.available) {
    b.textContent = "OCR พร้อมใช้งาน (" + STATUS.ocr.languages.length + " ภาษา)";
    b.className = "badge ok";
  } else {
    b.textContent = "ยังไม่มี OCR สำหรับไฟล์สแกน";
    b.className = "badge warn";
  }

  const sel = $("#c-font");
  sel.innerHTML = "";
  STATUS.fonts.forEach((f) => {
    const o = document.createElement("option");
    o.value = f.name;
    o.textContent = f.name + (f.installed ? "" : "  (ไม่พบในเครื่องนี้)");
    o.dataset.installed = f.installed ? "1" : "0";
    o.dataset.note = f.note;
    if (f.name === STATUS.recommended_font) o.selected = true;
    sel.appendChild(o);
  });
  updateFontNote();
}

function updateFontNote() {
  const opt = $("#c-font").selectedOptions[0];
  if (!opt) return;
  $("#c-font-note").textContent = opt.dataset.installed === "1"
    ? opt.dataset.note
    : "ไม่พบฟอนต์นี้ในเครื่อง Word จะเลือกฟอนต์อื่นแทน ซึ่งอาจทำให้หน้าตาเอกสารต่างไป";
}
$("#c-font").onchange = updateFontNote;

/* ============================================================ รวมรูปเป็น PDF */
let IMAGES = [];

function bindDrop(zone, input, handler) {
  zone.onclick = () => input.click();
  input.onchange = () => { handler(Array.from(input.files)); input.value = ""; };
  ["dragenter", "dragover"].forEach((e) =>
    zone.addEventListener(e, (ev) => { ev.preventDefault(); zone.classList.add("over"); }));
  ["dragleave", "drop"].forEach((e) =>
    zone.addEventListener(e, (ev) => { ev.preventDefault(); zone.classList.remove("over"); }));
  zone.addEventListener("drop", (ev) => {
    handler(Array.from(ev.dataTransfer.files));
  });
}

bindDrop($("#img-drop"), $("#img-input"), (files) => {
  const imgs = files.filter((f) => f.type.startsWith("image/") ||
    /\.(jpe?g|png|webp|tiff?|bmp|gif)$/i.test(f.name));
  if (!imgs.length) return toast("ไม่พบไฟล์รูปในสิ่งที่วางมา", true);
  imgs.forEach((f) => IMAGES.push({ file: f, url: URL.createObjectURL(f) }));
  renderThumbs();
});

function renderThumbs() {
  const list = $("#img-list");
  list.innerHTML = "";
  IMAGES.forEach((item, i) => {
    const div = document.createElement("div");
    div.className = "thumb";
    div.draggable = true;
    div.dataset.i = i;
    div.innerHTML =
      `<span class="num">${i + 1}</span>` +
      `<button class="rm" title="เอาออก">&times;</button>` +
      `<img src="${item.url}" alt="">` +
      `<div class="meta">${esc(item.file.name)}</div>`;
    div.querySelector(".rm").onclick = (e) => {
      e.stopPropagation();
      URL.revokeObjectURL(item.url);
      IMAGES.splice(i, 1);
      renderThumbs();
    };
    div.addEventListener("dragstart", (e) => {
      div.classList.add("dragging");
      e.dataTransfer.setData("text/plain", String(i));
    });
    div.addEventListener("dragend", () => div.classList.remove("dragging"));
    div.addEventListener("dragover", (e) => { e.preventDefault(); div.classList.add("drop-target"); });
    div.addEventListener("dragleave", () => div.classList.remove("drop-target"));
    div.addEventListener("drop", (e) => {
      e.preventDefault();
      div.classList.remove("drop-target");
      const from = parseInt(e.dataTransfer.getData("text/plain"), 10);
      const to = i;
      if (Number.isNaN(from) || from === to) return;
      const [moved] = IMAGES.splice(from, 1);
      IMAGES.splice(to, 0, moved);
      renderThumbs();
    });
    list.appendChild(div);
  });

  const has = IMAGES.length > 0;
  $("#img-toolbar").hidden = !has;
  $("#img-hint").hidden = !has;
  $("#img-build").disabled = !has;
  $("#img-count").textContent = IMAGES.length + " รูป";
}

$("#img-sort-name").onclick = () => {
  IMAGES.sort((a, b) => a.file.name.localeCompare(b.file.name, "th", { numeric: true }));
  renderThumbs();
};
$("#img-reverse").onclick = () => { IMAGES.reverse(); renderThumbs(); };
$("#img-clear").onclick = () => {
  IMAGES.forEach((i) => URL.revokeObjectURL(i.url));
  IMAGES = [];
  renderThumbs();
  $("#img-result").hidden = true;
};

$("#m-margin").oninput = (e) => ($("#m-margin-val").textContent = e.target.value + " มม.");
$("#m-jpeg-q").oninput = (e) => ($("#m-jq-val").textContent = e.target.value);
$("#m-max-px").oninput = (e) => ($("#m-px-val").textContent = e.target.value + " px");
$("#m-quality").onchange = (e) => {
  $$(".compact-only").forEach((el) => (el.hidden = e.target.value !== "compact"));
  $$(".q-only").forEach((el) => (el.hidden = e.target.value === "original"));
};

$("#img-build").onclick = async () => {
  if (!IMAGES.length) return;
  const fd = new FormData();
  IMAGES.forEach((i) => fd.append("files", i.file, i.file.name));
  fd.append("page_size", $("#m-page-size").value);
  fd.append("orientation", $("#m-orientation").value);
  fd.append("margin_mm", $("#m-margin").value);
  fd.append("quality_mode", $("#m-quality").value);
  fd.append("jpeg_quality", $("#m-jpeg-q").value);
  fd.append("max_pixels", $("#m-max-px").value);
  fd.append("fill_page", $("#m-fill").checked ? "true" : "false");
  fd.append("out_name", $("#m-name").value || "รวมรูป.pdf");

  busy(true, `กำลังรวม ${IMAGES.length} รูปเป็น PDF…`);
  try {
    const r = await post("/api/images-to-pdf", fd);
    const box = $("#img-result");
    box.className = "result";
    box.hidden = false;
    box.innerHTML =
      `<div class="line"><span>จำนวนหน้า</span><span>${r.pages} หน้า</span></div>` +
      `<div class="line"><span>ขนาดไฟล์</span><span>${esc(r.size_text)}</span></div>` +
      (r.skipped.length ? `<div class="line"><span>ข้ามไป</span><span>${r.skipped.length} ไฟล์</span></div>` : "") +
      (r.notes.length ? `<p style="margin:8px 0 0;font-size:12.5px">${r.notes.map(esc).join("<br>")}</p>` : "") +
      `<a class="dl" href="${r.download}" download>ดาวน์โหลด ${esc(r.filename)}</a>`;
    toast("สร้าง PDF เรียบร้อย");
  } catch (e) {
    toast(e.message, true);
  } finally {
    busy(false);
  }
};

/* ============================================================ PDF เป็น Word/Excel */
bindDrop($("#pdf-drop"), $("#pdf-input"), (files) => {
  const pdf = files.find((f) => /\.pdf$/i.test(f.name) || f.type === "application/pdf");
  if (!pdf) return toast("กรุณาเลือกไฟล์ PDF", true);
  analyze(pdf);
});

async function analyze(file) {
  const fd = new FormData();
  fd.append("file", file, file.name);
  fd.append("detect_tables", "true");
  busy(true, "กำลังอ่านไฟล์และตรวจอักขระไทย…");
  try {
    const data = await post("/api/analyze", fd);
    JOB = data.job_id;
    showAnalysis(data);
  } catch (e) {
    toast(e.message, true);
  } finally {
    busy(false);
  }
}

function showAnalysis(data) {
  ANALYSIS = data;
  CUR_PAGE = 1;
  $("#pdf-drop").hidden = true;
  $("#analysis").hidden = false;
  $("#convert-side").hidden = false;
  $("#a-name").textContent = data.filename;
  $("#a-pages").textContent = data.page_count + " หน้า";

  const q = data.quality;
  const scanned = q.needs_ocr_pages.length;
  const ocrPages = q.pages.filter((p) => p.source === "ocr").length;
  const fixedCount = q.fixed.reduce((s, r) => s + r.count, 0);

  const cards = [
    { k: "ตัวอักษรที่อ่านได้", v: q.total_chars.toLocaleString("th-TH"), cls: q.total_chars ? "good" : "bad" },
    { k: "สัดส่วนภาษาไทย", v: Math.round(q.thai_ratio * 100) + "%", cls: "" },
    { k: "จุดที่แอปแก้ให้", v: fixedCount.toLocaleString("th-TH"), cls: fixedCount ? "warn" : "good" },
    {
      k: "โครงสร้างอักขระไทย", v: q.clean ? "ถูกต้องทุกตัว" : "พบปัญหา",
      cls: q.clean ? "good" : "bad",
    },
    {
      k: "หน้าที่เป็นภาพสแกน",
      v: scanned ? scanned + " หน้า" : (ocrPages ? ocrPages + " หน้า (อ่านแล้ว)" : "ไม่มี"),
      cls: scanned ? "warn" : "good",
    },
  ];
  $("#a-cards").innerHTML = cards.map((c) =>
    `<div class="card ${c.cls}"><div class="k">${c.k}</div><div class="v">${c.v}</div></div>`).join("");

  renderIssues(q);
  renderOcrBox(data);
  renderPreview(data.preview);
  loadPageImage(1);
}

function renderIssues(q) {
  const box = $("#a-fixed");
  const rows = [...q.fixed, ...q.remaining.map((r) => ({ ...r, severity: "error" }))];
  if (!rows.length) {
    box.innerHTML = `<p class="empty">ไม่พบอักขระไทยที่ต้องแก้เลย ข้อความในไฟล์ต้นทางอยู่ในรูปแบบมาตรฐานอยู่แล้ว</p>`;
    return;
  }
  box.innerHTML = rows.map((r) => {
    const samples = (r.samples || []).filter((s) => s.before).slice(0, 2).map((s) =>
      `<code>${esc(s.before)}</code> → <code>${esc(s.after)}</code>`).join(" · ");
    return `<div class="issue ${r.severity}">
      <div class="top"><span>${esc(r.label)}</span><span class="count">${r.count} จุด</span></div>
      ${samples ? `<div class="samples">${samples}</div>` : ""}
    </div>`;
  }).join("");

  if (q.visual_order_suspect) {
    box.insertAdjacentHTML("beforeend",
      `<div class="issue error"><div class="top">
        <span>สงสัยว่าไฟล์นี้เก็บข้อความแบบเรียงตามสายตา สระหน้าอาจอยู่ผิดตำแหน่ง</span>
        <span class="count">${Math.round(q.visual_order_ratio * 100)}%</span>
      </div><div class="samples">ไฟล์แบบนี้ต้องตรวจผลลัพธ์ก่อนใช้งานเสมอ</div></div>`);
  }
}

function renderOcrBox(data) {
  const box = $("#a-ocr-box");
  const needs = data.quality.needs_ocr_pages;
  const st = data.ocr_status;
  const done = data.quality.pages.filter((p) => p.source === "ocr");

  if (!needs.length && !done.length) { box.innerHTML = ""; return; }

  if (!st.available) {
    box.innerHTML = `<div class="ocr-box">
      <h4>พบ ${needs.length} หน้าที่เป็นภาพสแกน ยังอ่านข้อความไม่ได้</h4>
      <p>${esc(st.hint)}</p></div>`;
    return;
  }

  const avg = done.length
    ? Math.round(done.reduce((s, p) => s + (p.confidence || 0), 0) / done.length)
    : null;

  box.innerHTML = `<div class="ocr-box ${needs.length ? "" : "ready"}">
    <h4>${needs.length ? `พบ ${needs.length} หน้าที่เป็นภาพสแกน` : `อ่านด้วย OCR แล้ว ${done.length} หน้า`}</h4>
    <p>${needs.length
      ? "หน้าที่เป็นภาพต้องใช้ OCR ซึ่งอ่านภาษาไทยผิดได้ โดยเฉพาะวรรณยุกต์ ต้องตรวจผลด้วยตาเสมอ"
      : `ค่าความมั่นใจที่เอนจินรายงานคือ ${avg}% แต่ค่านี้มักสูงกว่าความถูกต้องจริง โปรดอ่านทานผลลัพธ์ก่อนใช้งาน`}</p>
    <div class="ocr-row">
      <label>หน้าที่ต้องการอ่าน
        <input type="text" id="ocr-pages" value="${needs.join(",") || ""}" placeholder="เช่น 1,3,5-8 หรือเว้นว่างเพื่ออ่านทุกหน้า">
      </label>
      <label>ภาษาในเอกสาร
        <select id="ocr-lang">
          <option value="tha+eng" selected>ไทย + อังกฤษ</option>
          <option value="tha">ไทยล้วน (แม่นกว่าถ้าไม่มีอังกฤษปน)</option>
          <option value="eng">อังกฤษล้วน</option>
        </select>
      </label>
      <label>ความละเอียด
        <select id="ocr-dpi">
          <option value="200">200 dpi (เร็ว)</option>
          <option value="300" selected>300 dpi (แนะนำ)</option>
          <option value="400">400 dpi (ละเอียด ช้ากว่า)</option>
        </select>
      </label>
      <button class="primary" id="ocr-run" style="width:auto">อ่านด้วย OCR</button>
    </div>
    ${data.ocr_suspects.length ? `<div class="suspects">${data.ocr_suspects.slice(0, 60).map((s) =>
      `<span class="w">${esc(s.text)}<b>${s.confidence}%</b></span>`).join("")}</div>` : ""}
  </div>`;

  $("#ocr-run").onclick = runOcr;
}

async function runOcr() {
  const fd = new FormData();
  fd.append("job_id", JOB);
  fd.append("pages", $("#ocr-pages").value.trim());
  fd.append("dpi", $("#ocr-dpi").value);
  fd.append("lang", $("#ocr-lang").value);
  busy(true, "กำลังอ่านข้อความจากภาพ อาจใช้เวลาสักครู่…");
  try {
    const data = await post("/api/ocr", fd);
    showAnalysis(data);
    toast(`อ่านด้วย OCR เสร็จแล้ว ${data.ocr_pages_done.length} หน้า`);
  } catch (e) {
    toast(e.message, true);
  } finally {
    busy(false);
  }
}

function renderPreview(pages) {
  const box = $("#a-preview");
  if (!pages.length) { box.innerHTML = `<p class="empty">ไม่มีข้อความให้แสดง</p>`; return; }
  box.innerHTML = pages.map((p) => {
    const head = `<div class="pv-page">หน้า ${p.page}${p.source === "ocr"
      ? ` · อ่านด้วย OCR ความมั่นใจ ${p.confidence ?? "-"}%` : ""}</div>`;
    const body = p.items.map((it) => {
      if (it.type === "para") {
        const weight = it.bold ? "font-weight:650;" : "";
        // ขนาดในไฟล์ต้นทางเล็กเกินกว่าจะอ่านบนจอได้สบาย จึงกำหนดพื้นไว้
        // แล้วให้ขยับตามขนาดที่ผู้ใช้เลือกด้วยการใช้หน่วยเทียบขนาดราก
        const rem = Math.max(1.05, Math.min(it.size / 12, 1.55)).toFixed(2);
        return `<p class="pv-para ${it.align}" style="${weight}font-size:${rem}rem">${esc(it.text)}</p>`;
      }
      return `<table class="pv-table">${it.rows.map((r) =>
        `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</table>`;
    }).join("");
    return head + body;
  }).join("");
}

function loadPageImage(n) {
  if (!ANALYSIS) return;
  CUR_PAGE = Math.max(1, Math.min(n, ANALYSIS.page_count));
  $("#pg-label").textContent = `หน้า ${CUR_PAGE} จาก ${ANALYSIS.page_count}`;
  $("#pg-img").src = `/api/page-image/${JOB}/${CUR_PAGE}`;
  $("#pg-prev").disabled = CUR_PAGE <= 1;
  $("#pg-next").disabled = CUR_PAGE >= ANALYSIS.page_count;
}
$("#pg-prev").onclick = () => loadPageImage(CUR_PAGE - 1);
$("#pg-next").onclick = () => loadPageImage(CUR_PAGE + 1);

$("#a-reset").onclick = () => {
  JOB = null; ANALYSIS = null;
  $("#analysis").hidden = true;
  $("#convert-side").hidden = true;
  $("#pdf-drop").hidden = false;
  $("#c-result").hidden = true;
};

$("#c-size").oninput = (e) => ($("#c-size-val").textContent = e.target.value + " pt");
$("#c-scale").oninput = (e) => ($("#c-scale-val").textContent = e.target.value + "%");

async function convert(target) {
  if (!JOB) return;
  const fd = new FormData();
  fd.append("job_id", JOB);
  fd.append("target", target);
  fd.append("font_name", $("#c-font").value);
  fd.append("font_scale", (parseInt($("#c-scale").value, 10) / 100).toFixed(2));
  fd.append("base_size", $("#c-size").value);
  fd.append("keep_page_size", $("#c-keep-size").checked ? "true" : "false");
  fd.append("page_break", $("#c-page-break").checked ? "true" : "false");
  fd.append("numbers_as_values", $("#c-numbers").checked ? "true" : "false");
  fd.append("sheet_per_table", $("#c-sheet-per-table").checked ? "true" : "false");
  fd.append("include_text_sheet", $("#c-text-sheet").checked ? "true" : "false");

  busy(true, `กำลังสร้างไฟล์ ${target === "docx" ? "Word" : "Excel"} และตรวจสอบย้อนกลับ…`);
  try {
    const r = await post("/api/convert", fd);
    renderConvertResult(r);
    toast("แปลงเสร็จแล้ว");
  } catch (e) {
    toast(e.message, true);
  } finally {
    busy(false);
  }
}
$("#btn-docx").onclick = () => convert("docx");
$("#btn-xlsx").onclick = () => convert("xlsx");
$("#btn-txt").onclick = () => { if (JOB) window.open(`/api/text/${JOB}`, "_blank"); };

function renderConvertResult(r) {
  const v = r.verify;
  const box = $("#c-result");
  box.hidden = false;

  let cls = "result", verdict, note;
  if (r.guaranteed) {
    verdict = "ตรงกับต้นฉบับทุกตัวอักษร";
    note = "ตรวจย้อนกลับด้วยการเปิดไฟล์ผลลัพธ์อ่านใหม่แล้วเทียบทีละรหัสอักขระ";
  } else if (v.exact && r.ocr_pages.length) {
    cls = "result warn";
    verdict = "ตรงกับข้อความที่อ่านได้ทุกตัว";
    note = `แต่หน้า ${r.ocr_pages.join(", ")} มาจาก OCR ซึ่งอาจอ่านตัวอักษรผิดตั้งแต่ต้น ควรตรวจหน้าเหล่านี้ด้วยตา`;
  } else {
    cls = "result bad";
    verdict = "พบข้อความไม่ตรงกัน";
    note = "รายละเอียดอยู่ด้านล่าง";
  }

  box.className = cls;
  box.innerHTML =
    `<div style="font-weight:650;margin-bottom:8px">${verdict}</div>` +
    `<div class="line"><span>ข้อความที่ตรวจ</span><span>${v.items_matched} / ${v.items_total} ชิ้น</span></div>` +
    `<div class="line"><span>ความตรงกัน</span><span>${v.match_percent}%</span></div>` +
    `<div class="line"><span>จำนวนตัวอักษร</span><span>${v.chars_source.toLocaleString("th-TH")}</span></div>` +
    `<div class="line"><span>โครงสร้างอักขระไทย</span><span>${v.thai_problems.length ? "พบปัญหา" : "ถูกต้องทุกตัว"}</span></div>` +
    `<div class="line"><span>ขนาดไฟล์</span><span>${esc(r.size_text)}</span></div>` +
    `<p style="margin:9px 0 0;font-size:12.5px">${esc(note)}</p>` +
    (v.mismatches.length ? `<div style="margin-top:9px;font-size:12px">` + v.mismatches.slice(0, 4).map((m) =>
      `<div style="margin-bottom:6px"><b>${esc(m.note)}</b><br>คาด: <code>${esc(m.expected)}</code><br>ได้: <code>${esc(m.got) || "(ว่าง)"}</code></div>`).join("") + `</div>` : "") +
    (v.note ? `<p style="margin:6px 0 0;font-size:12.5px">${esc(v.note)}</p>` : "") +
    `<a class="dl" href="${r.download}" download>ดาวน์โหลด ${esc(r.filename)}</a>`;
}

/* ============================================================ ตรวจข้อความไทย */
$("#chk-sample").onclick = () => {
  $("#chk-input").value = [
    "นํ้าใจ",                       // นํ้าใจ แบบฟอนต์เก่า
    "เเละก็ท้ิ้ง", // เเละก็ทิ้ง
    "เ่กงมาก",                 // วรรณยุกต์เกาะสระหน้า
  ].join("  ");
};

$("#chk-run").onclick = async () => {
  const text = $("#chk-input").value;
  if (!text.trim()) return toast("ยังไม่ได้ใส่ข้อความ", true);
  const fd = new FormData();
  fd.append("text", text);
  busy(true, "กำลังตรวจ…");
  try {
    const r = await post("/api/check-text", fd);
    const box = $("#chk-result");
    box.hidden = false;
    const fixedRows = r.fixed_list.map((x) =>
      `<div class="issue fixed"><div class="top"><span>${esc(x.label)}</span><span class="count">${x.count} จุด</span></div></div>`).join("");
    const badRows = r.remaining.map((x) =>
      `<div class="issue error"><div class="top"><span>${esc(x.label)}</span><span class="count">${x.count} จุด</span></div></div>`).join("");

    box.innerHTML = `<div class="cmp">
      <div class="box"><h4>ก่อนแก้</h4><div class="text">${esc(r.original)}</div><div class="cp">${esc(r.original_cp)}</div></div>
      <div class="box after"><h4>หลังแก้</h4><div class="text">${esc(r.fixed)}</div><div class="cp">${esc(r.fixed_cp)}</div></div>
    </div>
    <h3 class="section-title">${r.changed ? "สิ่งที่แก้ไป" : "ไม่มีอะไรต้องแก้ ข้อความนี้ถูกต้องอยู่แล้ว"}</h3>
    <div class="issues">${fixedRows}${badRows}
      ${!fixedRows && !badRows ? `<p class="empty">โครงสร้างอักขระไทยถูกต้องตามกฎทุกตัว</p>` : ""}</div>
    ${r.visual_order_suspect ? `<div class="issue error" style="margin-top:8px"><div class="top"><span>สงสัยว่าข้อความนี้เรียงตามสายตา ไม่ใช่ลำดับตรรกะ</span><span class="count">${Math.round(r.visual_order_ratio * 100)}%</span></div></div>` : ""}`;
  } catch (e) {
    toast(e.message, true);
  } finally {
    busy(false);
  }
};

loadStatus();
