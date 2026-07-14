import sqlite3
from pathlib import Path

DATABASE_PATH = Path(file).with_name("vad_tracker.db")


def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS creators (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                display_name TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                vacation_until TEXT,
                last_meaningful_message TEXT,
                engagement_score INTEGER NOT NULL DEFAULT 0,
                date_added TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS engagement_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                message_id INTEGER,
                chat_id INTEGER,
                message_text TEXT,
                points INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (telegram_id)
                    REFERENCES creators (telegram_id)
            );

            CREATE TABLE IF NOT EXISTS pop_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                message_id INTEGER,
                chat_id INTEGER,
                thread_id INTEGER,
                proof_type TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reviewed_by INTEGER,
                review_note TEXT,
                FOREIGN KEY (telegram_id)
                    REFERENCES creators (telegram_id)
            );
            """
        )


def add_creator(telegram_id, username, display_name):
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO creators (
                telegram_id,
                username,
                display_name
            )
            VALUES (?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                display_name = excluded.display_name,
                active = 1
            """,
            (telegram_id, username, display_name),
        )


def get_creator(telegram_id):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT *
            FROM creators
            WHERE telegram_id = ?
            """,
            (telegram_id,),
        ).fetchone()


def get_active_creators():
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT *
            FROM creators
            WHERE active = 1
            ORDER BY display_name
            """
        ).fetchall()