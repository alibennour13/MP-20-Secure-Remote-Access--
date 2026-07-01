from faster_whisper import WhisperModel

# On charge le modèle de reconnaissance vocale
# "small" est un bon équilibre entre vitesse et précision
modele = WhisperModel("modele-whisper")
# On transcrit le fichier audio
# Remplace "test.wav" par le vrai nom de ton fichier
segments, info = modele.transcribe("test.m4a", language="fr")

# On affiche le texte reconnu
print("Langue détectée :", info.language)
print("Texte reconnu :")
for segment in segments:
    print(segment.text)