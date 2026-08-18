from flask import Blueprint, jsonify, request, session
from app.auth import login_required, role_required
from app.database import get_db, add_log
from app.utils.access import robot_access_required

settings_bp = Blueprint("settings", __name__, url_prefix="/api")


@settings_bp.post("/volume")
def update_volume():
    data = request.get_json(silent=True) or {}
    try:
        volume = int(data.get("volume"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Volume invalide."}), 400
    if not (0 <= volume <= 100):
        return jsonify({"success": False, "message": "Le volume doit etre compris entre 0 et 100."}), 400

    conn = get_db()
    conn.execute("UPDATE robots SET volume=? WHERE id=?", (volume, request.robot_id))
    conn.commit()
    conn.close()
    add_log(request.robot_id, f"Volume regle sur {volume}%", session["user"])
    return jsonify({"success": True, "message": f"Volume regle sur {volume}%"})


@settings_bp.post("/language")
def update_language():
    data = request.get_json(silent=True) or {}
    language = data.get("language")
    if language not in ("Français", "English", "العربية"):
        return jsonify({"success": False, "message": "Langue non autorisee."}), 400

    conn = get_db()
    conn.execute("UPDATE robots SET language=? WHERE id=?", (language, request.robot_id))
    conn.commit()
    conn.close()
    add_log(request.robot_id, f"Langue changee : {language}", session["user"])
    return jsonify({"success": True, "message": f"Langue reglee sur {language}"})


@settings_bp.post("/voice")
def update_voice():
    data = request.get_json(silent=True) or {}
    voice = data.get("voice")
    if voice not in ("Female", "Male"):
        return jsonify({"success": False, "message": "Voix non autorisee."}), 400

    conn = get_db()
    conn.execute("UPDATE robots SET voice=? WHERE id=?", (voice, request.robot_id))
    conn.commit()
    conn.close()
    add_log(request.robot_id, f"Voix changee : {voice}", session["user"])
    return jsonify({"success": True, "message": "Timbre de voix mis a jour"})


@settings_bp.post("/speed")
def update_speed():
    data = request.get_json(silent=True) or {}
    try:
        speed = float(data.get("speed"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Vitesse invalide."}), 400
    if not (0.5 <= speed <= 2.0):
        return jsonify({"success": False, "message": "Vitesse hors limites (0.5 a 2.0)."}), 400

    conn = get_db()
    conn.execute("UPDATE robots SET speed=? WHERE id=?", (speed, request.robot_id))
    conn.commit()
    conn.close()
    add_log(request.robot_id, f"Vitesse de parole : {speed}x", session["user"])
    return jsonify({"success": True, "message": f"Debit de parole regle sur {speed}x"})
