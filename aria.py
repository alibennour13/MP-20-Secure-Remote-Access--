import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel
from piper import PiperVoice

# ---- Chargement des briques (une seule fois au démarrage) ----
print("Démarrage d'ARIA, veuillez patienter...")
modele = WhisperModel("modele-whisper")
voix = PiperVoice.load("voix-piper/fr_FR-siwis-medium.onnx")

frequence = 16000

# ---- Petite fonction pour faire parler ARIA ----
def parler(texte):
    for morceau in voix.synthesize(texte):
        donnees = np.frombuffer(morceau.audio_int16_bytes, dtype=np.int16)
        sd.play(donnees, samplerate=morceau.sample_rate)
        sd.wait()

# ---- Petite fonction pour écouter jusqu'à ce qu'on appuie sur Entrée ----
def ecouter():
    input("   Appuyez sur Entrée, parlez, puis appuyez encore sur Entrée pour arrêter...")
    enregistrement = sd.rec(int(30 * frequence), samplerate=frequence, channels=1, dtype="float32")
    input()  # on attend le deuxième Entrée
    sd.stop()
    return np.squeeze(enregistrement)

# ---- Message d'accueil ----
print("\n=== ARIA est prête ! Dites 'au revoir' pour quitter. ===\n")
parler("Bonjour et bienvenue. Comment puis-je vous aider ?")

# ---- Boucle principale ----
while True:
    print("🎤  J'écoute...")
    audio = ecouter()

    print("💭  Je réfléchis...")
    segments, info = modele.transcribe(audio, language="fr")
    texte = ""
    for segment in segments:
        texte = texte + segment.text
    texte = texte.strip()

    # Gestion du silence : rien entendu
    if texte == "":
        print("   (rien entendu)")
        parler("Je n'ai rien entendu, pouvez-vous répéter ?")
        continue

    print("👤  Vous avez dit :", texte)

    # Condition de sortie
    if "au revoir" in texte.lower():
        parler("Au revoir et à bientôt !")
        print("\n=== ARIA s'arrête. ===")
        break

    # Pour l'instant, ARIA répète (le cerveau viendra ensuite)
    print("🔊  Je réponds...")
    parler("Vous avez dit : " + texte)