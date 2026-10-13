"""Database helpers. The system uses SQLite: one file, no installation needed."""
import sqlite3
from flask import g
import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
  full_name TEXT, role TEXT NOT NULL, password_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS branches(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, code TEXT UNIQUE, location TEXT);
CREATE TABLE IF NOT EXISTS ministries(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, leader TEXT,
  branch_id INTEGER REFERENCES branches(id), description TEXT);
CREATE TABLE IF NOT EXISTS members(id INTEGER PRIMARY KEY AUTOINCREMENT, full_name TEXT, gender TEXT, age_group TEXT,
  branch_id INTEGER REFERENCES branches(id), ministry_id INTEGER REFERENCES ministries(id), phone TEXT,
  join_date TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS attendance(id INTEGER PRIMARY KEY AUTOINCREMENT, branch_id INTEGER REFERENCES branches(id),
  service_date TEXT, service_type TEXT, attendance INTEGER, notes TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, branch_id INTEGER REFERENCES branches(id),
  event_date TEXT, event_type TEXT, expected_attendance INTEGER, status TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS finances(id INTEGER PRIMARY KEY AUTOINCREMENT, branch_id INTEGER REFERENCES branches(id),
  tx_date TEXT, category TEXT, amount REAL, recorded_by TEXT, note TEXT,
  injected_anomaly INTEGER DEFAULT 0, flagged INTEGER DEFAULT 0, anomaly_score REAL,
  review_status TEXT DEFAULT 'Not reviewed');
CREATE TABLE IF NOT EXISTS outreach(id INTEGER PRIMARY KEY AUTOINCREMENT, branch_id INTEGER REFERENCES branches(id),
  activity_date TEXT, activity_type TEXT, title TEXT, beneficiaries INTEGER, cost REAL, notes TEXT);
CREATE TABLE IF NOT EXISTS resources(id INTEGER PRIMARY KEY AUTOINCREMENT, branch_id INTEGER REFERENCES branches(id),
  name TEXT, resource_type TEXT, status TEXT, condition TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, category TEXT, content TEXT, added_on TEXT);
CREATE TABLE IF NOT EXISTS model_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, run_on TEXT, model_name TEXT, target TEXT,
  mae REAL, rmse REAL, r2 REAL, baseline_mae REAL, n_train INTEGER, n_test INTEGER, notes TEXT);
CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, username TEXT, action TEXT, detail TEXT);
"""


def connect(path=None):
    conn = sqlite3.connect(path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(_=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(path=None):
    conn = connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
