"""Tests sans appel réseau : un faux client remplace l'API Claude."""

import copy
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from jarvis import Jarvis, Memoire, Outils, choisir_modele, cout, cout_sans_cache
from jarvis.__main__ import boucle, commande
from jarvis.economie import MODELE_ECONOMIQUE, MODELE_PUISSANT


# --- faux client -------------------------------------------------------------

def texte(t):
    return SimpleNamespace(type="text", text=t)


def outil(nom, entree, ident="toolu_1"):
    return SimpleNamespace(type="tool_use", id=ident, name=nom, input=entree)


def reponse(*blocs, stop="end_turn", entree=100, sortie=20, cache_w=0, cache_r=0):
    usage = SimpleNamespace(input_tokens=entree, output_tokens=sortie,
                            cache_creation_input_tokens=cache_w, cache_read_input_tokens=cache_r)
    return SimpleNamespace(content=list(blocs), stop_reason=stop, usage=usage)


class FauxClient:
    def __init__(self, *reponses):
        self.reponses = list(reponses)
        self.appels = []
        self.messages = self

    def create(self, **kwargs):
        self.appels.append(copy.deepcopy(kwargs))   # comme le SDK, qui envoie un instantané
        return self.reponses.pop(0)


@pytest.fixture
def memoire():
    m = Memoire(":memory:")
    yield m
    m.fermer()


def jarvis_avec(memoire, *reponses, **options):
    client = FauxClient(*reponses)
    outils = Outils(memoire, confirmer=lambda q: False, ouvrir=lambda n: True,
                    horloge=lambda: datetime(2026, 11, 20, 14, 5))
    return Jarvis(client=client, memoire=memoire, outils=outils, nom_utilisateur="Alex", **options), client


# --- mémoire -------------------------------------------------------------------

def test_memoire_recherche_sans_accents(memoire):
    memoire.ajouter("Alex travaille en contrôle de gestion chez Durand Industrie")
    memoire.ajouter("Le marathon de Paris a lieu en avril")
    trouves = memoire.rechercher("Où est-ce que je travaille en controle ?")
    assert trouves and "Durand" in trouves[0].contenu
    assert memoire.rechercher("recette de cuisine") == []


def test_memoire_doublons_et_oubli(memoire):
    a = memoire.ajouter("Aime le café")
    assert memoire.ajouter("Aime   le café") == a
    assert memoire.nombre() == 1
    assert memoire.oublier(a) and not memoire.oublier(a)
    assert memoire.rechercher("café") == []


def test_memoire_persistante(tmp_path):
    chemin = tmp_path / "memoire.db"
    m = Memoire(chemin)
    m.ajouter("Anniversaire de Camille le 12 mai")
    m.definir_resume("On a parlé du budget.")
    m.fermer()
    m2 = Memoire(chemin)
    assert m2.rechercher("anniversaire")[0].contenu.endswith("12 mai")
    assert m2.resume() == "On a parlé du budget."
    m2.fermer()


# --- économie --------------------------------------------------------------------

def test_couts():
    u = {"input_tokens": 1_000_000, "output_tokens": 0}
    assert cout(MODELE_ECONOMIQUE, u) == Decimal("0.10")
    assert cout(MODELE_PUISSANT, {"output_tokens": 1_000_000}) == Decimal("10")
    # Lecture depuis le cache : 0,10 $ au lieu de 2 $ par million sur Sonnet 5.5
    lu = {"cache_read_input_tokens": 1_000_000}
    assert cout(MODELE_PUISSANT, lu) == Decimal("0.10")
    assert cout_sans_cache(MODELE_PUISSANT, lu) == Decimal("2")


def test_choix_du_modele():
    assert choisir_modele("Quelle heure est-il ?") == MODELE_ECONOMIQUE
    assert choisir_modele("Rédige un mail à mon tuteur") == MODELE_PUISSANT
    assert choisir_modele("x" * 600) == MODELE_PUISSANT
    assert choisir_modele("salut", force="claude-opus-5-5") == "claude-opus-5-5"


# --- outils ------------------------------------------------------------------------

def test_outils(memoire, tmp_path):
    refus = Outils(memoire, dossier_notes=tmp_path, confirmer=lambda q: False, ouvrir=lambda n: True,
                   horloge=lambda: datetime(2026, 11, 20, 14, 5))
    assert refus.executer("heure_et_date", {}) == "vendredi 20 novembre 2026, 14:05"
    assert "enregistré" in refus.executer("se_souvenir", {"fait": "Préfère le thé"})
    assert "thé" in refus.executer("rechercher_souvenirs", {"requete": "thé"})
    refus.executer("noter", {"texte": "Acheter du pain"})
    assert "Acheter du pain" in (tmp_path / "notes.md").read_text(encoding="utf-8")
    assert "refusé" in refus.executer("ouvrir_application", {"nom": "Safari"})
    assert "refusé" in refus.executer("ouvrir_application", {"nom": "Safari; rm -rf ~"})
    accord = Outils(memoire, confirmer=lambda q: True, ouvrir=lambda n: True)
    assert accord.executer("ouvrir_application", {"nom": "Notes"}) == "Notes est ouvert."
    assert "inconnu" in accord.executer("formater_disque", {})
    assert "invalides" in accord.executer("noter", {"mauvais": 1})


