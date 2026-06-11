const $ = (id) => document.getElementById(id);
let selected = null;
let sections = { unprocessed: [], validated: [], failed: [] };

const FIELD_LABELS = {
  brand_name: "Brand name",
  alcohol_content: "Alcohol content",
  government_warning: "Gov. warning",
  class_type: "Class / type",
  net_contents: "Net contents",
  bottler: "Bottler",
  country_of_origin: "Country of origin",
};
const BADGE = { pass: "✓", fail: "✗", error: "!", analyzing: "⋯",
                pending: "" };

function initColumnResizers() {
  const main = document.querySelector('main');
  if (!main) return;

  const sidebarHandle = document.getElementById('resize-sidebar');
  const resultsHandle = document.getElementById('resize-results');

  // Load saved widths
  const savedSidebar = localStorage.getItem('labelcompare-sidebar-width');
  if (savedSidebar) {
    main.style.setProperty('--sidebar-width', savedSidebar);
  }
  const savedResults = localStorage.getItem('labelcompare-results-width');
  if (savedResults) {
    main.style.setProperty('--results-width', savedResults);
  }

  function attachResizer(handle, isSidebar) {
    if (!handle) return;

    let startX = 0;
    let startWidth = 0;

    handle.addEventListener('mousedown', (e) => {
      e.preventDefault();
      startX = e.clientX;
      const currentSidebar = parseInt(getComputedStyle(main).getPropertyValue('--sidebar-width')) || 240;
      const currentResults = parseInt(getComputedStyle(main).getPropertyValue('--results-width')) || 380;
      startWidth = isSidebar ? currentSidebar : currentResults;

      document.addEventListener('mousemove', onMouseMove);
      document.addEventListener('mouseup', onMouseUp, { once: true });
    });

    function onMouseMove(e) {
      const delta = e.clientX - startX;
      let newWidth = isSidebar ? startWidth + delta : startWidth - delta;

      if (isSidebar) {
        newWidth = Math.max(160, Math.min(480, newWidth));
        main.style.setProperty('--sidebar-width', `${newWidth}px`);
      } else {
        newWidth = Math.max(220, Math.min(650, newWidth));
        main.style.setProperty('--results-width', `${newWidth}px`);
      }
    }

    function onMouseUp() {
      document.removeEventListener('mousemove', onMouseMove);
      // Persist once per drag, not on every mousemove
      const key = isSidebar ? 'labelcompare-sidebar-width' : 'labelcompare-results-width';
      const prop = isSidebar ? '--sidebar-width' : '--results-width';
      const value = main.style.getPropertyValue(prop);
      if (value) localStorage.setItem(key, value.trim());
    }
  }

  attachResizer(sidebarHandle, true);
  attachResizer(resultsHandle, false);
}

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
                  .replace(/>/g, "&gt;");
}



function populateList(listEl, items) {
  listEl.innerHTML = "";
  for (const a of (items || [])) {
    const li = document.createElement("li");
    li.className = a.name === selected ? "selected" : "";
    const badge = `<span class="badge ${a.status}">${BADGE[a.status] ?? ""}</span>`;
    const prog = a.progress ? `<div class="prog-row"><span class="prog">${esc(a.progress)}</span></div>` : "";
    li.innerHTML = `
      <div class="pdf-row">
        ${badge}
        <span class="pdf-name">${esc(a.name)}</span>
      </div>
      ${prog}
    `;
    li.onclick = () => select(a.name);  // whole row selects
    listEl.appendChild(li);
  }
}

async function refresh() {
  sections = await (await fetch("/api/applications")).json();

  populateList($("unprocessed-list"), sections.unprocessed || []);
  populateList($("passed-list"), sections.validated || []);
  populateList($("failed-list"), sections.failed || []);

  // Enable analyze only for something selected that is not analyzing
  const all = (sections.unprocessed || []).concat(sections.validated || [], sections.failed || []);
  const isAnalyzing = all.find((a) => a.name === selected)?.status === "analyzing";
  $("analyzeBtn").disabled = !selected || isAnalyzing;
}

