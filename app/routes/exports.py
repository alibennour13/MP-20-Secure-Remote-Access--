import csv
import io
from flask import Blueprint, Response, jsonify, request, session
from app.auth import login_required
from app.database import get_db, user_owns_robot

exports_bp = Blueprint("exports", __name__, url_prefix="/api/export")


@exports_bp.get("/logs")
def export_logs():
    username = session["user"]
    robot_id = request.args.get("robot_id")
    if not robot_id or not user_owns_robot(username, robot_id):
        return jsonify({"success": False, "message": "Acces refuse."}), 403

    conn = get_db()
    if session["role"] == "super_admin":
        rows = conn.execute("SELECT time,event,by_user FROM logs WHERE robot_id=? ORDER BY id", (robot_id,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT time,event,by_user FROM logs WHERE robot_id=? AND by_user=? ORDER BY id",
            (robot_id, username)
        ).fetchall()
    conn.close()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Date/heure", "Evenement", "Utilisateur"])
    for r in rows:
        writer.writerow([r["time"], r["event"], r["by_user"]])

    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=journal_{robot_id}.csv"}
    )


@exports_bp.get("/alerts")
def export_alerts():
    username = session["user"]
    robot_id = request.args.get("robot_id")
    if not robot_id or not user_owns_robot(username, robot_id):
        return jsonify({"success": False, "message": "Acces refuse."}), 403

    conn = get_db()
    rows = conn.execute(
        "SELECT time,type,severity,message,acknowledged FROM alerts WHERE robot_id=? ORDER BY id", (robot_id,)
    ).fetchall()
    conn.close()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Date/heure", "Type", "Gravite", "Message", "Lue"])
    for r in rows:
        writer.writerow([r["time"], r["type"], r["severity"], r["message"], "Oui" if r["acknowledged"] else "Non"])

    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=alertes_{robot_id}.csv"}
    )
