const $ = (id) => document.getElementById(id);
let selected = null;
let apps = [];

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

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
                  .replace(/>/g, "&gt;");
}

async function refresh() {
  apps = await (await fetch("/api/applications")).json();
  const ul = $("pdfList");
  ul.innerHTML = "";
  for (const a of apps) {
    const li = document.createElement("li");
    li.className = a.name === selected ? "selected" : "";
    const badge = `<span class="badge ${a.status}">${BADGE[a.status] ?? ""}</span>`;
    const prog = a.progress ? `<span class="prog">${esc(a.progress)}</span>` : "";
    li.innerHTML = `${badge}<span>${esc(a.name)}</span>${prog}`;
    li.onclick = () => select(a.name);
    ul.appendChild(li);
  }
  $("analyzeBtn").disabled = !selected ||
    apps.find((a) => a.name === selected)?.status === "analyzing";
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
  const v = entry.result;
  let html = `<div class="verdict ${entry.status}">
      ${entry.status === "pass" ? "✓ PASSES minimum requirements"
                                 : "✗ FAILS minimum requirements"}</div>
    <table class="fields"><tr><th>Field</th><th>Application</th>
    <th>Label</th><th></th></tr>`;
  for (const [key, label] of Object.entries(FIELD_LABELS)) {
    const f = v.fields[key];
    if (!f) continue;
    const lab = key === "government_warning"
      ? (f.label ? "(see below)" : "—") : esc(f.label ?? "—");
    html += `<tr class="${f.status}"><td>${label}</td>
      <td>${esc(f.application ?? "—")}</td><td>${lab}</td>
      <td class="status">${f.status}</td></tr>`;
  }
  html += "</table>";
  const w = v.fields.government_warning?.detail;
  if (w) {
    const yn = (ok, txt) =>
      `<span class="${ok ? "ok" : "bad"}">${ok ? "✓" : "✗"} ${txt}</span>`;
    html += `<div class="warningbox"><b>Government warning</b><br>
      ${yn(w.present, "present")} &nbsp; ${yn(w.content_ok, "statutory text")}
      &nbsp; ${yn(w.caps_ok, "ALL CAPS")}<br><br>${esc(w.text ?? "(not found)")}</div>`;
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
    for (const a of [...apps]) await analyzeOne(a.name);
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

const sb = $("sidebar");
sb.ondragover = (e) => { e.preventDefault(); sb.classList.add("dragover"); };
sb.ondragleave = () => sb.classList.remove("dragover");
sb.ondrop = (e) => {
  e.preventDefault();
  sb.classList.remove("dragover");
  uploadFiles(e.dataTransfer.files);
};

refresh();
