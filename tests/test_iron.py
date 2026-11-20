"""Tests des fonctions « Iron Man », sans réseau ni Mac : tout est simulé."""

import json
from datetime import datetime

from jarvis import Jarvis, Memoire, Outils
from jarvis import systeme
from jarvis.__main__ import BANNIERE, boucle
from jarvis.voix import extraire_commande


def faux_telecharger(url):
    if "geocoding" in url:
        return json.dumps({"results": [{"name": "Lyon", "latitude": 45.75, "longitude": 4.85}]})
    return json.dumps({
        "current": {"temperature_2m": 12.4, "weather_code": 61, "wind_speed_10m": 15.2},
        "daily": {"temperature_2m_max": [14.1], "temperature_2m_min": [6.8],
                  "precipitation_probability_max": [70]},
    })


class FauxExecuter:
    def __init__(self, sortie="Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1)\t82%; discharging; 4:10 remaining"):
        self.sortie = sortie
        self.commandes = []

    def __call__(self, commande):
        self.commandes.append(commande)
        return 0, self.sortie


class FauxPlanifier:
    def __init__(self):
        self.taches = []

    def __call__(self, secondes, action):
        self.taches.append((secondes, action))


def test_meteo_open_meteo():
    texte = systeme.meteo("Lyon", faux_telecharger)
    assert texte.startswith("À Lyon, 12 degrés")
    assert "pluie" in texte and "70 %" in texte and "15 km/h" in texte


def test_meteo_ville_introuvable():
    texte = systeme.meteo("Xyzabc", lambda url: json.dumps({}))
    assert "introuvable" in texte.lower() or "trouve" in texte.lower()


def test_meteo_sans_reseau():
    def panne(url):
        raise OSError("pas de réseau")
    assert "météo" in systeme.meteo("Lyon", panne).lower()


def test_outil_meteo_utilise_la_ville_par_defaut():
    o = Outils(Memoire(":memory:"), ville="Lyon", telecharger=faux_telecharger)
    assert "Lyon" in o.executer("meteo", {})
    assert "Ville inconnue" in Outils(Memoire(":memory:")).executer("meteo", {})


def test_batterie_et_etat_systeme():
    ex = FauxExecuter()
    assert systeme.batterie(ex) == "batterie à 82 %, sur batterie"
    etat = systeme.etat_systeme(ex)
    assert etat.startswith("Systèmes nominaux") and "Go libres" in etat and "82 %" in etat


def test_volume_borne_et_musique():
    ex = FauxExecuter(sortie="")
    assert systeme.regler_volume(150, ex) == "Volume réglé à 100 %."
    assert ex.commandes[-1][-1] == "set volume output volume 100"
    assert systeme.musique("suivant", ex) == "Morceau suivant."
    assert ex.commandes[-1][-1] == 'tell application "Music" to next track'
    assert "inconnue" in systeme.musique("danser", ex)


def test_minuteur_declenche_une_alerte():
    alertes, plan = [], FauxPlanifier()
    m = systeme.Minuteurs(alerte=alertes.append, planifier=plan)
    o = Outils(Memoire(":memory:"), minuteurs=m)
    assert o.executer("minuteur", {"minutes": 10, "message": "sortir le gâteau"}) == "Rappel programmé dans 10 minutes."
    assert plan.taches[0][0] == 600
    plan.taches[0][1]()
    assert alertes == ["sortir le gâteau"] and m.actifs == []
    assert m.programmer(0.5, "") == "Rappel programmé dans 30 secondes."


def test_extraire_commande():
    assert extraire_commande("Jarvis, quelle heure est-il ?") == "quelle heure est-il"
    assert extraire_commande("jarvis") == ""
    assert extraire_commande("dis-moi Jarvis la météo") == "dis-moi la météo"
    assert extraire_commande("bonjour") is None
    assert extraire_commande(None) is None


def test_briefing_sans_appel_api():
    class ClientInterdit:
        class messages:
            @staticmethod
            def create(**kw):
                raise AssertionError("le briefing ne doit pas appeler l'API")

    mem = Memoire(":memory:")
    mem.ajouter("Le dentiste est jeudi")
    o = Outils(mem, ville="Lyon", telecharger=faux_telecharger, executer=FauxExecuter(),
               horloge=lambda: datetime(2026, 3, 2, 8, 30))
    j = Jarvis(client=ClientInterdit(), memoire=mem, outils=o, nom_utilisateur="Madame")
    b = j.briefing()
    assert b.startswith("Bonjour Madame.")
    assert "Lyon" in b and "Batterie à 82 %" in b and "1 souvenir en mémoire" in b
    assert b.endswith("Que puis-je faire pour vous ?")
    soir = Jarvis(client=ClientInterdit(), memoire=Memoire(":memory:"),
                  outils=Outils(Memoire(":memory:"), horloge=lambda: datetime(2026, 3, 2, 21, 0)))
    assert soir.briefing().startswith("Bonsoir Monsieur.")


def test_boucle_affiche_le_briefing():
    sorties = []
    boucle(None, iter([None]).__next__, sorties.append, accueil="Bonjour Monsieur.")
    assert sorties[0].startswith("Jarvis : Bonjour Monsieur.")


def test_banniere():
    assert "J . A . R . V . I . S ." in BANNIERE.format(version="0.2.0")


def test_dix_outils_declares():
    from jarvis.outils import DEFINITIONS
    noms = {d["name"] for d in DEFINITIONS}
    assert {"meteo", "etat_systeme", "regler_volume", "musique", "minuteur"} <= noms
    assert len(noms) == 10
