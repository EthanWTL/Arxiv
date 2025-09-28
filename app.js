"use strict";

/** ============================== CONFIG ============================== **/
const PRESET_TERMS = [
  "multimodal","reasoning","llm","\"large language model\"",
  "video generation","navigation","diffusion","egocentric",
];

/** ============================== STATE =============================== **/
let ALL = [];                // papers for the currently selected date
let INDEX = [];              // [{date, count}, ...] from paper_json/index.json

const els = {
  content: document.getElementById("content"),
  search: document.getElementById("search"),
  titleOnly: document.getElementById("titleOnly"),
  presetChips: document.getElementById("presetChips"),
  count: document.getElementById("count"),
  paperTpl: document.getElementById("paperTpl"),
  date: document.getElementById("date"),
  prevDay: document.getElementById("prevDay"),
  nextDay: document.getElementById("nextDay"),
  todayBtn: document.getElementById("todayBtn"),
};

function fmtISO(d){ return d.toISOString().split("T")[0]; }
function parseISO(s){ const [y,m,d] = s.split("-").map(Number); return new Date(Date.UTC(y,m-1,d)); }
function normalize(s){ return (s || "").toLowerCase(); }
function debounce(fn, ms=250){ let t; return (...a)=>{clearTimeout(t); t=setTimeout(()=>fn(...a),ms)}; }

/** ============================ LOAD ================================= **/
async function fetchJSON(url){
  try{
    const res = await fetch(url, { cache: "no-store" });
    if(!res.ok) return null;
    return await res.json();
  }catch{ return null; }
}

async function loadIndex(){
  const idx = await fetchJSON("paper_json/index.json");
  INDEX = Array.isArray(idx) ? idx.filter(x=>x && x.date).sort((a,b)=>a.date.localeCompare(b.date)) : [];
}

async function loadDate(dateStr){
  els.content.textContent = "Loading…";
  const data = await fetchJSON(`paper_json/${dateStr}.json`);
  ALL = Array.isArray(data) ? data : [];
  applyFilters();
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

function getAllowedCats(){
  const boxes = [...document.querySelectorAll(".cat")];
  const checked = boxes.filter(b => b.checked).map(b => b.value);
  return new Set(checked);
}

/** =========================== RENDER ================================= **/
function render(papers, dateStr){
  els.content.innerHTML = "";
  const section = document.createElement("section");
  section.className = "date-section";
  const heading = document.createElement("h2");
  heading.textContent = dateStr;
  section.appendChild(heading);

  if(!papers || papers.length === 0){
    const empty = document.createElement("div");
    empty.textContent = "No papers for this day (or none matched your filters).";
    section.appendChild(empty);
    els.content.appendChild(section);
    els.count.textContent = "0";
    return;
  }

  for(const p of papers){
    const node = els.paperTpl.content.firstElementChild.cloneNode(true);
    node.querySelector(".title").textContent = p.title;
    node.querySelector(".meta").textContent = `${p.published} | ${(p.category||[]).join(", ")}`;
    node.querySelector(".summary").textContent = p.summary;
    const link = node.querySelector(".link");
    link.href = p.link; link.textContent = "PDF";
    section.appendChild(node);
  }

  els.content.appendChild(section);
  els.count.textContent = String(papers.length);
}

/** =========================== APPLY FILTERS ========================== **/
function applyFilters(){
  const terms = getActiveTerms();
  const titleOnly = els.titleOnly.checked;
  const cats = getAllowedCats();
  const filtered = ALL.filter(p =>
    categoryMatches(p, cats) &&
    textMatches(p, terms, titleOnly)
  );
  render(filtered, els.date.value || "(no date)");
}

/** ============================ DATE UX =============================== **/
function setDateBoundsFromIndex(){
  if(INDEX.length === 0) return;
  const min = INDEX[0].date;
  const max = INDEX[INDEX.length - 1].date;
  els.date.min = min;
  els.date.max = max;
  if(!els.date.value) els.date.value = max; // default to latest available
}

function findNeighborDate(current, dir){
  if(INDEX.length === 0) return null;
  const i = INDEX.findIndex(x => x.date === current);
  if(i < 0) return null;
  const j = i + (dir < 0 ? -1 : 1);
  if(j < 0 || j >= INDEX.length) return null;
  return INDEX[j].date;
}

/** ============================ INIT ================================= **/
function initChips(){ els.presetChips.addEventListener("click",(e)=>{ const btn=e.target.closest(".chip"); if(!btn) return; btn.classList.toggle("active"); applyFilters(); }); }
function initCategories(){ document.querySelectorAll(".cat").forEach(cb => cb.addEventListener("change", applyFilters)); }
function initSearch(){ els.search.addEventListener("input", debounce(applyFilters, 200)); els.titleOnly.addEventListener("change", applyFilters); }
function initDateControls(){
  els.date.addEventListener("change", async ()=>{
    if(els.date.value){ await loadDate(els.date.value); }
  });
  els.todayBtn.addEventListener("click", async ()=>{
    // pick latest available date (from index), not local today
    if(INDEX.length){ els.date.value = INDEX[INDEX.length-1].date; await loadDate(els.date.value); }
  });
  els.prevDay.addEventListener("click", async ()=>{
    const n = findNeighborDate(els.date.value, -1);
    if(n){ els.date.value = n; await loadDate(n); }
  });
  els.nextDay.addEventListener("click", async ()=>{
    const n = findNeighborDate(els.date.value, +1);
    if(n){ els.date.value = n; await loadDate(n); }
  });
}

document.addEventListener("DOMContentLoaded", async ()=>{
  initChips();
  initCategories();
  initSearch();
  initDateControls();

  await loadIndex();
  setDateBoundsFromIndex();

  if(els.date.value){
    await loadDate(els.date.value);
  }else{
    // No index yet: show friendly message
    els.content.textContent = "No data yet. Once the daily workflow runs, days will appear here.";
  }
});
