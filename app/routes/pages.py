from flask import Blueprint, redirect, render_template, request, session
from app.auth import login_required, role_required
from app.database import get_db, user_owns_robot
from app.utils.context import current_context
from app.utils.ui import ICONS

pages_bp = Blueprint("pages", __name__)


@pages_bp.route("/dashboard")
def dashboard():
    robot, robot_id, role, display_name, topbar = current_context()

    conn = get_db()
    unread_count = conn.execute(
        "SELECT COUNT(*) FROM alerts WHERE robot_id=? AND acknowledged=0", (robot_id,)
    ).fetchone()[0]
    conn.close()

    return render_template(
        "dashboard.html", topbar=topbar, icons=ICONS,
        robot=robot, role=role, unread_count=unread_count
    )


@pages_bp.route("/langue")
def page_langue():
    robot, robot_id, role, display_name, topbar = current_context()
    return render_template("langue.html", topbar=topbar, icons=ICONS, robot=robot)


@pages_bp.route("/audio")
def page_audio():
    robot, robot_id, role, display_name, topbar = current_context()
    return render_template("audio.html", topbar=topbar, icons=ICONS, robot=robot)


@pages_bp.route("/journal")
def page_journal():
    robot, robot_id, role, display_name, topbar = current_context()
    username = session["user"]

    conn = get_db()
    if role == "super_admin":
        rows = conn.execute("SELECT * FROM logs WHERE robot_id=? ORDER BY id DESC LIMIT 30", (robot_id,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM logs WHERE robot_id=? AND by_user=? ORDER BY id DESC LIMIT 30",
            (robot_id, username)
        ).fetchall()
    conn.close()

    return render_template(
        "journal.html", topbar=topbar, icons=ICONS, robot=robot, role=role,
        logs=[dict(r) for r in rows]
    )


@pages_bp.route("/alertes")
def page_alertes():
    robot, robot_id, role, display_name, topbar = current_context()

    conn = get_db()
    rows = conn.execute("SELECT * FROM alerts WHERE robot_id=? ORDER BY id DESC LIMIT 30", (robot_id,)).fetchall()
    conn.close()

    return render_template(
        "alertes.html", topbar=topbar, icons=ICONS, robot=robot, role=role,
        alerts=[dict(r) for r in rows]
    )


@pages_bp.route("/comptes")
def page_comptes():
    robot, robot_id, role, display_name, topbar = current_context()

    conn = get_db()
    rows = conn.execute("""
        SELECT u.username, u.display_name, u.role FROM users u
        JOIN ownership o ON o.username = u.username
        WHERE o.robot_id = ? ORDER BY u.role DESC
    """, (robot_id,)).fetchall()
    conn.close()

    return render_template(
        "comptes.html", topbar=topbar, icons=ICONS, robot=robot,
        robot_users=[dict(r) for r in rows]
    )


@pages_bp.route("/stats")
def stats():
    username = session["user"]
    robot_id = request.args.get("robot_id") or session.get("current_robot_id")
    if not user_owns_robot(username, robot_id):
        return redirect("/dashboard")

    robot, _, role, display_name, topbar = current_context()
    conn = get_db()

    severity_rows = conn.execute(
        "SELECT severity, COUNT(*) as n FROM alerts WHERE robot_id=? GROUP BY severity", (robot_id,)
    ).fetchall()
    severity_map = {"critical": "Critique", "warning": "Avertissement", "info": "Info"}
    severity_labels = [severity_map.get(r["severity"], r["severity"]) for r in severity_rows]
    severity_values = [r["n"] for r in severity_rows]

    if role == "super_admin":
        user_rows = conn.execute(
            "SELECT by_user, COUNT(*) as n FROM logs WHERE robot_id=? GROUP BY by_user", (robot_id,)
        ).fetchall()
    else:
        user_rows = conn.execute(
            "SELECT by_user, COUNT(*) as n FROM logs WHERE robot_id=? AND by_user=? GROUP BY by_user",
            (robot_id, username)
        ).fetchall()
    user_labels = [r["by_user"] for r in user_rows]
    user_values = [r["n"] for r in user_rows]

    activity_rows = conn.execute("""
        SELECT substr(time,1,10) as jour, COUNT(*) as n FROM logs
        WHERE robot_id=? GROUP BY jour ORDER BY jour DESC LIMIT 7
    """, (robot_id,)).fetchall()
    conn.close()

    activity_labels = [r["jour"] for r in reversed(activity_rows)]
    activity_values = [r["n"] for r in reversed(activity_rows)]

    return render_template(
        "stats.html", topbar=topbar, icons=ICONS, robot=robot,
        severity_labels=severity_labels, severity_values=severity_values,
        user_labels=user_labels, user_values=user_values,
        activity_labels=activity_labels, activity_values=activity_values,
    )
