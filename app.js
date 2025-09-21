"use strict";

const PRESET_TERMS = [
  "multimodal",
  "reasoning",
  "llm",
  '"large language model"',
  "video generation",
  "navigation",
  "diffusion",
  "egocentric",
];

let ALL = [];   // { date, ...paper }
let RENDER_DAYS = 5;

const els = {
  content: document.getElementById("content"),
  search: document.getElementById("search"),
  titleOnly: document.getElementById("titleOnly"),
  days: document.getElementById("days"),
  presetChips: document.getElementById("presetChips"),
  count: document.getElementById("count"),
};

function fmtDateISO(d){
  return d.toISOString().split("T")[0];
}

async function fetchDay(dateStr){
  const url = `paper_json/${dateStr}.json`;
  try{
    const res = await fetch(url, { cache: "no-store" });
    if(!res.ok) return [];
    const papers = await res.json();
    if(!Array.isArray(papers)) return [];
    // attach date to each paper for grouping later
    return papers.map(p => ({...p, __date: dateStr}));
  }catch(e){
    return [];
  }
}

async function loadDays(nDays){
  const today = new Date();
  const batches = [];
  for(let i=0;i<nDays;i++){
    const d = new Date(today);
    d.setDate(today.getDate() - i);
    batches.push(fetchDay(fmtDateISO(d)));
  }
  const results = await Promise.all(batches);
  ALL = results.flat();
}

function normalize(str){
  return (str || "").toLowerCase();
}

function textMatches(paper, terms, titleOnly){
  if(terms.length === 0) return true;
  const title = normalize(paper.title);
  const summary = normalize(paper.summary);
  const hay = titleOnly ? title : (title + " " + summary);
  // Support quoted phrases: terms already include quotes if clicked
  return terms.every(term => {
    term = term.trim();
    if(!term) return true;
    const isQuoted = term.startsWith('"') && term.endsWith('"');
    const needle = normalize(isQuoted ? term.slice(1, -1) : term);
    return hay.includes(needle);
  });
}

function categoryMatches(paper, allowedCats){
  if(allowedCats.size === 0) return true; // none selected => allow all
  const cats = Array.isArray(paper.category) ? paper.category : [];
  // include if any category intersects
  return cats.some(c => allowedCats.has(c));
}

function getActiveTerms(){
  const raw = els.search.value.trim();
  // Split by spaces but keep quoted phrases intact
  // Simple parser: find "phrases", keep them; remaining split by spaces
  const quotes = [...raw.matchAll(/"([^"]+)"/g)].map(m => `"${m[1]}"`);
  const withoutQuotes = raw.replace(/"([^"]+)"/g, "").trim();
  const singles = withoutQuotes ? withoutQuotes.split(/\s+/) : [];
  const chipActives = [...els.presetChips.querySelectorAll(".chip.active")].map(b => b.dataset.term);
  return [...quotes, ...singles, ...chipActives].filter(Boolean);
}

function getAllowedCats(){
  const boxes = [...document.querySelectorAll(".cat")];
  const checked = boxes.filter(b => b.checked).map(b => b.value);
  return new Set(checked);
}

function groupByDate(papers){
  const map = new Map();
  for(const p of papers){
    if(!map.has(p.__date)) map.set(p.__date, []);
    map.get(p.__date).push(p);
  }
  // Sort dates descending
  return [...map.entries()].sort((a,b) => (a[0] < b[0] ? 1 : -1));
}

function render(papers){
  const groups = groupByDate(papers);
  els.content.innerHTML = "";

  if(groups.length === 0){
    els.content.textContent = "No papers match your filters.";
    els.count.textContent = "0";
    return;
  }

  let total = 0;

  for(const [date, items] of groups){
    if(items.length === 0) continue;
    total += items.length;

    const section = document.createElement("section");
    section.className = "date-section";
    section.innerHTML = `<h2>${date}</h2>`;
    els.content.appendChild(section);

    for(const p of items){
      const div = document.createElement("div");
      div.className = "paper";
      const cats = Array.isArray(p.category) ? p.category.join(", ") : "";
      div.innerHTML = `
        <div class="title">${p.title}</div>
        <div class="meta">${p.published} | ${cats}</div>
        <div class="summary">${p.summary}</div>
        <a class="link" href="${p.link}" target="_blank" rel="noopener noreferrer">PDF</a>
      `;
      section.appendChild(div);
    }
  }
  els.count.textContent = String(total);
}

function applyFilters(){
  const terms = getActiveTerms();
  const titleOnly = els.titleOnly.checked;
  const cats = getAllowedCats();

  const filtered = ALL.filter(p =>
    categoryMatches(p, cats) &&
    textMatches(p, terms, titleOnly)
  );

  render(filtered);
}

// Simple debounce for input
function debounce(fn, ms=250){
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

function initChipBehavior(){
  els.presetChips.addEventListener("click", (e) => {
    const btn = e.target.closest(".chip");
    if(!btn) return;
    btn.classList.toggle("active");
    applyFilters();
  });
}

function initCategoryBehavior(){
  document.querySelectorAll(".cat").forEach(cb => {
    cb.addEventListener("change", applyFilters);
  });
}

function initDaysBehavior(){
  els.days.addEventListener("change", async () => {
    RENDER_DAYS = parseInt(els.days.value, 10) || 5;
    els.content.textContent = "Loading…";
    await loadDays(RENDER_DAYS);
    applyFilters();
  });
}

function initSearchBehavior(){
  els.search.addEventListener("input", debounce(applyFilters, 200));
  els.titleOnly.addEventListener("change", applyFilters);
}

document.addEventListener("DOMContentLoaded", async () => {
  initChipBehavior();
  initCategoryBehavior();
  initDaysBehavior();
  initSearchBehavior();

  await loadDays(RENDER_DAYS);
  applyFilters();
});
