"use strict";

/** ============================== CONFIG ============================== **/
const PRESET_TERMS = [
  "multimodal","reasoning","llm","\"large language model\"",
  "video generation","navigation","diffusion","egocentric",
];
let RENDER_DAYS = 5;

/** Optional: flip this to true and run tag_server.py to persist on disk */
const USE_BACKEND = false;
const BACKEND_BASE = ""; // e.g., "http://127.0.0.1:5055"

/** ============================== STATE =============================== **/
let ALL = [];   // flat list of papers across days, each has __date
const els = {
  content: document.getElementById("content"),
  search: document.getElementById("search"),
  titleOnly: document.getElementById("titleOnly"),
  onlyReadLater: document.getElementById("onlyReadLater"),
  onlyStarred: document.getElementById("onlyStarred"),
  days: document.getElementById("days"),
  presetChips: document.getElementById("presetChips"),
  topicFilter: document.getElementById("topicFilter"),
  newTopicBtn: document.getElementById("newTopicBtn"),
  renameTopicBtn: document.getElementById("renameTopicBtn"),
  deleteTopicBtn: document.getElementById("deleteTopicBtn"),
  exportReadLaterBtn: document.getElementById("exportReadLaterBtn"),
  exportStarsAllBtn: document.getElementById("exportStarsAllBtn"),
  exportTopicBtn: document.getElementById("exportTopicBtn"),
  importBtn: document.getElementById("importBtn"),
  count: document.getElementById("count"),
  paperTpl: document.getElementById("paperTpl"),
};

const STORAGE_KEYS = {
  READ_LATER: "arxiv_read_later",                // Set<id>
  TOPICS: "arxiv_topics",                        // string[] (ordered list)
  STARS_BY_TOPIC: "arxiv_stars_by_topic",        // { topic: Set<id> }
};

function getPaperId(p){ return p.id || p.link || p.title; }

