"""Voix de Jarvis : synthèse vocale (macOS) et reconnaissance vocale (optionnelle).

Synthèse : commande « say » intégrée à macOS, voix française « Thomas » par défaut.
Reconnaissance : paquet SpeechRecognition (pip install "jarvis-fr[voix]"), qui envoie
l'audio au service de reconnaissance de Google.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from typing import Optional

VOIX_DEFAUT = "Thomas"


def synthese_disponible() -> bool:
    return sys.platform == "darwin" and shutil.which("say") is not None


def parler(texte: str, voix: str = VOIX_DEFAUT) -> bool:
    """Lit le texte à voix haute. Renvoie False si aucune synthèse n'est disponible."""
    if not texte.strip() or not synthese_disponible():
        return False
    subprocess.run(["say", "-v", voix, texte], check=False)
    return True


def ecouter(delai: int = 8, langue: str = "fr-FR") -> Optional[str]:
    """Écoute le micro et renvoie le texte compris, ou None si rien n'a été compris."""
    try:
        import speech_recognition as sr
    except ImportError as exc:
        raise RuntimeError('Reconnaissance vocale absente : pip install "jarvis-fr[voix]"') from exc
    r = sr.Recognizer()
    with sr.Microphone() as source:
        r.adjust_for_ambient_noise(source, duration=0.5)
        try:
            audio = r.listen(source, timeout=delai, phrase_time_limit=20)
        except sr.WaitTimeoutError:
            return None
    try:
        return r.recognize_google(audio, language=langue)
    except sr.UnknownValueError:
        return None

MOT_ACTIVATION = "jarvis"


def extraire_commande(texte: Optional[str], mot: str = MOT_ACTIVATION) -> Optional[str]:
    """Pour le mode veille : None si le mot d'activation est absent, sinon la demande
    qui suit (chaîne vide si l'utilisateur n'a dit que « Jarvis »)."""
    if not texte:
        return None
    m = re.search(rf"\b{re.escape(mot)}\b[\s,.!?:]*", texte, flags=re.IGNORECASE)
    if not m:
        return None
    return (texte[:m.start()] + texte[m.end():]).strip(" ,.!?:")
