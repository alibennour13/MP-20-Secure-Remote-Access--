from flask import Blueprint, redirect, render_template, request, session
from werkzeug.security import check_password_hash
from app.database import get_db, get_user_robots

auth_bp = Blueprint("auth", __name__)


def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            robots = get_user_robots(username)
            if not robots:
                return render_template(LOGIN_HTML, error="Aucun robot n'est associe a ce compte.")

            session["user"] = username
            session["role"] = user["role"]
            session["current_robot_id"] = robots[0]["id"]
            add_log(robots[0]["id"], f"Connexion reussie ({user['role']})", username)
            return redirect("/dashboard")

        return render_template(LOGIN_HTML, error="Identifiant ou mot de passe incorrect.")

    return render_template(LOGIN_HTML)

def logout():
    if "user" in session and session.get("current_robot_id"):
        add_log(session["current_robot_id"], "Deconnexion", session["user"])
    session.clear()
    return redirect("/")
