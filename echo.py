import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel
from piper import PiperVoice

# On charge les deux briques
print("Chargement des modèles...")
modele = WhisperModel("modele-whisper")
voix = PiperVoice.load("voix-piper/fr_FR-siwis-medium.onnx")

# Réglages du micro
duree = 5
frequence = 16000

# 1) ÉCOUTER
print("Parlez maintenant... (", duree, "secondes )")
audio = sd.rec(int(duree * frequence), samplerate=frequence, channels=1, dtype="float32")
sd.wait()
audio = np.squeeze(audio)

# 2) COMPRENDRE (transcrire)
print("Analyse...")
segments, info = modele.transcribe(audio, language="fr")
texte_reconnu = ""
for segment in segments:
    texte_reconnu = texte_reconnu + segment.text
print("Vous avez dit :", texte_reconnu)

# 3) RÉPONDRE (répéter à voix haute)
reponse = "Vous avez dit :" + texte_reconnu
print("ARIA répète...")
for morceau in voix.synthesize(reponse):
    donnees = np.frombuffer(morceau.audio_int16_bytes, dtype=np.int16)
    sd.play(donnees, samplerate=morceau.sample_rate)
    sd.wait()

print("Terminé.")