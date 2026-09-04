"""
robot_controller.py
====================
Couche d'integration entre le dashboard client (Flask) et le systeme
reel du robot (Ubuntu / Jetson). Ce module isole TOUTES les commandes
systeme et les appels materiel en un seul endroit : le reste du
dashboard ne connait jamais les details d'implementation, il appelle
juste des fonctions comme restart_robot() ou set_volume(50).

MODE SIMULATION AUTOMATIQUE :
Tant que la variable d'environnement ROBOT_REAL_MODE n'est pas mise a
"1", toutes les fonctions se contentent d'afficher ce qu'elles
AURAIENT fait, sans toucher au vrai systeme. Ca permet de developper
et de tester le dashboard sur n'importe quelle machine (VM de dev,
PC) sans risque, et de basculer en mode reel d'un seul coup une fois
deploye sur le robot :

    export ROBOT_REAL_MODE=1

PARTIES A COMPLETER UNE FOIS LES INFOS DE L'ENCADRANT CONNUES :
Cherchez les blocs marques "# TODO INTEGRATION" -- ce sont les seuls
endroits a modifier selon que le robot tourne sous ROS/ROS2, une API
REST maison, ou un simple script Python. Tout le reste (validation,
logging, gestion des roles) ne change jamais.
"""

import os
import subprocess
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("robot_controller")

REAL_MODE = os.environ.get("ROBOT_REAL_MODE") == "1"


class RobotControllerError(Exception):
    """Levee quand une action reelle sur le robot echoue -- permet au
    dashboard de distinguer une erreur materielle d'un succes, plutot
    que de supposer que tout a fonctionne."""
    pass


def _run_or_simulate(description, commande):
    """Execute une vraie commande systeme en mode reel, ou se contente
    de logger ce qui aurait ete execute en mode simulation. Centralise
    la gestion d'erreur pour toutes les commandes systeme du fichier."""
    if not REAL_MODE:
        logger.info(f"[SIMULATION] {description} -> {' '.join(commande)}")
        return True

    try:
        resultat = subprocess.run(commande, capture_output=True, text=True, timeout=10)
        if resultat.returncode != 0:
            logger.error(f"{description} a echoue : {resultat.stderr.strip()}")
            raise RobotControllerError(f"{description} a echoue : {resultat.stderr.strip()}")
        logger.info(f"{description} : OK")
        return True
    except subprocess.TimeoutExpired:
        raise RobotControllerError(f"{description} : delai depasse (robot ne repond pas)")
    except FileNotFoundError:
        raise RobotControllerError(f"{description} : commande introuvable sur ce systeme")


# ============================================================
# CONTROLE DU ROBOT - demarrage / arret
# ============================================================
# Ces deux fonctions sont deja "reelles" et ne dependent d'aucune
# information supplementaire de l'encadrant : ce sont des commandes
# systeme Linux standards, valables sur n'importe quel Ubuntu/Jetson.
#
# PREREQUIS COTE ROBOT (a faire une seule fois par l'encadrant ou toi,
# une fois l'acces SSH disponible) :
#
#   sudo adduser --system --no-create-home robotapp
#   sudo visudo -f /etc/sudoers.d/40-robotapp
#   -> contenu du fichier :
#      robotapp ALL=(root) NOPASSWD: /usr/sbin/reboot, /usr/sbin/shutdown
#
# Le dashboard doit alors tourner sous l'utilisateur "robotapp",
# jamais en root, exactement comme le principe RBAC deja applique
# cote infrastructure MP-20.
# ============================================================

def restart_robot():
    return _run_or_simulate("Redemarrage du robot", ["sudo", "/usr/sbin/reboot"])


def shutdown_robot():
    return _run_or_simulate("Extinction du robot", ["sudo", "/usr/sbin/shutdown", "now"])


# ============================================================
# VOLUME - deja reel via ALSA, standard sur Ubuntu/Jetson
# ============================================================

def set_volume(pourcentage: int):
    if not (0 <= pourcentage <= 100):
        raise ValueError("Le volume doit etre entre 0 et 100.")
    return _run_or_simulate(
        f"Reglage du volume a {pourcentage}%",
        ["amixer", "set", "Master", f"{pourcentage}%"]
    )


# ============================================================
# LANGUE / VOIX / VITESSE - EN ATTENTE DES INFOS DE L'ENCADRANT
# ============================================================
# Ces trois fonctions dependent du logiciel de controle propre au
# robot (ROS, API REST maison, ou autre). Les blocs ci-dessous
# proposent 3 implementations alternatives commentees -- decommentez
# celle qui correspond a la reponse de l'encadrant, et effacez les
# deux autres.

def set_language(langue: str):
    langues_autorisees = ("Français", "English", "العربية")
    if langue not in langues_autorisees:
        raise ValueError(f"Langue non autorisee : {langue}")

    if not REAL_MODE:
        logger.info(f"[SIMULATION] Changement de langue -> {langue}")
        return True

    # TODO INTEGRATION -- decommenter UNE des 3 options selon la reponse
    # de l'encadrant, une fois connue.

    # --- Option A : le robot tourne sous ROS2 ---
    # import rclpy
    # from std_msgs.msg import String
    # ... publier sur le topic /robot/set_language avec la valeur `langue`

    # --- Option B : le robot expose une API REST locale ---
    # import requests
    # reponse = requests.post("http://127.0.0.1:8080/api/config/language",
    #                          json={"language": langue}, timeout=3)
    # reponse.raise_for_status()

    # --- Option C : le robot lit un fichier de config et se recharge ---
    # import json
    # with open("/etc/robot/config.json", "r+") as f:
    #     config = json.load(f)
    #     config["language"] = langue
    #     f.seek(0); json.dump(config, f, indent=2); f.truncate()
    # subprocess.run(["sudo", "systemctl", "reload", "robot-control.service"])

    raise RobotControllerError(
        "set_language() n'est pas encore branchee au logiciel du robot. "
        "Voir les commentaires TODO INTEGRATION dans robot_controller.py."
    )


def set_voice(voix: str):
    if voix not in ("Female", "Male"):
        raise ValueError(f"Voix non autorisee : {voix}")

    if not REAL_MODE:
        logger.info(f"[SIMULATION] Changement de voix -> {voix}")
        return True

    # TODO INTEGRATION -- meme principe que set_language() ci-dessus.
    raise RobotControllerError(
        "set_voice() n'est pas encore branchee au logiciel du robot."
    )


def set_speed(vitesse: float):
    if not (0.5 <= vitesse <= 2.0):
        raise ValueError("Vitesse hors limites (0.5 a 2.0).")

    if not REAL_MODE:
        logger.info(f"[SIMULATION] Changement de vitesse de parole -> {vitesse}x")
        return True

    # TODO INTEGRATION -- meme principe que set_language() ci-dessus.
    raise RobotControllerError(
        "set_speed() n'est pas encore branchee au logiciel du robot."
    )


# ============================================================
# STATUT DU ROBOT (batterie, etat) - a completer aussi
# ============================================================

def get_battery_level():
    """Tente de lire un niveau de batterie reel si disponible (chemin
    standard sur beaucoup de cartes embarquees), sinon retourne None
    -- le dashboard doit alors garder la derniere valeur connue en
    base plutot que d'afficher une fausse donnee."""
    chemin_batterie = "/sys/class/power_supply/BAT0/capacity"

    if not REAL_MODE:
        return None  # le dashboard garde la valeur simulee en base

    try:
        with open(chemin_batterie, "r") as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        logger.warning("Impossible de lire le niveau de batterie reel.")
        return None