async function select(name) {
  selected = name;
  $("pdfFrame").src = `/api/applications/${encodeURIComponent(name)}/pdf`;
  await refresh();
  await showResult(name);
}

async function showResult(name) {
  const body = $("resultBody");
  const r = await fetch(`/api/applications/${encodeURIComponent(name)}/result`);
  if (!r.ok) {
    body.innerHTML = '<p class="muted">Not analyzed yet.</p>';
    return;
  }
  const entry = await r.json();
  if (entry.status === "error") {
    body.innerHTML = `<div class="verdict error">Analysis error</div>
                      <p>${esc(entry.error)}</p>`;
    return;
  }

  const v = entry.result || {};
  let html = `<div class="verdict ${entry.status}">
      ${entry.status === "pass" 
        ? "✓ This label looks good — required fields match" 
        : "Review needed — some fields do not match"}</div>`;

  // Simple comparison table
  html += `<h3 style="margin: 8px 0 6px; font-size: 14px;">Form vs. what’s on the label</h3>`;
  html += `<table class="fields"><tr><th>Field</th><th>Form says</th>
    <th>Label shows</th><th></th></tr>`;
  for (const [key, label] of Object.entries(FIELD_LABELS)) {
    const f = v.fields ? v.fields[key] : null;
    if (!f) continue;
    const lab = key === "government_warning"
      ? (f.label ? "(see warning below)" : "—") : esc(f.label ?? "—");
    html += `<tr class="${f.status}"><td>${label}</td>
      <td>${esc(f.application ?? "—")}</td><td>${lab}</td>
      <td class="status">${f.status}</td></tr>`;
  }
  html += "</table>";

  // Government warning (keep clear and prominent)
  const w = v.fields && v.fields.government_warning?.detail;
  if (w) {
    const yn = (ok, txt) =>
      `<span class="${ok ? "ok" : "bad"}">${ok ? "✓" : "✗"} ${txt}</span>`;
    html += `<div class="warningbox"><strong>Government warning check</strong><br>
      ${yn(w.present, "Present")} &nbsp; ${yn(w.content_ok, "Matches required text")} 
      &nbsp; ${yn(w.caps_ok, "In ALL CAPS")}<br><br>${esc(w.text ?? "(not found)")}</div>`;
  }

  // Regulatory analysis — tucked in details but easy to open for nuance
  const comp = entry.compliance;
  if (comp) {
    html += `<details style="margin-top: 10px;"><summary style="cursor:pointer; font-weight: 600;">More regulatory checks (for nuance & details)</summary>`;
    const cat = comp.product_category || "unknown";
    const assess = comp.overall_assessment || "needs review";
    html += `<div style="font-size:13px; margin: 6px 0;"><strong>Product type:</strong> ${esc(cat)} — <strong>Overall:</strong> ${esc(assess)}</div>`;

    if (comp.findings && comp.findings.length) {
      html += `<table class="fields" style="margin-top:4px;"><tr>
        <th>Requirement</th><th>Status</th><th>What the scan showed</th><th>Notes / citation</th></tr>`;
      for (const f of comp.findings) {
        const ev = f.evidence ? esc(f.evidence).replace(/\n/g, "<br>") : "—";
        const notes = [f.citation, f.notes].filter(Boolean).map(esc).join(" — ");
        html += `<tr class="${f.status}"><td>${esc(f.requirement)}</td>
          <td class="status">${esc(f.status)}</td>
          <td style="font-size:12px;">${ev}</td>
          <td style="font-size:12px;">${notes || "—"}</td></tr>`;
      }
      html += "</table>";
    }
    html += `</details>`;
  }

  // Raw OCR — label text first (isolated from form text for easier comparison)
  const ext = entry.extraction || {};
  if (ext.raw_label_text || ext.raw_form_text || (entry.transcripts && entry.transcripts.length)) {
    html += `<details style="margin-top: 10px;"><summary style="cursor:pointer; font-weight: 600;">See what the AI read (raw scan)</summary>`;

    if (ext.raw_label_text) {
      html += `<strong>Label Artwork Text</strong>`;
      html += `<pre style="white-space:pre-wrap; font-size:12px; background:#f8f8f8; padding:8px; border:1px solid #ddd; max-height:240px; overflow:auto;">${esc(ext.raw_label_text)}</pre>`;
    }

    if (ext.raw_form_text) {
      html += `<strong>Form / Application Text</strong>`;
      html += `<pre style="white-space:pre-wrap; font-size:12px; background:#f8f8f8; padding:8px; border:1px solid #ddd; max-height:240px; overflow:auto;">${esc(ext.raw_form_text)}</pre>`;
    }

    // Fallback to old full transcripts if splits not available
    if (!ext.raw_label_text && !ext.raw_form_text && entry.transcripts && entry.transcripts.length) {
      html += `<pre style="white-space:pre-wrap; font-size:12px; background:#f8f8f8; padding:8px; border:1px solid #ddd; max-height:240px; overflow:auto;">`;
      entry.transcripts.forEach((t, i) => {
        html += `\n--- View ${i+1} ---\n${esc(t)}\n`;
      });
      html += `</pre>`;
    }

    html += `</details>`;
  }

  body.innerHTML = html;
}

