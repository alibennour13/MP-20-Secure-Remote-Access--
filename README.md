# MP-20 : Secure Remote Access

Architecture de sécurisation de l'accès distant à un robot de sécurité, avec un dashboard web dédié au client final.

Projet de fin d'études en génie mécatronique, TEK-UP University.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Flask](https://img.shields.io/badge/Flask-3.x-lightgrey)
![WireGuard](https://img.shields.io/badge/VPN-WireGuard-88171a)
![Platform](https://img.shields.io/badge/Platform-Ubuntu%20%2F%20Jetson%20Orin%20Nano-76b900)

---

## Sommaire

- [Contexte](#contexte)
- [Vue d'ensemble](#vue-densemble)
- [Volet 1 : Infrastructure fournisseur](#volet-1--infrastructure-fournisseur)
- [Volet 2 : Dashboard client](#volet-2--dashboard-client)
- [Intégration au robot](#intégration-au-robot)
- [Structure du dépôt](#structure-du-dépôt)
- [Installation](#installation)
- [Déploiement en production](#déploiement-en-production)
- [Sécurité](#sécurité)
- [Limites connues](#limites-connues)
- [Feuille de route](#feuille-de-route)
- [Auteur](#auteur)

---

## Contexte

Le robot de sécurité est un système autonome de patrouille et de surveillance, fabriqué en laboratoire et fonctionnant sous Ubuntu sur une carte NVIDIA Jetson Orin Nano. Pour être exploité et maintenu, il doit pouvoir être administré à distance. Une interface d'administration exposée sans protection est une surface d'attaque critique : toute personne présente sur le réseau pourrait tenter de reconfigurer le robot ou de désactiver ses fonctions de sécurité.

Le projet répond à ce besoin avec deux volets strictement séparés, correspondant aux deux acteurs de la commercialisation du robot :

| Acteur | Rôle | Périmètre |
|---|---|---|
| **Fournisseur** (laboratoire) | `admin` | Administration technique complète du système |
| **Client** (acheteur du robot) | `super admin` | Pilotage fonctionnel uniquement (langue, voix, volume, alertes) |

Le client n'a jamais accès au système Linux sous-jacent, ni au VPN, ni à SSH.

## Vue d'ensemble

```
Fournisseur ──► WireGuard ──► SSH + RADIUS + TOTP ──► sudoers (RBAC) ──► Wazuh / Fail2Ban
                                       │
                                  Robot (Jetson / Ubuntu)
                                       │
Client ──► HTTPS ──► Nginx ──► Gunicorn ──► Dashboard Flask ──► robot_controller.py
```

Les deux chemins d'accès ne se croisent jamais : un compte client, quel que soit son niveau de permission dans le dashboard, ne peut pas atteindre l'infrastructure du fournisseur.

---

## Volet 1 : Infrastructure fournisseur

Architecture en cinq couches indépendantes.

| Couche | Rôle | Composants |
|---|---|---|
| **L1 Périmètre** | Refus par défaut de tout trafic entrant | ufw / nftables |
| **L2 Tunnel chiffré** | Seul chemin d'administration possible | WireGuard, SSH lié à `wg0` |
| **L3 Authentification** | Deux facteurs obligatoires | FreeRADIUS, PAM, TOTP |
| **L4 Autorisation** | Permissions par rôle | sudoers (technicien, administrateur, superviseur) |
| **L5 Traçabilité** | Journalisation et réaction | auditd, journald, Fail2Ban, Wazuh |

### Principes directeurs

- **Défense en profondeur** : compromettre une couche ne donne jamais accès à la suivante.
- **Default deny** : tout est refusé par défaut, l'accès est une exception explicite.
- **Application par construction** : les règles critiques sont rendues techniquement impossibles à contourner (par exemple SSH n'écoute que sur l'interface du tunnel).

### Exigences et validation

Chaque exigence du cahier des charges a été validée par deux tests : le chemin autorisé fonctionne, le chemin refusé échoue explicitement.

| Exigence | Élément | Preuve de validation |
|---|---|---|
| FR1 | Tunnel WireGuard | `wg show` : handshake récent et trafic transféré |
| FR2 | FreeRADIUS via PAM | Connexion refusée quand RADIUS est arrêté |
| FR3 | TOTP | Connexion refusée avec un code invalide |
| FR4, FR5 | Groupes et fichiers sudoers | `visudo -c` : tous les fichiers valides |
| FR6 | auditd et journald | Commande sudo retrouvée avec horodatage |
| FR7 | Fail2Ban | IP bannie après 5 échecs, chaîne `f2b-sshd` dans nftables |
| FR8 | Wazuh | Événements classés selon MITRE ATT&CK |
| NFR1 | ufw et `ListenAddress` | SSH hors tunnel : connexion refusée |
| NFR6 | Git | Aucun secret dans l'historique |

---

## Volet 2 : Dashboard client

Application web Flask, indépendante de l'infrastructure fournisseur. Aucun accès système depuis l'interface : les actions passent par un module d'intégration dédié (`robot_controller.py`).

### Interface

Page d'accueil en tuiles cliquables (thème sombre), avec une page dédiée par fonction :

| Tuile | Fonction |
|---|---|
| Redémarrer / Éteindre | Actions directes sur le robot |
| Alertes | Anomalies détectées, trois niveaux de gravité |
| Journal | Historique d'activité, export CSV |
| Statistiques | Graphiques (alertes, activité par utilisateur, tendance sur 7 jours) |
| Langue | Français, English, العربية |
| Audio et Voix | Volume, voix, vitesse d'élocution |
| Comptes | Création et suppression des techniciens |

### Rôles applicatifs

| Fonction | Technicien | Super admin |
|---|---|---|
| Redémarrer / éteindre le robot | Oui | Oui |
| Voir et acquitter les alertes | Oui | Oui |
| Journal d'activité | Ses propres actions uniquement | Historique complet |
| Langue, voix, volume, vitesse | Non | Oui |
| Gérer les comptes techniciens | Non | Oui |
| Effacer l'historique des alertes | Non | Oui |

### Choix de sécurité

- Restrictions appliquées **côté serveur** (réponse 403), pas seulement par masquage de l'interface.
- Isolation par robot vérifiée à chaque requête (protection contre les accès directs par identifiant).
- Un compte créé depuis le dashboard est toujours un technicien : pas d'élévation de privilèges possible.
- Mots de passe hashés (Werkzeug), base SQLite dédiée.
- Validation stricte des entrées (bornes du volume et de la vitesse, longueur des mots de passe, format des identifiants).

---

## Intégration au robot

Trois fichiers à déployer ensemble.

| Fichier | Rôle |
|---|---|
| `dashboard_tiles.py` | Application web (pages, comptes, permissions) |
| `robot_controller.py` | Module importé par le dashboard : traduit les actions en commandes système |
| `alert_watcher.py` | Service séparé qui écrit les anomalies du robot dans la base du dashboard |

### Mode simulation et mode réel

Par défaut, `robot_controller.py` fonctionne en **simulation** : il journalise ce qu'il ferait sans toucher au système. Le mode réel s'active avec une variable d'environnement :

```bash
export ROBOT_REAL_MODE=1
```

### État de l'intégration

| Fonction | État |
|---|---|
| Redémarrage, extinction | Réel (commandes Linux standard) |
| Volume | Réel (ALSA) |
| Langue, voix, vitesse | En attente du logiciel de contrôle du robot (ROS2, API REST ou fichier de configuration) |
| Alertes | Simulation en place, lecture des capteurs réels à brancher |

---

## Structure du dépôt

```
mp20-secure-remote-access/
├── wireguard/           Tunnel VPN (exemples anonymisés)
├── freeradius/          Authentification centralisée
├── pam/                 Intégration RADIUS et TOTP dans SSH
├── sudoers.d/           Politiques RBAC par rôle
├── fail2ban/            Blocage automatique
├── wazuh/rules/         Règles de détection personnalisées
├── client-dashboard/
│   ├── dashboard_tiles.py
│   ├── robot_controller.py
│   ├── alert_watcher.py
│   └── requirements.txt
└── docs/                Rapport, procédures, guide de démonstration
```

Les fichiers de configuration contenant des secrets (clés privées, mots de passe) sont exclus par `.gitignore`. Seules des versions d'exemple anonymisées (`*.example`) sont versionnées.

---

## Installation

### Infrastructure fournisseur

L'installation pas à pas (WireGuard, FreeRADIUS, PAM, RBAC, Fail2Ban, Wazuh) est décrite dans `docs/`.
Prérequis : Ubuntu Server 22.04 LTS ou équivalent.

### Dashboard client (développement)

```bash
cd client-dashboard
pip install flask
python3 dashboard_tiles.py
```

L'application est accessible sur `http://127.0.0.1:5000`. La base de données et un compte de démonstration sont créés au premier lancement : **changez ces identifiants avant toute mise en ligne**.

---

## Déploiement en production

Le dashboard client est destiné à être servi comme un site web classique, sans passer par le tunnel d'administration.

```
Navigateur ──► HTTPS (443) ──► Nginx ──► Gunicorn ──► Flask
```

1. Créer un utilisateur système sans privilèges (`robotapp`) : le dashboard ne tourne jamais en root.
2. Limiter ses droits à `reboot` et `shutdown` dans un fichier `/etc/sudoers.d/` dédié.
3. Lancer Gunicorn comme service systemd, derrière Nginx avec un certificat Let's Encrypt.
4. Définir `ROBOT_REAL_MODE=1` dans le service sur le robot réel.
5. Lancer `alert_watcher.py` comme second service systemd.
6. N'ouvrir que les ports 80 et 443 pour le dashboard. SSH reste réservé à l'administration du fournisseur, via WireGuard.

---

## Sécurité

- Aucun secret n'est présent dans l'historique Git (vérifié par recherche sur l'historique complet).
- Les deux applications (administration technique et dashboard client) ne communiquent jamais entre elles.
- Chaque contrôle est redondant par construction : la défaillance d'un mécanisme ne compromet pas l'ensemble.
- Toutes les clés et tous les mots de passe de test doivent être régénérés avant la mise en production.

Pour signaler une vulnérabilité, ouvrir une issue sur ce dépôt.

## Limites connues

- Le test de refus RBAC (technicien tentant une action hors périmètre) reste à finaliser avec un compte entièrement dédié, distinct du compte d'administration du projet.
- Le délai d'attente de `pam_radius_auth` a dû être porté à 30 secondes sur la machine de test, dont les ressources sont limitées.
- Sur la machine de test, l'interface `wg0` peut perdre son adresse après une longue pause, ce qui empêche SSH de démarrer. Un ordre de démarrage systemd explicite (SSH après WireGuard) est la correction prévue.
- La règle de corrélation Wazuh personnalisée est écrite mais son déclenchement n'est pas confirmé.
- Les commandes de langue, voix et vitesse dépendent du logiciel de contrôle du robot et ne sont pas encore branchées.

## Feuille de route

- [ ] Brancher langue, voix et vitesse sur le logiciel de contrôle du robot
- [ ] Remplacer la simulation de `alert_watcher.py` par la lecture des capteurs réels
- [ ] Installer l'infrastructure MP-20 et le dashboard sur la Jetson Orin Nano
- [ ] Déployer le dashboard derrière Nginx avec HTTPS
- [ ] Dashboard technique pour le fournisseur (vue consolidée Wazuh et état des services)
- [ ] Valider le refus RBAC avec des comptes dédiés

## Auteur

**Ali Bennour**, ingénierie mécatronique (ING-3), TEK-UP University
