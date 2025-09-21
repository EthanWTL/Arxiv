"use strict";

/** ============================== CONFIG ============================== **/
const PRESET_TERMS = [
  "multimodal","reasoning","llm","\"large language model\"",
  "video generation","navigation","diffusion","egocentric",
];
let RENDER_DAYS = 5;

/** ============================== STATE =============================== **/
let ALL = [];   // flat list of papers across days, each has __date

const els = {
  content: document.getElementById("content"),
  search: document.getElementById("search"),
  titleOnly: document.getElementById("titleOnly"),
  onlyReadLater: document.getElementById("onlyReadLater"),
  days: document.getElementById("days"),
  presetChips: document.getElementById("presetChips"),
  exportReadLaterBtn: document.getElementById("exportReadLaterBtn"),
  importBtn: document.getElementById("importBtn"),
  count: document.getElementById("count"),
  paperTpl: document.getElementById("paperTpl"),
};

const STORAGE_KEY_RL = "arxiv_read_later"; // stores array of IDs

/** =========================== UTILITIES ============================= **/
function fmtDateISO(d){ return d.toISOString().split("T")[0]; }
function normalize(s){ return (s || "").toLowerCase(); }
function debounce(fn, ms=250){ let t; return (...a)=>{clearTimeout(t); t=setTimeout(()=>fn(...a),ms)}; }
function download(filename, dataStr){
  const blob = new Blob([dataStr], {type: "application/json;charset=utf-8"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; document.body.appendChild(a); a.click();
  setTimeout(()=>{URL.revokeObjectURL(url); a.remove();}, 0);
}
function getPaperId(p){ return p.id || p.link || p.title; }

/** =========================== STORAGE =============================== **/
function loadReadLater(){
  try{
    const s = localStorage.getItem(STORAGE_KEY_RL);
    const arr = s ? JSON.parse(s) : [];
    return new Set(Array.isArray(arr) ? arr : []);
  }catch{ return new Set(); }
}
function saveReadLater(set){
  localStorage.setItem(STORAGE_KEY_RL, JSON.stringify([...set]));
}

/** ============================ LOAD ================================= **/
async function fetchDay(dateStr){
  const url = `paper_json/${dateStr}.json`;
  try{
    const res = await fetch(url, { cache: "no-store" });
    if(!res.ok) return [];
    const papers = await res.json();
    return Array.isArray(papers) ? papers.map(p => ({...p, __date: dateStr})) : [];
  }catch{ return []; }
}

async function loadDays(nDays){
  const today = new Date();
  const tasks = [];
  for(let i=0;i<nDays;i++){
    const d = new Date(today); d.setDate(today.getDate() - i);
    tasks.push(fetchDay(fmtDateISO(d)));
  }
  const results = await Promise.all(tasks);
  ALL = results.flat();
}

/** ============================ FILTERS =============================== **/
function getActiveTerms(){
  const raw = els.search.value.trim();
  const quotes = [...raw.matchAll(/"([^"]+)"/g)].map(m => `"${m[1]}"`);
  const withoutQuotes = raw.replace(/"([^"]+)"/g, "").trim();
  const singles = withoutQuotes ? withoutQuotes.split(/\s+/) : [];
  const chipActives = [...els.presetChips.querySelectorAll(".chip.active")].map(b => b.dataset.term);
  return [...quotes, ...singles, ...chipActives].filter(Boolean);
}

function textMatches(paper, terms, titleOnly){
  if(terms.length === 0) return true;
  const title = normalize(paper.title);
  const summary = normalize(paper.summary);
  const hay = titleOnly ? title : (title + " " + summary);
  return terms.every(term => {
    term = term.trim();
    if(!term) return true;
    const quoted = term.startsWith('"') && term.endsWith('"');
    const needle = normalize(quoted ? term.slice(1,-1) : term);
    return hay.includes(needle);
  });
}

function categoryMatches(paper, allowed){
  if(allowed.size === 0) return true;
  const cats = Array.isArray(paper.category) ? paper.category : [];
  return cats.some(c => allowed.has(c));
}

function readLaterMatches(paper, onlyRL, rlSet){
  if(!onlyRL) return true;
  return rlSet.has(getPaperId(paper));
}

function getAllowedCats(){
  const boxes = [...document.querySelectorAll(".cat")];
  const checked = boxes.filter(b => b.checked).map(b => b.value);
  return new Set(checked);
}

/** =========================== RENDER ================================= **/
function groupByDate(papers){
  const map = new Map();
  for(const p of papers){
    if(!map.has(p.__date)) map.set(p.__date, []);
    map.get(p.__date).push(p);
  }
  return [...map.entries()].sort((a,b)=> a[0]<b[0]?1:-1);
}

function render(papers){
  const groups = groupByDate(papers);
  els.content.innerHTML = "";

  if(groups.length === 0){
    els.content.textContent = "No papers match your filters.";
    els.count.textContent = "0";
    return;
  }

  const rlSet = loadReadLater();
  let total = 0;

  for(const [date, items] of groups){
    if(items.length === 0) continue;
    total += items.length;

    const section = document.createElement("section");
    section.className = "date-section";
    section.innerHTML = `<h2>${date}</h2>`;
    els.content.appendChild(section);

    for(const p of items){
      const id = getPaperId(p);
      const node = els.paperTpl.content.firstElementChild.cloneNode(true);

      node.querySelector(".title").textContent = p.title;
      node.querySelector(".meta").textContent = `${p.published} | ${(p.category||[]).join(", ")}`;
      node.querySelector(".summary").textContent = p.summary;

      const link = node.querySelector(".link");
      link.href = p.link; link.textContent = "PDF";

      const rlBtn = node.querySelector(".tag-btn.readlater");
      const active = rlSet.has(id);
      rlBtn.classList.toggle("active", active);
      rlBtn.textContent = active ? "✓ Read-Later" : "Read-Later";

      rlBtn.addEventListener("click", () => {
        const set = loadReadLater();
        if(set.has(id)) set.delete(id); else set.add(id);
        saveReadLater(set);
        // Update button immediately
        rlBtn.classList.toggle("active", set.has(id));
        rlBtn.textContent = set.has(id) ? "✓ Read-Later" : "Read-Later";
        // If filtering by read-later, re-apply filters to hide/show cards
        if(els.onlyReadLater.checked) applyFilters();
      });

      section.appendChild(node);
    }
  }
  els.count.textContent = String(total);
}

/** =========================== APPLY FILTERS ========================== **/
function applyFilters(){
  const terms = getActiveTerms();
  const titleOnly = els.titleOnly.checked;
  const cats = getAllowedCats();
  const onlyRL = els.onlyReadLater.checked;
  const rlSet = loadReadLater();

  const filtered = ALL.filter(p =>
    categoryMatches(p, cats) &&
    textMatches(p, terms, titleOnly) &&
    readLaterMatches(p, onlyRL, rlSet)
  );

  render(filtered);
}

/** ======================== EXPORT / IMPORT =========================== **/
function exportReadLater(){
  const rl = [...loadReadLater()];
  download("read_later.json", JSON.stringify(rl, null, 2));
}

function importReadLaterFile(file){
  const reader = new FileReader();
  reader.onload = () => {
    try{
      const parsed = JSON.parse(reader.result);
      if(!Array.isArray(parsed)) return alert("Expected an array of paper IDs.");
      const set = loadReadLater();
      for(const id of parsed) set.add(id);
      saveReadLater(set);
      applyFilters();
    }catch{
      alert("Failed to parse JSON.");
    }
  };
  reader.readAsText(file);
}

/** ============================ INIT ================================= **/
function initChipBehavior(){
  els.presetChips.addEventListener("click",(e)=>{
    const btn = e.target.closest(".chip"); if(!btn) return;
    btn.classList.toggle("active"); applyFilters();
  });
}
function initCategoryBehavior(){
  document.querySelectorAll(".cat").forEach(cb => cb.addEventListener("change", applyFilters));
}
function initDaysBehavior(){
  els.days.addEventListener("change", async ()=>{
    RENDER_DAYS = parseInt(els.days.value, 10) || 5;
    els.content.textContent = "Loading…";
    await loadDays(RENDER_DAYS);
    applyFilters();
  });
}
function initSearchBehavior(){
  els.search.addEventListener("input", debounce(applyFilters, 200));
  els.titleOnly.addEventListener("change", applyFilters);
  els.onlyReadLater.addEventListener("change", applyFilters);
}
function initExportImport(){
  els.exportReadLaterBtn.addEventListener("click", exportReadLater);
  els.importBtn.addEventListener("change", e => {
    if(e.target.files && e.target.files[0]) importReadLaterFile(e.target.files[0]);
    e.target.value = "";
  });
}

document.addEventListener("DOMContentLoaded", async ()=>{
  initChipBehavior();
  initCategoryBehavior();
  initDaysBehavior();
  initSearchBehavior();
  initExportImport();

  await loadDays(RENDER_DAYS);
  applyFilters();
});
