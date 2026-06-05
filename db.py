"""
db.py — Thunder FC
Database helpers using Flask's g object for per-request connection management.
Connections are opened once per request and closed automatically on teardown.
"""

import sqlite3
import os
from flask import g, current_app
from werkzeug.security import generate_password_hash


def get_db():
    """Return the per-request DB connection, opening it if needed."""
    if 'db' not in g:
        g.db = sqlite3.connect(
            current_app.config['DATABASE'],
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")   # better concurrency
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


def close_db(e=None):
    """Close DB connection at end of request."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db(app):
    """Create tables and seed default data if the DB is empty."""
    os.makedirs('data', exist_ok=True)
    team = app.config['TEAM_NAME']

    with app.app_context():
        db = get_db()
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                username  TEXT UNIQUE NOT NULL,
                password  TEXT NOT NULL,
                role      TEXT NOT NULL CHECK(role IN ('admin','coach','player')),
                player_id TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS players (
                player_id TEXT PRIMARY KEY,
                name      TEXT NOT NULL,
                position  TEXT NOT NULL CHECK(position IN ('Forward','Midfielder','Defender','Goalkeeper')),
                age       INTEGER CHECK(age BETWEEN 15 AND 55),
                team      TEXT
            );
            CREATE TABLE IF NOT EXISTS performances (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id        TEXT NOT NULL,
                match_date       TEXT NOT NULL,
                minutes_played   INTEGER DEFAULT 0,
                goals            INTEGER DEFAULT 0,
                assists          INTEGER DEFAULT 0,
                shots_on_target  INTEGER DEFAULT 0,
                pass_accuracy    REAL    DEFAULT 0,
                tackles          INTEGER DEFAULT 0,
                saves            INTEGER DEFAULT 0,
                clean_sheet      INTEGER DEFAULT 0,
                FOREIGN KEY (player_id) REFERENCES players(player_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS login_attempts (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                username   TEXT NOT NULL,
                ip_address TEXT NOT NULL,
                attempted_at TEXT NOT NULL DEFAULT (datetime('now')),
                success    INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_perf_player ON performances(player_id);
            CREATE INDEX IF NOT EXISTS idx_perf_date   ON performances(player_id, match_date);
            CREATE INDEX IF NOT EXISTS idx_login_user  ON login_attempts(username, attempted_at);
        """)

        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            _seed_users(db)

        if db.execute("SELECT COUNT(*) FROM players").fetchone()[0] == 0:
            _seed_players(db, team)

        db.commit()
        close_db()


def _seed_users(db):
    default_users = [
        ('admin',    'admin123',  'admin',  ''),
        ('coach1',   'coach123',  'coach',  ''),
        ('player1',  'pass001',   'player', 'P001'),
        ('player2',  'pass002',   'player', 'P002'),
        ('player3',  'pass003',   'player', 'P003'),
        ('player4',  'pass004',   'player', 'P004'),
        ('player5',  'pass005',   'player', 'P005'),
        ('player6',  'pass006',   'player', 'P006'),
        ('player7',  'pass007',   'player', 'P007'),
        ('player8',  'pass008',   'player', 'P008'),
        ('player9',  'pass009',   'player', 'P009'),
        ('player10', 'pass010',   'player', 'P010'),
        ('player11', 'pass011',   'player', 'P011'),
        ('player12', 'pass012',   'player', 'P012'),
        ('player13', 'pass013',   'player', 'P013'),
        ('player14', 'pass014',   'player', 'P014'),
        ('player15', 'pass015',   'player', 'P015'),
        ('player16', 'pass016',   'player', 'P016'),
        ('player17', 'pass017',   'player', 'P017'),
        ('player18', 'pass018',   'player', 'P018'),
        ('player19', 'pass019',   'player', 'P019'),
        ('player20', 'pass020',   'player', 'P020'),
    ]
    db.executemany(
        "INSERT INTO users (username, password, role, player_id) VALUES (?,?,?,?)",
        [(u, generate_password_hash(p), r, pid) for u, p, r, pid in default_users]
    )


def _seed_players(db, team):
    players = [
        ('P001','James Harrington','Forward',    24, team),
        ('P002','Carlos Mendez',   'Forward',    22, team),
        ('P003','Antoine Dubois',  'Forward',    27, team),
        ('P004','Emeka Okafor',    'Forward',    21, team),
        ('P005','Ryo Tanaka',      'Forward',    25, team),
        ('P006','Sebastian Reyes', 'Forward',    29, team),
        ('P007','Luca Bianchi',    'Midfielder', 26, team),
        ('P008','Kwame Asante',    'Midfielder', 23, team),
        ('P009','Arjun Sharma',    'Midfielder', 24, team),
        ('P010','Nils Bergstrom',  'Midfielder', 28, team),
        ('P011','Femi Adeyemi',    'Midfielder', 22, team),
        ('P012','Pablo Castillo',  'Midfielder', 30, team),
        ('P013','Marco Delgado',   'Defender',   28, team),
        ('P014','Yusuf Al-Rashid', 'Defender',   25, team),
        ('P015','Dmitri Volkov',   'Defender',   27, team),
        ('P016','Tobias Muller',   'Defender',   26, team),
        ('P017','Chen Wei',        'Defender',   24, team),
        ('P018','Kofi Mensah',     'Defender',   29, team),
        ('P019','Takeshi Mori',    'Goalkeeper', 30, team),
        ('P020','Alvaro Fernandez','Goalkeeper', 26, team),
    ]
    db.executemany("INSERT INTO players VALUES (?,?,?,?,?)", players)