/** =========================== UTILITIES ============================= **/
function fmtDateISO(d){ return d.toISOString().split("T")[0]; }
function normalize(s){ return (s||"").toLowerCase(); }
function debounce(fn, ms=250){ let t; return (...a)=>{clearTimeout(t); t=setTimeout(()=>fn(...a),ms)}; }
function download(filename, dataStr){
  const blob = new Blob([dataStr], {type: "application/json;charset=utf-8"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; document.body.appendChild(a); a.click();
  setTimeout(()=>{URL.revokeObjectURL(url); a.remove();}, 0);
}

/** =========================== STORAGE =============================== **/
function loadJSON(key, fallback){
  try{
    const s = localStorage.getItem(key);
    if(!s) return fallback;
    return JSON.parse(s);
  }catch{ return fallback; }
}
function saveJSON(key, val){
  localStorage.setItem(key, JSON.stringify(val));
}

/** Read Later: Set<id> **/
function loadReadLater(){
  const arr = loadJSON(STORAGE_KEYS.READ_LATER, []);
  return new Set(arr);
}
function saveReadLater(set){
  saveJSON(STORAGE_KEYS.READ_LATER, [...set]);
}

/** Topics list: string[] **/
function loadTopics(){
  return loadJSON(STORAGE_KEYS.TOPICS, []);
}
function saveTopics(list){
  saveJSON(STORAGE_KEYS.TOPICS, list);
}

/** Stars by topic: { topic: Set<id> } **/
function loadStarsByTopic(){
  const obj = loadJSON(STORAGE_KEYS.STARS_BY_TOPIC, {});
  // normalize to Set
  const out = {};
  for(const k of Object.keys(obj)) out[k] = new Set(obj[k]);
  return out;
}
function saveStarsByTopic(map){
  const plain = {};
  for(const k of Object.keys(map)) plain[k] = [...map[k]];
  saveJSON(STORAGE_KEYS.STARS_BY_TOPIC, plain);
}

/** ====================== BACKEND (optional) ========================= **/
async function backendGetAllTags(){
  const res = await fetch(`${BACKEND_BASE}/api/tags`);
  return res.json(); // { readLater: string[], topics: string[], starsByTopic: {topic: string[]} }
}
async function backendSaveAllTags(payload){
  await fetch(`${BACKEND_BASE}/api/tags`, {
    method:"POST", headers:{ "Content-Type":"application/json" },
    body: JSON.stringify(payload)
  });
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
function starredMatches(paper, onlyStar, starsByTopic){
  if(!onlyStar) return true;
  const id = getPaperId(paper);
  return Object.values(starsByTopic).some(set => set.has(id));
}
function topicMatches(paper, topic, starsByTopic){
  if(!topic) return true;
  const set = starsByTopic[topic];
  if(!set) return false;
  return set.has(getPaperId(paper));
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

function ensureTopicOptions(select){
  const topics = loadTopics();
  select.innerHTML = `<option value="">+ topic…</option>` + topics.map(t => `<option value="${t}">${t}</option>`).join("");
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
  const stars = loadStarsByTopic();

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

      // Read later button
      const rlBtn = node.querySelector(".tag-btn.readlater");
      const rlActive = rlSet.has(id);
      rlBtn.classList.toggle("active", rlActive);
      rlBtn.textContent = rlActive ? "✓ Read-Later" : "Read-Later";
      rlBtn.addEventListener("click", () => {
        const set = loadReadLater();
        if(set.has(id)) set.delete(id); else set.add(id);
        saveReadLater(set);
        applyFilters(); // rerender to reflect changes & filters
        maybeSyncBackend();
      });

      // Star controls
      const starBtn = node.querySelector(".tag-btn.star");
      const isStarred = Object.values(stars).some(s => s.has(id));
      starBtn.classList.toggle("active", isStarred);
      starBtn.textContent = isStarred ? "★ Starred" : "☆ Star";
      starBtn.addEventListener("click", () => {
        // If not in any topic yet, prompt to add one (optional UX)
        if(!Object.values(loadStarsByTopic()).some(s=>s.has(id))){
          const topics = loadTopics();
          if(topics.length === 0){
            alert("No topics yet. Click ‘New Topic’ above to create one, then use the + topic select to add.");
          }else{
            alert("Use the ‘+ topic…’ select to add this paper into a topic.");
          }
        } else {
          // remove from all topics (toggle off)
          const sbt = loadStarsByTopic();
          for(const t of Object.keys(sbt)) sbt[t].delete(id);
          saveStarsByTopic(sbt);
          applyFilters();
          maybeSyncBackend();
        }
      });

      // Topic add/remove UI
      const adder = node.querySelector(".topicAdder");
      ensureTopicOptions(adder);
      adder.addEventListener("change", (e) => {
        const t = e.target.value;
        if(!t) return;
        const sbt = loadStarsByTopic();
        if(!sbt[t]) sbt[t] = new Set();
        sbt[t].add(id);
        saveStarsByTopic(sbt);
        applyFilters();
        maybeSyncBackend();
        e.target.value = ""; // reset
      });

      // Existing topic badges
      const badgeWrap = node.querySelector(".topic-badges");
      for(const topic of Object.keys(stars)){
        if(stars[topic].has(id)){
          const badge = document.createElement("span");
          badge.className = "badge";
          badge.innerHTML = `${topic} <button class="x" title="Remove from topic">×</button>`;
          badge.querySelector(".x").addEventListener("click", () => {
            const sbt = loadStarsByTopic();
            sbt[topic].delete(id);
            saveStarsByTopic(sbt);
            applyFilters();
            maybeSyncBackend();
          });
          badgeWrap.appendChild(badge);
        }
      }

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
  const onlyStar = els.onlyStarred.checked;
  const topicSel = els.topicFilter.value;

  const rlSet = loadReadLater();
  const starsByTopic = loadStarsByTopic();

  const filtered = ALL.filter(p =>
    categoryMatches(p, cats) &&
    textMatches(p, terms, titleOnly) &&
    readLaterMatches(p, onlyRL, rlSet) &&
    starredMatches(p, onlyStar, starsByTopic) &&
    topicMatches(p, topicSel, starsByTopic)
  );

  render(filtered);
}

/** ======================== TOPIC MANAGEMENT ========================== **/
function refreshTopicFilterSelect(){
  const topics = loadTopics();
  els.topicFilter.innerHTML = `<option value="">(any)</option>` + topics.map(t=>`<option value="${t}">${t}</option>`).join("");
}

function createTopic(){
  const name = prompt("New topic name:");
  if(!name) return;
  const topics = loadTopics();
  if(topics.includes(name)) return alert("Topic already exists.");
  topics.push(name);
  saveTopics(topics);
  const sbt = loadStarsByTopic();
  if(!sbt[name]) sbt[name] = new Set();
  saveStarsByTopic(sbt);
  refreshTopicFilterSelect();
  applyFilters();
  maybeSyncBackend();
}
function renameTopic(){
  const topics = loadTopics();
  if(topics.length===0) return alert("No topics to rename.");
  const oldName = prompt(`Rename which topic? Available:\n${topics.join(", ")}`);
  if(!oldName || !topics.includes(oldName)) return;
  const newName = prompt("New name:", oldName);
  if(!newName) return;
  if(topics.includes(newName) && newName!==oldName) return alert("A topic with that name already exists.");

  const newTopics = topics.map(t=> t===oldName ? newName : t);
  saveTopics(newTopics);

  const sbt = loadStarsByTopic();
  sbt[newName] = sbt[oldName] || new Set();
  delete sbt[oldName];
  saveStarsByTopic(sbt);

  refreshTopicFilterSelect();
  applyFilters();
  maybeSyncBackend();
}
function deleteTopic(){
  const topics = loadTopics();
  if(topics.length===0) return alert("No topics to delete.");
  const name = prompt(`Delete which topic? Available:\n${topics.join(", ")}`);
  if(!name || !topics.includes(name)) return;
  if(!confirm(`Delete topic "${name}"? Papers remain available; only the topic tag is removed.`)) return;

  const newTopics = topics.filter(t => t!==name);
  saveTopics(newTopics);

  const sbt = loadStarsByTopic();
  delete sbt[name];
  saveStarsByTopic(sbt);

  refreshTopicFilterSelect();
  applyFilters();
  maybeSyncBackend();
}

/** ======================== EXPORT / IMPORT =========================== **/
function exportReadLater(){
  const rl = [...loadReadLater()];
  download("read_later.json", JSON.stringify(rl, null, 2));
}
function exportAllTopics(){
  const sbt = loadStarsByTopic();
  for(const topic of Object.keys(sbt)){
    const arr = [...sbt[topic]];
    download(`stars_${slugify(topic)}.json`, JSON.stringify(arr, null, 2));
  }
}
function exportSelectedTopic(){
  const topic = els.topicFilter.value;
  if(!topic) return alert("Choose a Topic first.");
  const sbt = loadStarsByTopic();
  const arr = [...(sbt[topic] || [])];
  download(`stars_${slugify(topic)}.json`, JSON.stringify(arr, null, 2));
}
function slugify(s){ return String(s).toLowerCase().replace(/\s+/g,'_').replace(/[^a-z0-9_]/g,''); }

function importJSONFile(file){
  const reader = new FileReader();
  reader.onload = () => {
    try{
      const parsed = JSON.parse(reader.result);
      // Heuristic: if array of ids => ask user where to put it
      if(Array.isArray(parsed)){
        const kind = prompt("Import into (type): 'read_later' OR a topic name (existing or new).");
        if(!kind) return;
        if(kind === "read_later"){
          const set = loadReadLater();
          for(const id of parsed) set.add(id);
          saveReadLater(set);
        }else{
          const topics = loadTopics();
          if(!topics.includes(kind)){ topics.push(kind); saveTopics(topics); }
          const sbt = loadStarsByTopic();
          if(!sbt[kind]) sbt[kind] = new Set();
          for(const id of parsed) sbt[kind].add(id);
          saveStarsByTopic(sbt);
        }
      }else if(parsed && parsed.readLater && parsed.starsByTopic && parsed.topics){
        // Full payload import
        saveReadLater(new Set(parsed.readLater));
        saveTopics(parsed.topics);
        const map = {};
        for(const k of Object.keys(parsed.starsByTopic)){
          map[k] = new Set(parsed.starsByTopic[k]);
        }
        saveStarsByTopic(map);
      }else{
        alert("Unrecognized JSON format.");
      }
      refreshTopicFilterSelect();
      applyFilters();
      maybeSyncBackend();
    }catch(e){
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
  els.onlyStarred.addEventListener("change", applyFilters);
}
function initTopicControls(){
  refreshTopicFilterSelect();
  els.topicFilter.addEventListener("change", applyFilters);
  els.newTopicBtn.addEventListener("click", createTopic);
  els.renameTopicBtn.addEventListener("click", renameTopic);
  els.deleteTopicBtn.addEventListener("click", deleteTopic);
}
function initExportImport(){
  els.exportReadLaterBtn.addEventListener("click", exportReadLater);
  els.exportStarsAllBtn.addEventListener("click", exportAllTopics);
  els.exportTopicBtn.addEventListener("click", exportSelectedTopic);
  els.importBtn.addEventListener("change", e => {
    if(e.target.files && e.target.files[0]) importJSONFile(e.target.files[0]);
    e.target.value = "";
  });
}

function maybeSyncBackend(){
  if(!USE_BACKEND) return;
  const payload = {
    readLater: [...loadReadLater()],
    topics: loadTopics(),
    starsByTopic: Object.fromEntries(Object.entries(loadStarsByTopic())
      .map(([k,v]) => [k, [...v]])),
  };
  backendSaveAllTags(payload).catch(()=>{ /* ignore */ });
}

document.addEventListener("DOMContentLoaded", async ()=>{
  initChipBehavior();
  initCategoryBehavior();
  initDaysBehavior();
  initSearchBehavior();
  initTopicControls();
  initExportImport();

  // Optional: pull from backend first
  if(USE_BACKEND){
    try{
      const data = await backendGetAllTags();
      saveReadLater(new Set(data.readLater || []));
      saveTopics(data.topics || []);
      const map = {};
      for(const k of Object.keys(data.starsByTopic || {})) map[k] = new Set(data.starsByTopic[k]);
      saveStarsByTopic(map);
    }catch{}
  }

  await loadDays(RENDER_DAYS);
  applyFilters();
});
