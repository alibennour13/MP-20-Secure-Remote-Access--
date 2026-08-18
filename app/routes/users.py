from flask import Blueprint, jsonify, request, session
from werkzeug.security import generate_password_hash
from app.auth import login_required, role_required
from app.database import get_db, add_log, user_owns_robot
from app.utils.access import robot_access_required

users_bp = Blueprint("users", __name__, url_prefix="/api/users")


@users_bp.post("/create")
def create_technician():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    display_name = (data.get("display_name") or username).strip()

    if not username or not password:
        return jsonify({"success": False, "message": "Renseignez un identifiant et un mot de passe."}), 400
    if len(password) < 6:
        return jsonify({"success": False, "message": "Le mot de passe doit faire au moins 6 caracteres."}), 400
    if not username.replace("_", "").isalnum():
        return jsonify({"success": False, "message": "Identifiant invalide (lettres, chiffres et underscore uniquement)."}), 400

    conn = get_db()
    existing = conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone()
    if existing:
        conn.close()
        return jsonify({"success": False, "message": "Cet identifiant est deja pris."}), 409

    # Un compte cree depuis cette interface est TOUJOURS un technicien,
    # jamais un autre super_admin (evite l'auto-elevation de privileges).
    conn.execute(
        "INSERT INTO users (username,password_hash,role,display_name) VALUES (?,?,?,?)",
        (username, generate_password_hash(password), "technicien", display_name)
    )
    conn.execute("INSERT INTO ownership VALUES (?,?)", (username, request.robot_id))
    conn.commit()
    conn.close()

    add_log(request.robot_id, f"Compte technicien cree : {username}", session["user"])
    return jsonify({"success": True, "message": f"Compte {username} cree"})


@users_bp.post("/delete")
def delete_technician():
    data = request.get_json(silent=True) or {}
    username = data.get("username")

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not user:
        conn.close()
        return jsonify({"success": False, "message": "Compte introuvable."}), 404
    if user["role"] != "technicien":
        conn.close()
        return jsonify({"success": False, "message": "Un compte super admin ne peut pas etre supprime ici."}), 403
    if not user_owns_robot(username, request.robot_id):
        conn.close()
        return jsonify({"success": False, "message": "Ce technicien n'est pas rattache a ce robot."}), 403

    conn.execute("DELETE FROM users WHERE username=?", (username,))  # cascade supprime aussi ownership
    conn.commit()
    conn.close()

    add_log(request.robot_id, f"Compte technicien supprime : {username}", session["user"])
    return jsonify({"success": True, "message": f"Acces de {username} retire"})