# --- assistant ---------------------------------------------------------------------

def test_reponse_simple_et_cache(memoire):
    memoire.ajouter("Alex a un chat qui s'appelle Biscotte")
    j, client = jarvis_avec(memoire, reponse(texte("Votre chat s'appelle Biscotte.")))
    r = j.repondre("Comment s'appelle mon chat ?")
    assert r.texte == "Votre chat s'appelle Biscotte."
    assert r.modele == MODELE_ECONOMIQUE
    appel = client.appels[0]
    assert appel["system"][0]["cache_control"] == {"type": "ephemeral"}
    contenu = appel["messages"][-1]["content"]
    assert "Biscotte" in contenu[0]["text"] and contenu[0]["text"].startswith("<contexte>")
    assert contenu[-1]["text"] == "Comment s'appelle mon chat ?"
    # Le contexte n'est pas conservé dans l'historique (il serait renvoyé à chaque tour)
    assert j.historique[0][0]["content"] == "Comment s'appelle mon chat ?"
    assert j.statistiques()["appels"] == 1


def test_point_de_cache_sur_l_historique(memoire):
    j, client = jarvis_avec(memoire, reponse(texte("Bonjour.")), reponse(texte("Très bien.")))
    j.repondre("Bonjour Jarvis")
    j.repondre("Ça va ?")
    messages = client.appels[1]["messages"]
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    # L'historique stocké n'est pas modifié par le marquage
    assert "cache_control" not in j.historique[0][1]["content"][-1]


def test_boucle_d_outils(memoire):
    j, client = jarvis_avec(
        memoire,
        reponse(outil("se_souvenir", {"fait": "L'anniversaire de Léa est le 3 juin"}), stop="tool_use"),
        reponse(texte("C'est noté.")),
    )
    r = j.repondre("Retiens que l'anniversaire de Léa est le 3 juin")
    assert r.texte == "C'est noté." and r.outils == ["se_souvenir"]
    assert memoire.rechercher("anniversaire Léa")
    second = client.appels[1]["messages"]
    assert second[-1]["role"] == "user" and second[-1]["content"][0]["type"] == "tool_result"
    assert second[-1]["content"][0]["tool_use_id"] == "toolu_1"


def test_point_d_exclamation_force_le_modele_puissant(memoire):
    j, client = jarvis_avec(memoire, reponse(texte("ok")))
    r = j.repondre("! salut")
    assert r.modele == MODELE_PUISSANT and client.appels[0]["model"] == MODELE_PUISSANT
    assert client.appels[0]["messages"][-1]["content"][-1]["text"] == "salut"


def test_economie_mesuree(memoire):
    j, _ = jarvis_avec(memoire, reponse(texte("ok"), entree=10, cache_r=100_000))
    r = j.repondre("Rédige deux lignes")      # modèle puissant
    assert r.economie == Decimal("0.19")     # 100 000 jetons : 0,20 $ au lieu de 0,01 $


def test_resume_glissant(memoire):
    longues = [reponse(texte("Réponse " + "détaillée " * 60)) for _ in range(4)]
    j, client = jarvis_avec(memoire, *longues[:3], reponse(texte("Alex prépare un marathon.")), longues[3],
                            reponse(texte("Alex prépare un marathon, suite.")), seuil_resume=200, tours_gardes=2)
    for i in range(3):
        j.repondre(f"Question {i}")
    assert len(client.appels) == 4
    assert client.appels[3]["model"] == MODELE_ECONOMIQUE and client.appels[3]["max_tokens"] == 400
    assert memoire.resume() == "Alex prépare un marathon."
    assert len(j.historique) == 2
    j.repondre("Et ensuite ?")
    assert "Alex prépare un marathon." in client.appels[4]["messages"][-1]["content"][0]["text"]


def test_message_vide(memoire):
    j, _ = jarvis_avec(memoire)
    with pytest.raises(ValueError):
        j.repondre("   ")


# --- ligne de commande -----------------------------------------------------------

def test_commandes(memoire):
    j, _ = jarvis_avec(memoire)
    memoire.ajouter("Joue au basket")
    assert "1. Joue au basket" in commande(j, "/souvenirs")
    assert "0 appels" in commande(j, "/stats")
    assert commande(j, "/oublie 1") == "Souvenir effacé."
    assert commande(j, "/quitter") is None
    assert "Commandes" in commande(j, "/aide")


def test_boucle(memoire):
    j, _ = jarvis_avec(memoire, reponse(texte("Il est 14 h 05.")))
    entrees = iter(["Quelle heure est-il ?", "/quitter"])
    sorties, voix = [], []
    boucle(j, lambda: next(entrees), sorties.append, voix.append)
    assert "Jarvis : Il est 14 h 05." in sorties
    assert voix == ["Il est 14 h 05."]
    assert sorties[-1] == "Jarvis : À bientôt."
