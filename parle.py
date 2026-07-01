import wave
from piper import PiperVoice
import sounddevice as sd
import numpy as np

# On charge la voix française depuis le dossier local
voix = PiperVoice.load("voix-piper/fr_FR-siwis-medium.onnx")

# Le texte que le robot va dire
texte = "Bonjour et bienvenue à l'université. Comment puis-je vous aider ?"

print("ARIA parle...")

# On génère l'audio de la phrase et on le joue
for morceau in voix.synthesize(texte):
    # on récupère les données audio du morceau
    donnees = np.frombuffer(morceau.audio_int16_bytes, dtype=np.int16)
    sd.play(donnees, samplerate=morceau.sample_rate)
    sd.wait()

print("Terminé.")