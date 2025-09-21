#!/usr/bin/env python3
# tag_server.py
from flask import Flask, request, jsonify
from pathlib import Path
import json
from flask_cors import CORS

DATA = Path("user_data")
DATA.mkdir(exist_ok=True)

READ_LATER = DATA / "read_later.json"
TOPICS = DATA / "topics.json"
STARS_DIR = DATA / "stars"
STARS_DIR.mkdir(exist_ok=True)

def read_json(p, default):
  if p.exists():
    try:
      return json.loads(p.read_text(encoding="utf-8"))
    except: pass
  return default

def write_json(p, obj):
  p.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")

def load_all():
  read_later = read_json(READ_LATER, [])
  topics = read_json(TOPICS, [])
  stars_by_topic = {}
  for t in topics:
    f = STARS_DIR / f"{t}.json"
    stars_by_topic[t] = read_json(f, [])
  return {"readLater": read_later, "topics": topics, "starsByTopic": stars_by_topic}

def save_all(payload):
  write_json(READ_LATER, payload.get("readLater", []))
  topics = payload.get("topics", [])
  write_json(TOPICS, topics)
  # clear files not in topics
  for f in STARS_DIR.glob("*.json"):
    if f.stem not in topics:
      f.unlink(missing_ok=True)
  stars_by_topic = payload.get("starsByTopic", {})
  for t in topics:
    f = STARS_DIR / f"{t}.json"
    write_json(f, stars_by_topic.get(t, []))

app = Flask(__name__)
CORS(app)  # adjust for your domain in production

@app.get("/api/tags")
def get_tags():
  return jsonify(load_all())

@app.post("/api/tags")
def set_tags():
  payload = request.get_json(force=True)
  save_all(payload)
  return jsonify({"ok": True})

if __name__ == "__main__":
  app.run(host="0.0.0.0", port=5055, debug=False)
