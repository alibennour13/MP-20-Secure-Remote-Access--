from flask import Flask
from .config import Config
from .database import init_db
from .routes.auth import auth_bp
from .routes.pages import pages_bp
from .routes.robot import robot_bp
from .routes.settings import settings_bp
from .routes.users import users_bp
from .routes.alerts import alerts_bp
from .routes.exports import exports_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    app.register_blueprint(auth_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(robot_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(exports_bp)

    with app.app_context():
        init_db()

    return app
