from flask import session
from app.database import get_db, get_robot
from app.utils.ui import topbar_html


def session_display_name(username):
    conn = get_db()
    row = conn.execute(
        "SELECT display_name FROM users WHERE username=?",
        (username,)
    ).fetchone()
    conn.close()
    return row["display_name"] if row else username


def current_context():
    username = session["user"]
    role = session["role"]
    robot_id = session.get("current_robot_id")
    robot = get_robot(robot_id)
    display_name = session_display_name(username)
    return robot, robot_id, role, display_name, topbar_html(display_name, role)
