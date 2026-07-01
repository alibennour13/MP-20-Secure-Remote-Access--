import sounddevice as sd
import numpy as np
import time
from faster_whisper import WhisperModel
from piper import PiperVoice

frequence = 16000

# ---- Écran de démarrage ----
print("=" * 45)
print("                A R I A")
print("     Robot d'accueil et securite")
print("       Fonctionnement HORS-LIGNE")
print("=" * 45)
print()

# ---- Chargement des briques, avec confirmation ----
print("Chargement des composants...")
print("   Reconnaissance vocale ...", end=" ", flush=True)
modele = WhisperModel("modele-whisper")
print("OK")
print("   Synthese vocale .........", end=" ", flush=True)
voix = PiperVoice.load("voix-piper/fr_FR-siwis-medium.onnx")
print("OK")
print()
print(">>> Mode hors-ligne actif : aucune connexion Internet requise <<<")
print()

# ---- Fonction pour faire parler ARIA ----
def parler(texte):
    for morceau in voix.synthesize(texte):
        donnees = np.frombuffer(morceau.audio_int16_bytes, dtype=np.int16)
        sd.play(donnees, samplerate=morceau.sample_rate)
        sd.wait()

# ---- Fonction pour écouter jusqu'à la touche Entrée ----
def ecouter():
    input("   [Entree] pour parler, [Entree] a nouveau pour arreter...")
    enregistrement = sd.rec(int(30 * frequence), samplerate=frequence, channels=1, dtype="float32")
    input()
    sd.stop()
    return np.squeeze(enregistrement)

# ---- Accueil vocal ----
print("=== ARIA est prete ! Dites 'au revoir' pour quitter. ===\n")
parler("Bonjour et bienvenue. Comment puis-je vous aider ?")

# ---- Boucle principale ----
while True:
    print("🎤  J'ecoute...")
    audio = ecouter()

    print("💭  Je reflechis...")
    debut = time.time()
    segments, info = modele.transcribe(audio, language="fr")
    texte = ""
    for segment in segments:
        texte = texte + segment.text
    texte = texte.strip()
    duree_calcul = time.time() - debut

    # Gestion des ratés : rien entendu ou phrase trop courte
    if len(texte) < 2:
        print("   (rien entendu de clair)")
        parler("Je n'ai pas bien entendu, pouvez-vous repeter ?")
        continue

    print("👤  Vous avez dit :", texte, "   (transcrit en", round(duree_calcul, 1), "s)")

    # Condition de sortie
    if "au revoir" in texte.lower():
        parler("Au revoir et a bientot !")
        print("\n=== ARIA s'arrete. ===")
        break

    # Pour l'instant ARIA répète (le cerveau viendra en Semaine 3)
    print("🔊  Je reponds...")
    parler("Vous avez dit : " + texte)
    print()