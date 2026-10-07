import sqlite3
import os
from datetime import datetime

DB_FILE = os.path.join(os.path.dirname(__file__), "notifications.db")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS posted_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notification_id TEXT UNIQUE,
            state TEXT,
            title TEXT,
            apply_link TEXT,
            pdf_link TEXT,
            last_date TEXT,
            posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def is_already_posted(notification_id: str) -> bool:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM posted_notifications WHERE notification_id = ?", (notification_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def record_posted(notification_id: str, state: str, title: str, apply_link: str, pdf_link: str, last_date: str = ""):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR IGNORE INTO posted_notifications 
            (notification_id, state, title, apply_link, pdf_link, last_date)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (notification_id, state, title, apply_link, pdf_link, last_date))
        conn.commit()
    finally:
        conn.close()

def get_all_posted_count() -> int:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM posted_notifications")
    count = cursor.fetchone()[0]
    conn.close()
    return count
