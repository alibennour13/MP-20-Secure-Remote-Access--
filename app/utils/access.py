from functools import wraps
from flask import jsonify, request, session
from app.database import user_owns_robot


def robot_access_required(function):
    """A poser APRES login_required sur toute route qui recoit un
    robot_id (query param ou JSON) : verifie l'appartenance avant
    de laisser la route s'executer."""
    @wraps(function)
    def wrapper(*args, **kwargs):
        robot_id = request.args.get("robot_id") or session.get("current_robot_id")
        if request.is_json:
            robot_id = (request.get_json(silent=True) or {}).get("robot_id", robot_id)
        if not robot_id or not user_owns_robot(session["user"], robot_id):
            return jsonify({"success": False, "message": "Robot introuvable ou acces refuse."}), 403
        request.robot_id = robot_id
        return function(*args, **kwargs)
    return wrapper
