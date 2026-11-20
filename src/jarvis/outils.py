"""Actions que Jarvis peut déclencher (outils de l'API Claude)."""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .memoire import Memoire

JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
        "octobre", "novembre", "décembre")
NOM_APPLICATION = re.compile(r"^[\w .+\-]{1,60}$")

DEFINITIONS = [
    {
        "name": "heure_et_date",
        "description": "Donne la date et l'heure actuelles de l'ordinateur.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "se_souvenir",
        "description": "Enregistre durablement un fait utile sur l'utilisateur (préférence, personne, projet, "
                       "date importante). À utiliser quand l'utilisateur demande de retenir quelque chose.",
        "input_schema": {"type": "object", "properties": {"fait": {"type": "string"}}, "required": ["fait"]},
    },
    {
        "name": "rechercher_souvenirs",
        "description": "Cherche dans la mémoire à long terme des souvenirs liés à des mots-clés.",
        "input_schema": {"type": "object", "properties": {"requete": {"type": "string"}}, "required": ["requete"]},
    },
    {
        "name": "noter",
        "description": "Ajoute une note datée dans le carnet de notes de l'utilisateur.",
        "input_schema": {"type": "object", "properties": {"texte": {"type": "string"}}, "required": ["texte"]},
    },
    {
        "name": "ouvrir_application",
        "description": "Ouvre une application sur le Mac de l'utilisateur (par exemple Safari, Notes, Calendrier). "
                       "L'utilisateur doit confirmer.",
        "input_schema": {"type": "object", "properties": {"nom": {"type": "string"}}, "required": ["nom"]},
    },
]


def _confirmer_terminal(question: str) -> bool:
    try:
        return input(f"{question} [o/N] ").strip().lower() in ("o", "oui", "y", "yes")
    except EOFError:
        return False


def _ouvrir_mac(nom: str) -> bool:
    if sys.platform != "darwin":
        return False
    return subprocess.run(["open", "-a", nom], capture_output=True).returncode == 0


class Outils:
    def __init__(self, memoire: Memoire, dossier_notes: Optional[Path] = None,
                 confirmer: Callable[[str], bool] = _confirmer_terminal,
                 ouvrir: Callable[[str], bool] = _ouvrir_mac,
                 horloge: Callable[[], datetime] = datetime.now):
        self.memoire = memoire
        self.dossier_notes = Path(dossier_notes) if dossier_notes else Path.home() / ".jarvis"
        self.confirmer = confirmer
        self.ouvrir = ouvrir
        self.horloge = horloge

    def executer(self, nom: str, entree: dict) -> str:
        methode = getattr(self, nom, None)
        if nom not in {d["name"] for d in DEFINITIONS} or methode is None:
            return f"Outil inconnu : {nom}"
        try:
            return methode(**(entree or {}))
        except TypeError as exc:
            return f"Paramètres invalides pour {nom} : {exc}"

    def heure_et_date(self) -> str:
        n = self.horloge()
        return f"{JOURS[n.weekday()]} {n.day} {MOIS[n.month - 1]} {n.year}, {n:%H:%M}"

    def se_souvenir(self, fait: str) -> str:
        identifiant = self.memoire.ajouter(fait)
        return f"Souvenir n°{identifiant} enregistré."

    def rechercher_souvenirs(self, requete: str) -> str:
        trouves = self.memoire.rechercher(requete, limite=8)
        if not trouves:
            return "Aucun souvenir correspondant."
        return "\n".join(f"- {s.contenu}" for s in trouves)

    def noter(self, texte: str) -> str:
        self.dossier_notes.mkdir(parents=True, exist_ok=True)
        fichier = self.dossier_notes / "notes.md"
        with fichier.open("a", encoding="utf-8") as f:
            f.write(f"- {self.horloge():%d/%m/%Y %H:%M} : {texte.strip()}\n")
        return f"Note ajoutée dans {fichier}."

    def ouvrir_application(self, nom: str) -> str:
        nom = nom.strip()
        if not NOM_APPLICATION.match(nom):
            return "Nom d'application refusé."
        if not self.confirmer(f"Jarvis veut ouvrir « {nom} ». D'accord ?"):
            return "L'utilisateur a refusé l'ouverture."
        if self.ouvrir(nom):
            return f"{nom} est ouvert."
        return f"Impossible d'ouvrir {nom} (application introuvable ou système autre que macOS)."
