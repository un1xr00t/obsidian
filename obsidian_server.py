"""
OBSIDIAN Server — Local storage backend for OBSIDIAN AI interface
Stores chats, projects, and files in SQLite + filesystem.

Install deps:
    pip install fastapi uvicorn

Run:
    python obsidian_server.py

Then open: http://localhost:8000
"""

import sqlite3
import json
import os
import sys
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Any, Optional
import uvicorn

# ── Paths ────────────────────────────────────────────────────
DATA_DIR  = Path.home() / "obsidian"
DB_PATH   = DATA_DIR / "obsidian.db"
FILES_DIR = DATA_DIR / "files"
HTML_PATH = Path(__file__).parent / "obsidian.html"

# ── App setup ────────────────────────────────────────────────
app = FastAPI(title="OBSIDIAN Server", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Database ─────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS chats (
            id      TEXT PRIMARY KEY,
            title   TEXT    DEFAULT '',
            created INTEGER DEFAULT 0,
            updated INTEGER DEFAULT 0,
            history TEXT    DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS projects (
            id   TEXT PRIMARY KEY,
            data TEXT DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS settings (
            id   INTEGER PRIMARY KEY DEFAULT 1,
            data TEXT    DEFAULT '{}'
        );
    """)
    conn.commit()
    conn.close()
    print(f"[OBSIDIAN] Database: {DB_PATH}")

# ── Health ────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "online", "version": "1.0"}

# ── Serve obsidian.html ─────────────────────────────────────────
@app.get("/")
def serve_ui():
    if HTML_PATH.exists():
        return FileResponse(HTML_PATH, media_type="text/html")
    return JSONResponse({"error": "obsidian.html not found next to obsidian_server.py"}, status_code=404)

# ── Chats ─────────────────────────────────────────────────────
@app.get("/chats")
def list_chats():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, title, created, updated FROM chats ORDER BY updated DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/chats/{chat_id}")
def get_chat(chat_id: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Chat not found")
    d = dict(row)
    d["history"] = json.loads(d["history"] or "[]")
    return d

class ChatPayload(BaseModel):
    id: str
    title: str = ""
    created: int = 0
    updated: int = 0
    history: list = []

@app.post("/chats")
def save_chat(chat: ChatPayload):
    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO chats (id, title, created, updated, history)
        VALUES (?, ?, ?, ?, ?)
    """, (chat.id, chat.title, chat.created, chat.updated, json.dumps(chat.history)))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.delete("/chats/{chat_id}")
def delete_chat(chat_id: str):
    conn = get_db()
    conn.execute("DELETE FROM chats WHERE id=?", (chat_id,))
    conn.commit()
    conn.close()
    return {"ok": True}

# ── Projects ──────────────────────────────────────────────────
@app.get("/projects")
def list_projects():
    conn = get_db()
    rows = conn.execute("SELECT data FROM projects").fetchall()
    conn.close()
    return [json.loads(r["data"]) for r in rows]

@app.get("/projects/{proj_id}")
def get_project(proj_id: str):
    conn = get_db()
    row = conn.execute("SELECT data FROM projects WHERE id=?", (proj_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Project not found")
    return json.loads(row["data"])

class ProjectPayload(BaseModel):
    id: str
    data: dict

@app.post("/projects")
def save_project(proj: ProjectPayload):
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO projects (id, data) VALUES (?, ?)",
        (proj.id, json.dumps(proj.data))
    )
    conn.commit()
    conn.close()
    return {"ok": True}

@app.delete("/projects/{proj_id}")
def delete_project(proj_id: str):
    conn = get_db()
    conn.execute("DELETE FROM projects WHERE id=?", (proj_id,))
    conn.commit()
    conn.close()
    return {"ok": True}

# ── Settings ──────────────────────────────────────────────────
@app.get("/settings")
def get_settings():
    conn = get_db()
    row = conn.execute("SELECT data FROM settings WHERE id=1").fetchone()
    conn.close()
    return json.loads(row["data"]) if row else {}

@app.post("/settings")
async def save_settings(request: Request):
    body = await request.json()
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO settings (id, data) VALUES (1, ?)",
        (json.dumps(body),)
    )
    conn.commit()
    conn.close()
    return {"ok": True}

# ── Bulk export / import ──────────────────────────────────────
@app.get("/export")
def export_all():
    conn = get_db()
    chat_rows = conn.execute("SELECT * FROM chats").fetchall()
    proj_rows = conn.execute("SELECT data FROM projects").fetchall()
    settings_row = conn.execute("SELECT data FROM settings WHERE id=1").fetchone()
    conn.close()

    chats_out = {}
    for r in chat_rows:
        d = dict(r)
        d["history"] = json.loads(d["history"] or "[]")
        chats_out[d["id"]] = d

    projects_out = {}
    for r in proj_rows:
        p = json.loads(r["data"])
        projects_out[p["id"]] = p

    return {
        "chats": chats_out,
        "projects": projects_out,
        "settings": json.loads(settings_row["data"]) if settings_row else {}
    }

@app.post("/import")
async def import_all(request: Request):
    data = await request.json()
    conn = get_db()
    for chat in data.get("chats", {}).values():
        conn.execute("""
            INSERT OR REPLACE INTO chats (id, title, created, updated, history)
            VALUES (?,?,?,?,?)
        """, (
            chat["id"],
            chat.get("title", ""),
            chat.get("created", 0),
            chat.get("updated", 0),
            json.dumps(chat.get("history", []))
        ))
    for proj in data.get("projects", {}).values():
        conn.execute(
            "INSERT OR REPLACE INTO projects (id, data) VALUES (?,?)",
            (proj["id"], json.dumps(proj))
        )
    if "settings" in data:
        conn.execute(
            "INSERT OR REPLACE INTO settings (id, data) VALUES (1,?)",
            (json.dumps(data["settings"]),)
        )
    conn.commit()
    conn.close()
    return {"ok": True, "imported": {
        "chats": len(data.get("chats", {})),
        "projects": len(data.get("projects", {}))
    }}

# ── Startup ───────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    print("[OBSIDIAN] Server running at http://localhost:8000")
    print("[OBSIDIAN] Open http://localhost:8000 in your browser")
    if not HTML_PATH.exists():
        print(f"[OBSIDIAN] WARNING: obsidian.html not found at {HTML_PATH}")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
