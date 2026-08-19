import os
import sqlite3
from datetime import datetime
from flask import current_app
from werkzeug.security import generate_password_hash


def get_db():
    conn = sqlite3.connect(current_app.config["DB_PATH"])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Cree le schema s'il n'existe pas deja, puis seme des donnees
    de demonstration UNIQUEMENT si la base est vide (pour ne jamais
    ecraser des donnees reelles lors d'un redemarrage)."""
    conn = get_db()
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS robots (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Online',
            battery INTEGER NOT NULL DEFAULT 100,
            volume INTEGER NOT NULL DEFAULT 50,
            language TEXT NOT NULL DEFAULT 'Français',
            voice TEXT NOT NULL DEFAULT 'Female',
            speed REAL NOT NULL DEFAULT 1.0
        );

        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('super_admin','technicien')),
            display_name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ownership (
            username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
            robot_id TEXT NOT NULL REFERENCES robots(id) ON DELETE CASCADE,
            PRIMARY KEY (username, robot_id)
        );

        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            robot_id TEXT NOT NULL REFERENCES robots(id) ON DELETE CASCADE,
            time TEXT NOT NULL,
            event TEXT NOT NULL,
            by_user TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            robot_id TEXT NOT NULL REFERENCES robots(id) ON DELETE CASCADE,
            time TEXT NOT NULL,
            type TEXT NOT NULL,
            severity TEXT NOT NULL CHECK(severity IN ('info','warning','critical')),
            message TEXT NOT NULL,
            acknowledged INTEGER NOT NULL DEFAULT 0
        );
    """)
    conn.commit()

    # Ne semer les donnees de demo que si la base est vraiment vide
    if cur.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO robots (id,name,status,battery,volume,language,voice,speed) VALUES (?,?,?,?,?,?,?,?)",
            ("robot-alpha", "MP-20", "Online", 87, 65, "Français", "Female", 1.0)
        )
        cur.execute(
            "INSERT INTO users (username,password_hash,role,display_name) VALUES (?,?,?,?)",
            ("client", generate_password_hash(os.getenv("ADMIN_PASSWORD")), "super_admin", "Super Admin")
        )
        cur.execute(
            "INSERT INTO users (username,password_hash,role,display_name) VALUES (?,?,?,?)",
            ("tech1", generate_password_hash(os.getenv("TECH_PASSWORD")), "technicien", "Technicien 1")
        )
        # Le super_admin et le technicien de demo sont tous deux
        # rattaches a l'unique robot du compte.
        cur.execute("INSERT INTO ownership VALUES ('client','robot-alpha')")
        cur.execute("INSERT INTO ownership VALUES ('tech1','robot-alpha')")

        exemples_logs = [
            ("robot-alpha", "Robot demarre", "system"),
            ("robot-alpha", "Connexion reussie", "client"),
        ]
        for robot_id, event, by in exemples_logs:
            cur.execute(
                "INSERT INTO logs (robot_id,time,event,by_user) VALUES (?,?,?,?)",
                (robot_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), event, by)
            )

        exemples_alertes = [
            ("robot-alpha", "mouvement", "warning", "Mouvement detecte hors horaires de patrouille"),
            ("robot-alpha", "connexion", "info", "Connexion depuis une nouvelle adresse reseau"),
        ]
        for robot_id, type_, sev, msg in exemples_alertes:
            cur.execute(
                "INSERT INTO alerts (robot_id,time,type,severity,message,acknowledged) VALUES (?,?,?,?,?,0)",
                (robot_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), type_, sev, msg)
            )

        conn.commit()
        print("Base de donnees initialisee avec les comptes de demonstration.")

    conn.close()


def add_log(robot_id, event, by_user):
    conn = get_db()
    conn.execute(
        "INSERT INTO logs (robot_id,time,event,by_user) VALUES (?,?,?,?)",
        (robot_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), event, by_user)
    )
    conn.commit()
    conn.close()


def add_alert(robot_id, type_, severity, message):
    conn = get_db()
    conn.execute(
        "INSERT INTO alerts (robot_id,time,type,severity,message,acknowledged) VALUES (?,?,?,?,?,0)",
        (robot_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), type_, severity, message)
    )
    conn.commit()
    conn.close()


def user_owns_robot(username, robot_id):
    """Verification d'appartenance -- le coeur de l'isolation multi-
    robots. Appelee au debut de CHAQUE route qui manipule un robot_id,
    pour qu'un utilisateur ne puisse jamais agir sur un robot qui ne
    lui a pas ete explicitement associe, meme en modifiant l'URL ou
    la requete a la main."""
    conn = get_db()
    row = conn.execute(
        "SELECT 1 FROM ownership WHERE username=? AND robot_id=?",
        (username, robot_id)
    ).fetchone()
    conn.close()
    return row is not None


def get_user_robots(username):
    conn = get_db()
    rows = conn.execute("""
        SELECT r.* FROM robots r
        JOIN ownership o ON o.robot_id = r.id
        WHERE o.username = ?
        ORDER BY r.name
    """, (username,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_robot(robot_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM robots WHERE id=?", (robot_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

