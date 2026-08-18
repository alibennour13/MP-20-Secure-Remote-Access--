from flask import Blueprint, jsonify, request, session
from app.auth import login_required
from app.database import get_db, add_log
from app.utils.access import robot_access_required

robot_bp = Blueprint("robot", __name__, url_prefix="/api/robot")


@robot_bp.post("/restart")
def robot_restart():
    conn = get_db()
    conn.execute("UPDATE robots SET status='Online' WHERE id=?", (request.robot_id,))
    conn.commit()
    conn.close()
    add_log(request.robot_id, "Robot redemarre", session["user"])
    return jsonify({"success": True, "message": "Robot redemarre"})


@robot_bp.post("/shutdown")
def robot_shutdown():
    conn = get_db()
    conn.execute("UPDATE robots SET status='Offline' WHERE id=?", (request.robot_id,))
    conn.commit()
    conn.close()
    add_log(request.robot_id, "Robot eteint", session["user"])
    return jsonify({"success": True, "message": "Robot eteint"})