async function analyzeOne(name) {
  const poll = setInterval(refresh, 1500);
  try {
    await fetch(`/api/applications/${encodeURIComponent(name)}/analyze`,
                { method: "POST" });
  } finally {
    clearInterval(poll);
    await refresh();
    if (selected === name) await showResult(name);
  }
}

$("analyzeBtn").onclick = () => selected && analyzeOne(selected);

$("batchBtn").onclick = async () => {
  $("batchBtn").disabled = true;
  try {
    const unproc = (sections.unprocessed || []);
    for (const a of [...unproc]) await analyzeOne(a.name);
  } finally {
    $("batchBtn").disabled = false;
  }
};

$("uploadBtn").onclick = () => $("fileInput").click();
$("fileInput").onchange = () => uploadFiles($("fileInput").files);

async function uploadFiles(files) {
  if (!files.length) return;
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  const r = await fetch("/api/applications", { method: "POST", body: fd });
  if (!r.ok) {
    let detail = r.status;
    try { detail = (await r.json()).detail ?? detail; } catch (e) { /* noop */ }
    alert(`Upload failed: ${detail}`);
  }
  await refresh();
}

$("resetBtn").onclick = async () => {
  if (!confirm("This will permanently delete ALL PDFs and ALL analysis meta-data. The app will be reset to a completely clean state.\n\nAre you sure?")) {
    return;
  }
  try {
    const r = await fetch("/api/reset", { method: "POST" });
    if (!r.ok) {
      const detail = (await r.json()).detail ?? r.status;
      throw new Error(detail);
    }
    // Clear UI
    $("pdfFrame").src = "";
    $("resultBody").innerHTML = '<p class="muted">Select a PDF and click Analyze.</p>';
    selected = null;
    await refresh();
  } catch (e) {
    alert("Reset failed: " + e.message);
  }
};

const helpModal = $("helpModal");
const helpClose = $("helpClose");

$("helpBtn").onclick = () => {
  helpModal.style.display = "block";
};

helpClose.onclick = () => {
  helpModal.style.display = "none";
};

// Close modal when clicking outside the content
window.onclick = (event) => {
  if (event.target === helpModal) {
    helpModal.style.display = "none";
  }
};

const sb = $("sidebar");
sb.ondragover = (e) => { e.preventDefault(); sb.classList.add("dragover"); };
sb.ondragleave = () => sb.classList.remove("dragover");
sb.ondrop = (e) => {
  e.preventDefault();
  sb.classList.remove("dragover");
  uploadFiles(e.dataTransfer.files);
};

refresh();
initColumnResizers();
