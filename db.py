import json
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "tasting.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    category TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS attributes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('scale','select','multiselect','text')),
    config TEXT NOT NULL DEFAULT '{}',
    display_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    num_samples INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
    share_token TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at TEXT,
    sample_mapping TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    sample_label TEXT NOT NULL,
    taster_name TEXT NOT NULL,
    answers TEXT NOT NULL,
    submitted_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_attributes_product ON attributes(product_id, display_order);
CREATE INDEX IF NOT EXISTS idx_responses_session ON responses(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(share_token);
"""


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)
    seed_defaults()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ── Products ─────────────────────────────────────────────────────────────────

def list_products():
    with get_conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM products ORDER BY name").fetchall()]


def get_product(product_id):
    with get_conn() as c:
        r = c.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        return dict(r) if r else None


def create_product(name, category):
    with get_conn() as c:
        cur = c.execute("INSERT INTO products(name,category) VALUES(?,?)", (name, category))
        return cur.lastrowid


def update_product(product_id, name, category):
    with get_conn() as c:
        c.execute("UPDATE products SET name=?, category=? WHERE id=?", (name, category, product_id))


def delete_product(product_id):
    with get_conn() as c:
        c.execute("DELETE FROM products WHERE id=?", (product_id,))


# ── Attributes ───────────────────────────────────────────────────────────────

def list_attributes(product_id):
    with get_conn() as c:
        rows = c.execute(
            "SELECT * FROM attributes WHERE product_id=? ORDER BY display_order, id",
            (product_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["config"] = json.loads(d["config"]) if d["config"] else {}
        out.append(d)
    return out


def create_attribute(product_id, name, type_, config, display_order):
    with get_conn() as c:
        cur = c.execute(
            "INSERT INTO attributes(product_id,name,type,config,display_order) VALUES(?,?,?,?,?)",
            (product_id, name, type_, json.dumps(config), display_order),
        )
        return cur.lastrowid


def update_attribute(attr_id, name, type_, config, display_order):
    with get_conn() as c:
        c.execute(
            "UPDATE attributes SET name=?, type=?, config=?, display_order=? WHERE id=?",
            (name, type_, json.dumps(config), display_order, attr_id),
        )


def delete_attribute(attr_id):
    with get_conn() as c:
        c.execute("DELETE FROM attributes WHERE id=?", (attr_id,))


# ── Sessions ─────────────────────────────────────────────────────────────────

def create_session(name, product_id, num_samples, sample_mapping):
    token = secrets.token_urlsafe(8)
    with get_conn() as c:
        cur = c.execute(
            "INSERT INTO sessions(name,product_id,num_samples,share_token,sample_mapping) "
            "VALUES(?,?,?,?,?)",
            (name, product_id, num_samples, token, json.dumps(sample_mapping)),
        )
        return cur.lastrowid, token


def list_sessions():
    with get_conn() as c:
        rows = c.execute(
            """
            SELECT s.*, p.name AS product_name,
                   (SELECT COUNT(DISTINCT taster_name) FROM responses WHERE session_id=s.id) AS taster_count,
                   (SELECT COUNT(*) FROM responses WHERE session_id=s.id) AS response_count
            FROM sessions s JOIN products p ON p.id=s.product_id
            ORDER BY s.created_at DESC
            """
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["sample_mapping"] = json.loads(d["sample_mapping"]) if d["sample_mapping"] else {}
        out.append(d)
    return out


def get_session(session_id):
    with get_conn() as c:
        r = c.execute(
            "SELECT s.*, p.name AS product_name FROM sessions s "
            "JOIN products p ON p.id=s.product_id WHERE s.id=?",
            (session_id,),
        ).fetchone()
    if not r:
        return None
    d = dict(r)
    d["sample_mapping"] = json.loads(d["sample_mapping"]) if d["sample_mapping"] else {}
    return d


def get_session_by_token(token):
    with get_conn() as c:
        r = c.execute(
            "SELECT s.*, p.name AS product_name FROM sessions s "
            "JOIN products p ON p.id=s.product_id WHERE s.share_token=?",
            (token,),
        ).fetchone()
    if not r:
        return None
    d = dict(r)
    d["sample_mapping"] = json.loads(d["sample_mapping"]) if d["sample_mapping"] else {}
    return d


def close_session(session_id):
    with get_conn() as c:
        c.execute(
            "UPDATE sessions SET status='closed', closed_at=datetime('now') WHERE id=?",
            (session_id,),
        )


def reopen_session(session_id):
    with get_conn() as c:
        c.execute(
            "UPDATE sessions SET status='open', closed_at=NULL WHERE id=?",
            (session_id,),
        )


def delete_session(session_id):
    with get_conn() as c:
        c.execute("DELETE FROM sessions WHERE id=?", (session_id,))


# ── Responses ────────────────────────────────────────────────────────────────

def save_response(session_id, sample_label, taster_name, answers):
    with get_conn() as c:
        c.execute(
            "INSERT INTO responses(session_id,sample_label,taster_name,answers) VALUES(?,?,?,?)",
            (session_id, sample_label, taster_name, json.dumps(answers)),
        )


def list_responses(session_id):
    with get_conn() as c:
        rows = c.execute(
            "SELECT * FROM responses WHERE session_id=? ORDER BY submitted_at",
            (session_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["answers"] = json.loads(d["answers"]) if d["answers"] else {}
        out.append(d)
    return out


# ── Seed defaults ────────────────────────────────────────────────────────────

JAR_OPTIONS = [
    "1 — Way too low",
    "2 — A bit too low",
    "3 — Just right",
    "4 — A bit too high",
    "5 — Way too high",
]

LIKING_SCALE = {
    "min": 1,
    "max": 10,
    "low_label": "Dislike extremely",
    "high_label": "Like extremely",
}

DEFAULT_PRODUCTS = [
    {
        "name": "Coffee",
        "category": "coffee",
        "attributes": [
            {
                "name": "Aroma — overall liking",
                "type": "scale",
                "config": LIKING_SCALE,
            },
            {
                "name": "Flavor — overall liking",
                "type": "scale",
                "config": LIKING_SCALE,
            },
            {
                "name": "Mouthfeel / body",
                "type": "scale",
                "config": {
                    "min": 1,
                    "max": 10,
                    "low_label": "Thin / unpleasant",
                    "high_label": "Rich / pleasant",
                },
            },
            {
                "name": "Sweetness (JAR)",
                "type": "select",
                "config": {
                    "options": JAR_OPTIONS,
                    "description": "Just-About-Right scale — 3 means perfectly balanced.",
                },
            },
            {
                "name": "Bitterness / earthiness (JAR)",
                "type": "select",
                "config": {
                    "options": JAR_OPTIONS,
                    "description": "Just-About-Right scale — 3 means perfectly balanced.",
                },
            },
            {
                "name": "Off-notes detected?",
                "type": "select",
                "config": {"options": ["No", "Yes"]},
            },
            {
                "name": "Off-notes — describe (if any)",
                "type": "text",
                "config": {
                    "description": "e.g. metallic, cardboard, rancid, dusty, sour, soapy",
                },
            },
            {
                "name": "Overall liking",
                "type": "scale",
                "config": LIKING_SCALE,
            },
            {
                "name": "Comments / improvement direction",
                "type": "text",
                "config": {
                    "description": "Specific notes on aroma, flavor profile, finish, suggested tweaks.",
                },
            },
        ],
    },
]


def seed_defaults() -> None:
    """Seed default products + attributes if the products table is empty."""
    if list_products():
        return
    for product in DEFAULT_PRODUCTS:
        pid = create_product(product["name"], product.get("category"))
        for order, attr in enumerate(product["attributes"], start=1):
            create_attribute(pid, attr["name"], attr["type"], attr.get("config", {}), order)
