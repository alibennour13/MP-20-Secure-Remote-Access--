"""
alert_watcher.py
==================
Ce script tourne EN PARALLELE du dashboard, directement sur le robot,
comme un service systemd separe. Son role : surveiller le robot en
continu et ecrire une alerte dans la base de donnees du dashboard des
qu'une anomalie est detectee (batterie faible, obstacle, etc.).

C'est le sens INVERSE des autres fichiers : robot_controller.py fait
"dashboard -> robot" (le client commande le robot), alert_watcher.py
fait "robot -> dashboard" (le robot informe le client).

MODE SIMULATION :
Sans acces aux vrais capteurs, ce script genere periodiquement une
alerte aleatoire pour que le systeme reste demontrable des maintenant.
Une fois les capteurs reels identifies avec l'encadrant, remplacez
uniquement la fonction lire_etat_robot() -- tout le reste (ecriture
en base, evitement des doublons) ne change pas.

Lancer en tache de fond :
    python3 alert_watcher.py

Ou en service systemd (recommande sur le vrai robot) :
    voir le commentaire en bas de fichier pour le fichier .service
"""

import sqlite3
import time
import os
import random
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("alert_watcher")

DB_PATH = os.environ.get("ROBOT_DB_PATH", "robot_dashboard.db")
ROBOT_ID = os.environ.get("ROBOT_ID", "robot-alpha")
INTERVALLE_SECONDES = 15

REAL_MODE = os.environ.get("ROBOT_REAL_MODE") == "1"

# Seuils qui declenchent une alerte -- a ajuster selon le vrai robot
SEUIL_BATTERIE_CRITIQUE = 15
SEUIL_BATTERIE_FAIBLE = 30

# Evite de spammer la meme alerte en boucle : on retient le dernier
# type d'alerte envoye et on n'en renvoie pas une identique tant que
# la situation n'a pas change.
_dernier_type_envoye = None


def add_alert(robot_id, type_, severity, message):
    """Ecrit directement dans la meme base SQLite que le dashboard --
    aucune dependance a Flask, ce script peut tourner completement
    independamment du serveur web."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO alerts (robot_id,time,type,severity,message,acknowledged) VALUES (?,?,?,?,?,0)",
        (robot_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), type_, severity, message)
    )
    conn.commit()
    conn.close()
    logger.info(f"Alerte enregistree : [{severity}] {message}")


def lire_etat_robot():
    """Retourne un dict decrivant l'etat courant du robot. C'EST LA
    SEULE FONCTION A REMPLACER une fois les vrais capteurs identifies.

    Exemple d'implementation reelle avec ROS2 (a adapter) :

        import rclpy
        from sensor_msgs.msg import BatteryState
        # ... souscrire au topic /battery_state et retourner sa derniere valeur

    Exemple avec un fichier sysfs direct (Jetson) :

        with open("/sys/class/power_supply/BAT0/capacity") as f:
            batterie = int(f.read().strip())
        return {"batterie": batterie, "obstacle_detecte": False}
    """
    if not REAL_MODE:
        # Simulation : genere des valeurs plausibles pour la demo
        return {
            "batterie": random.randint(10, 100),
            "obstacle_detecte": random.random() < 0.1,   # 10% de chance
            "mouvement_inhabituel": random.random() < 0.1,
        }

    # TODO INTEGRATION -- remplacer par la vraie lecture capteur
    raise NotImplementedError(
        "lire_etat_robot() doit etre implementee avec les vrais capteurs du robot."
    )


def verifier_anomalies():
    """Analyse l'etat courant et declenche une alerte si necessaire.
    Appelee en boucle par la fonction principale."""
    global _dernier_type_envoye

    etat = lire_etat_robot()
    type_alerte_actuelle = None

    if etat["batterie"] <= SEUIL_BATTERIE_CRITIQUE:
        type_alerte_actuelle = "batterie_critique"
        if _dernier_type_envoye != type_alerte_actuelle:
            add_alert(ROBOT_ID, "batterie", "critical",
                      f"Niveau de batterie critique : {etat['batterie']}%")

    elif etat["batterie"] <= SEUIL_BATTERIE_FAIBLE:
        type_alerte_actuelle = "batterie_faible"
        if _dernier_type_envoye != type_alerte_actuelle:
            add_alert(ROBOT_ID, "batterie", "warning",
                      f"Niveau de batterie faible : {etat['batterie']}%")

    if etat.get("obstacle_detecte"):
        add_alert(ROBOT_ID, "obstacle", "critical", "Collision ou obstacle inattendu detecte")

    if etat.get("mouvement_inhabituel"):
        add_alert(ROBOT_ID, "mouvement", "warning", "Mouvement detecte en dehors des heures de patrouille")

    _dernier_type_envoye = type_alerte_actuelle


def main():
    logger.info(f"Surveillance demarree pour {ROBOT_ID} (mode {'REEL' if REAL_MODE else 'SIMULATION'})")
    while True:
        try:
            verifier_anomalies()
        except Exception as e:
            logger.error(f"Erreur pendant la verification : {e}")
        time.sleep(INTERVALLE_SECONDES)


if __name__ == "__main__":
    main()


