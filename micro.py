import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel

# On charge le modèle depuis le dossier local (déjà téléchargé)
modele = WhisperModel("modele-whisper")

# Réglages de l'enregistrement
duree = 5           # durée d'écoute en secondes
frequence = 16000   # qualité audio attendue par Whisper (16 kHz)

print("Parlez maintenant... (vous avez", duree, "secondes)")

# On enregistre le son du micro
audio = sd.rec(int(duree * frequence), samplerate=frequence, channels=1, dtype="float32")
sd.wait()   # on attend la fin de l'enregistrement

print("Enregistrement terminé. Analyse en cours...")

# Whisper attend un tableau audio "à plat"
audio = np.squeeze(audio)

# On transcrit directement l'audio du micro
segments, info = modele.transcribe(audio, language="fr")

print("Texte reconnu :")
for segment in segments:
    print(segment.text)