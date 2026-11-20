"""Capacités « à la Iron Man » : météo, état de l'ordinateur, volume, musique, minuteurs.

La météo vient d'Open-Meteo (gratuit, sans clé). Le volume, la musique et la
batterie passent par les commandes intégrées à macOS (osascript, pmset).
Chaque fonction accepte un « telecharger » ou un « executer » de remplacement,
ce qui permet de la tester sans réseau ni Mac.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
from typing import Callable, Optional

CODES_METEO = {
    0: "ciel dégagé", 1: "plutôt dégagé", 2: "partiellement nuageux", 3: "ciel couvert",
    45: "brouillard", 48: "brouillard givrant", 51: "bruine légère", 53: "bruine", 55: "bruine dense",
    56: "bruine verglaçante", 57: "bruine verglaçante", 61: "pluie faible", 63: "pluie", 65: "forte pluie",
    66: "pluie verglaçante", 67: "pluie verglaçante", 71: "neige faible", 73: "neige", 75: "forte neige",
    77: "grains de neige", 80: "averses", 81: "averses", 82: "fortes averses", 85: "averses de neige",
    86: "fortes averses de neige", 95: "orage", 96: "orage avec grêle", 99: "orage violent avec grêle",
}

Telecharger = Callable[[str], str]
Executer = Callable[[list], tuple]


def _telecharger(url: str) -> str:
    requete = urllib.request.Request(url, headers={"User-Agent": "jarvis-fr"})
    with urllib.request.urlopen(requete, timeout=8) as r:
        return r.read().decode("utf-8")


def _executer(commande: list) -> tuple:
    r = subprocess.run(commande, capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def est_mac() -> bool:
    return sys.platform == "darwin"


def _degres(x: float) -> str:
    return f"{round(x)} degré" + ("s" if abs(round(x)) > 1 else "")


# --- météo ----------------------------------------------------------------------

def meteo(ville: str, telecharger: Optional[Telecharger] = None) -> str:
    """Météo actuelle et du jour pour une ville, en une phrase."""
    t = telecharger or _telecharger
    try:
        geo = json.loads(t("https://geocoding-api.open-meteo.com/v1/search?count=1&language=fr&name="
                           + urllib.parse.quote(ville)))
        if not geo.get("results"):
            return f"Je ne trouve pas la ville « {ville} »."
        lieu = geo["results"][0]
        prev = json.loads(t(
            "https://api.open-meteo.com/v1/forecast?timezone=auto&forecast_days=1"
            f"&latitude={lieu['latitude']}&longitude={lieu['longitude']}"
            "&current=temperature_2m,weather_code,wind_speed_10m"
            "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"))
    except (OSError, ValueError, KeyError) as exc:
        return f"Service météo injoignable ({exc})."
    actuel, jour = prev["current"], prev["daily"]
    ciel = CODES_METEO.get(actuel["weather_code"], "temps indéterminé")
    phrase = (f"À {lieu['name']}, {_degres(actuel['temperature_2m'])}, {ciel}, vent à "
              f"{round(actuel['wind_speed_10m'])} km/h. Aujourd'hui entre {_degres(jour['temperature_2m_min'][0])} "
              f"et {_degres(jour['temperature_2m_max'][0])}")
    pluie = (jour.get("precipitation_probability_max") or [None])[0]
    if pluie is not None:
        phrase += f", {pluie} % de risque de pluie"
    return phrase + "."


# --- état de l'ordinateur -----------------------------------------------------------

def batterie(executer: Optional[Executer] = None) -> Optional[str]:
    if not est_mac() and executer is None:
        return None
    code, sortie = (executer or _executer)(["pmset", "-g", "batt"])
    m = re.search(r"(\d+)%;\s*([\w ]+?);", sortie) if code == 0 else None
    if not m:
        return None
    etat = {"charging": "en charge", "discharging": "sur batterie", "charged": "chargée",
            "finishing charge": "presque chargée", "AC attached": "sur secteur"}.get(m.group(2).strip(), m.group(2))
    return f"batterie à {m.group(1)} %, {etat}"


def etat_systeme(executer: Optional[Executer] = None) -> str:
    total, utilise, libre = shutil.disk_usage(os.path.expanduser("~"))
    parties = [f"disque utilisé à {round(utilise / total * 100)} %, {round(libre / 1e9)} Go libres"]
    if hasattr(os, "getloadavg"):
        charge = os.getloadavg()[0] / (os.cpu_count() or 1) * 100
        parties.append(f"processeur occupé à environ {round(charge)} %")
    b = batterie(executer)
    if b:
        parties.append(b)
    return "Systèmes nominaux : " + ", ".join(parties) + "."


# --- volume et musique (macOS) ----------------------------------------------------------

ACTIONS_MUSIQUE = {"lecture": "play", "pause": "pause", "suivant": "next track", "precedent": "previous track"}


def regler_volume(niveau: int, executer: Optional[Executer] = None) -> str:
    if not est_mac() and executer is None:
        return "Le réglage du volume n'est disponible que sur Mac."
    niveau = max(0, min(100, int(niveau)))
    code, _ = (executer or _executer)(["osascript", "-e", f"set volume output volume {niveau}"])
    return f"Volume réglé à {niveau} %." if code == 0 else "Impossible de régler le volume."


def musique(action: str, executer: Optional[Executer] = None) -> str:
    if action not in ACTIONS_MUSIQUE:
        return f"Action inconnue : {action} (lecture, pause, suivant, precedent)."
    if not est_mac() and executer is None:
        return "Le contrôle de la musique n'est disponible que sur Mac."
    code, _ = (executer or _executer)(["osascript", "-e",
                                       f'tell application "Music" to {ACTIONS_MUSIQUE[action]}'])
    return {"lecture": "Lecture lancée.", "pause": "Musique en pause.", "suivant": "Morceau suivant.",
            "precedent": "Morceau précédent."}[action] if code == 0 else "L'application Musique ne répond pas."


# --- minuteurs ------------------------------------------------------------------------

class Minuteurs:
    """Minuteurs et rappels : à l'échéance, la fonction « alerte » reçoit le message."""

    def __init__(self, alerte: Callable[[str], None] = print,
                 planifier: Optional[Callable[[float, Callable[[], None]], object]] = None):
        self.alerte = alerte
        self.planifier = planifier or self._planifier_thread
        self.actifs = []

    @staticmethod
    def _planifier_thread(secondes: float, action: Callable[[], None]) -> object:
        t = threading.Timer(secondes, action)
        t.daemon = True
        t.start()
        return t

    def programmer(self, minutes: float, message: str) -> str:
        if minutes <= 0 or minutes > 24 * 60:
            return "La durée doit être comprise entre quelques secondes et 24 heures."
        texte = message.strip() or "Le minuteur est terminé."
        entree = {"minutes": minutes, "message": texte}

        def declencher():
            if entree in self.actifs:
                self.actifs.remove(entree)
            self.alerte(texte)

        self.actifs.append(entree)
        self.planifier(minutes * 60, declencher)
        duree = f"{round(minutes)} minute" + ("s" if round(minutes) > 1 else "") if minutes >= 1 \
            else f"{round(minutes * 60)} secondes"
        return f"Rappel programmé dans {duree}."
