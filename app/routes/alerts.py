import random
from flask import Blueprint, jsonify, request, session
from app.auth import login_required, role_required
from app.database import get_db, add_alert, add_log
from app.utils.access import robot_access_required

alerts_bp = Blueprint("alerts", __name__, url_prefix="/api/alerts")

EXEMPLES_ANOMALIES = [
    ("mouvement", "warning", "Mouvement detecte en dehors des heures de patrouille"),
    ("batterie", "critical", "Chute brutale du niveau de batterie"),
    ("connexion", "info", "Connexion depuis une nouvelle adresse reseau"),
    ("temperature", "warning", "Temperature interne superieure a la normale"),
    ("obstacle", "critical", "Collision ou obstacle inattendu detecte"),
]


@alerts_bp.post("/acknowledge")
def acknowledge_alert():
    data = request.get_json(silent=True) or {}
    alert_id = data.get("alert_id")

    conn = get_db()
    alert = conn.execute(
        "SELECT * FROM alerts WHERE id=? AND robot_id=?", (alert_id, request.robot_id)
    ).fetchone()
    if not alert:
        conn.close()
        return jsonify({"success": False, "message": "Alerte introuvable."}), 404

    conn.execute("UPDATE alerts SET acknowledged=1 WHERE id=?", (alert_id,))
    conn.commit()
    conn.close()
    add_log(request.robot_id, f"Alerte #{alert_id} marquee comme lue", session["user"])
    return jsonify({"success": True, "message": "Alerte marquee comme lue"})


@alerts_bp.post("/simulate")
def simulate_alert():
    """Route de DEMONSTRATION : declenche une fausse anomalie. Sur le
    vrai robot, ce sont les capteurs qui appellent add_alert() directement."""
    import random
    type_, severity, message = random.choice(EXEMPLES_ANOMALIES)
    add_alert(request.robot_id, type_, severity, message)
    add_log(request.robot_id, f"Anomalie simulee : {message}", session["user"])
    return jsonify({"success": True, "message": "Anomalie simulee ajoutee"})


@alerts_bp.post("/clear")
def clear_alerts():
    conn = get_db()
    conn.execute("DELETE FROM alerts WHERE robot_id=?", (request.robot_id,))
    conn.commit()
    conn.close()
    add_log(request.robot_id, "Historique des alertes efface", session["user"])
    return jsonify({"success": True, "message": "Historique des alertes efface"})
