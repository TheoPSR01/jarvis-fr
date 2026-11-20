"""Le cœur de Jarvis : conversation économe avec mémoire.

Quatre mécanismes réduisent la facture :

1. Cache de prompt : les outils et la personnalité (partie fixe) puis
   l'historique sont marqués « cache_control » ; relus depuis le cache, ils
   coûtent 5 à 10 % du prix normal.
2. Mémoire ciblée : seuls les souvenirs pertinents pour la question sont
   ajoutés au message, jamais toute la mémoire.
3. Résumé glissant : au-delà d'un seuil, les vieux échanges sont résumés par
   le modèle économique et retirés de l'historique envoyé.
4. Choix du modèle : Haiku pour les questions simples, Sonnet pour les
   demandes exigeantes (ou quand le message commence par « ! »).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

from .economie import MODELE_ECONOMIQUE, choisir_modele, cout, cout_sans_cache, estimer_jetons, jetons
from .memoire import Memoire
from .outils import DEFINITIONS, Outils

CACHE = {"type": "ephemeral"}
MAX_ITERATIONS_OUTILS = 5

PERSONNALITE = """Tu es J.A.R.V.I.S., l'intelligence artificielle personnelle de {nom}, \
dans l'esprit du majordome numérique de Tony Stark : dévoué, d'un calme à toute épreuve, \
d'une politesse impeccable, avec un humour pince-sans-rire très britannique. Tu appelles l'utilisateur \
« {nom} ». Tu réponds en français, en une à trois phrases le plus souvent : tes réponses sont lues \
à voix haute, donc pas de listes à puces ni de Markdown, et des chiffres faciles à prononcer.

Tu agis plutôt que de décrire : pour l'heure, la météo, l'état de l'ordinateur, le volume, la musique, \
un minuteur ou une application, utilise tes outils puis confirme brièvement (« C'est fait. »). \
Tu ne prétends jamais avoir fait une action que tes outils n'ont pas confirmée, et tu ne disposes \
d'aucune armure, d'aucun satellite ni d'aucun accès aux systèmes extérieurs : si on te le demande, \
décline avec élégance.

Tu disposes d'une mémoire à long terme. Avant chaque message, tu reçois parfois un bloc <contexte> \
contenant le résumé des conversations passées et des souvenirs liés à la question : utilise-les \
naturellement, sans dire que tu les as lus. Quand {nom} te demande de retenir quelque chose, ou te \
confie un fait durable (une personne, une préférence, une échéance), enregistre-le avec l'outil \
se_souvenir. N'invente jamais un souvenir. Si tu ne sais pas, dis-le."""

RESUME_SYSTEME = ("Tu tiens à jour le résumé des conversations entre un utilisateur et son assistant. "
                  "Écris en français, en quelques phrases, en gardant les faits, décisions et tâches en cours "
                  "utiles pour la suite. Pas de préambule.")


@dataclass
class Reponse:
    texte: str
    modele: str
    cout: Decimal
    economie: Decimal
    outils: list = field(default_factory=list)


def _bloc_en_dict(bloc: Any) -> dict:
    if bloc.type == "text":
        return {"type": "text", "text": bloc.text}
    if bloc.type == "tool_use":
        return {"type": "tool_use", "id": bloc.id, "name": bloc.name, "input": bloc.input}
    raise ValueError(f"type de bloc non géré : {bloc.type}")


def _texte(message: dict) -> str:
    contenu = message["content"]
    if isinstance(contenu, str):
        return contenu
    return " ".join(b.get("text", "") for b in contenu if b.get("type") == "text").strip()


class Jarvis:
    def __init__(self, client: Any = None, memoire: Optional[Memoire] = None, nom_utilisateur: str = "Monsieur",
                 outils: Optional[Outils] = None, modele_force: Optional[str] = None, max_tokens: int = 800,
                 seuil_resume: int = 3000, tours_gardes: int = 4, souvenirs_par_question: int = 5):
        if client is None:
            import anthropic  # import tardif : les tests n'en ont pas besoin
            client = anthropic.Anthropic()
        self.client = client
        self.memoire = memoire if memoire is not None else Memoire()
        self.outils = outils if outils is not None else Outils(self.memoire)
        self.nom = nom_utilisateur
        self.modele_force = modele_force
        self.max_tokens = max_tokens
        self.seuil_resume = seuil_resume
        self.tours_gardes = tours_gardes
        self.souvenirs_par_question = souvenirs_par_question
        self.historique: list = []   # liste de tours ; un tour = liste de messages

    # --- construction de la requête -----------------------------------------

    def _systeme(self) -> list:
        return [{"type": "text", "text": PERSONNALITE.format(nom=self.nom), "cache_control": CACHE}]

    def _contexte(self, question: str) -> str:
        parties = []
        resume = self.memoire.resume()
        if resume:
            parties.append(f"Résumé des échanges précédents : {resume}")
        souvenirs = self.memoire.rechercher(question, self.souvenirs_par_question)
        if souvenirs:
            parties.append("Souvenirs liés à la question :\n" + "\n".join(f"- {s.contenu}" for s in souvenirs))
        return "\n\n".join(parties)

    def _messages(self, question: str) -> list:
        messages = [dict(m) for tour in self.historique for m in tour]
        if messages:
            # Point de cache sur la fin de l'historique : il sera relu à prix réduit au tour suivant.
            dernier = messages[-1]
            contenu = dernier["content"]
            blocs = [{"type": "text", "text": contenu}] if isinstance(contenu, str) else [dict(b) for b in contenu]
            blocs[-1]["cache_control"] = CACHE
            messages[-1] = {"role": dernier["role"], "content": blocs}
        actuel = []
        contexte = self._contexte(question)
        if contexte:
            actuel.append({"type": "text", "text": f"<contexte>\n{contexte}\n</contexte>"})
        actuel.append({"type": "text", "text": question})
        messages.append({"role": "user", "content": actuel})
        return messages

    # --- conversation ---------------------------------------------------------

    def _comptabiliser(self, modele: str, usage: Any) -> tuple:
        c, s = cout(modele, usage), cout_sans_cache(modele, usage)
        j = jetons(usage)
        self.memoire.enregistrer_consommation(modele, j["entree"], j["sortie"], j["cache_ecriture"],
                                              j["cache_lecture"], float(c), float(s))
        return c, s

    def repondre(self, message: str) -> Reponse:
        message = message.strip()
        force = self.modele_force
        if message.startswith("!"):
            message = message.lstrip("!").strip()
            force = force or "claude-sonnet-5-5"
        if not message:
            raise ValueError("message vide")
        modele = choisir_modele(message, force)

        tour = [{"role": "user", "content": message}]       # stocké sans le contexte
        messages = self._messages(message)
        total, sans_cache, outils_utilises = Decimal(0), Decimal(0), []

        for _ in range(MAX_ITERATIONS_OUTILS):
            r = self.client.messages.create(model=modele, max_tokens=self.max_tokens, system=self._systeme(),
                                            tools=DEFINITIONS, messages=messages)
            c, s = self._comptabiliser(modele, r.usage)
            total, sans_cache = total + c, sans_cache + s
            reponse_assistant = {"role": "assistant", "content": [_bloc_en_dict(b) for b in r.content]}
            messages.append(reponse_assistant)
            tour.append(reponse_assistant)
            if r.stop_reason != "tool_use":
                break
            resultats = []
            for b in r.content:
                if b.type == "tool_use":
                    outils_utilises.append(b.name)
                    resultats.append({"type": "tool_result", "tool_use_id": b.id,
                                      "content": self.outils.executer(b.name, b.input)})
            retour = {"role": "user", "content": resultats}
            messages.append(retour)
            tour.append(retour)

        texte = _texte(tour[-1]) if tour[-1]["role"] == "assistant" else ""
        self.historique.append(tour)
        self._compacter()
        return Reponse(texte or "(pas de réponse)", modele, total, sans_cache - total, outils_utilises)

    # --- résumé glissant -------------------------------------------------------

    def taille_historique(self) -> int:
        return estimer_jetons(json.dumps(self.historique, ensure_ascii=False))

    def _compacter(self) -> bool:
        if self.taille_historique() <= self.seuil_resume or len(self.historique) <= self.tours_gardes:
            return False
        anciens = self.historique[:-self.tours_gardes]
        lignes = []
        for tour in anciens:
            for m in tour:
                t = _texte(m)
                if t:
                    lignes.append(("Utilisateur" if m["role"] == "user" else "Assistant") + " : " + t)
        demande = (f"Résumé actuel :\n{self.memoire.resume() or '(aucun)'}\n\n"
                   f"Nouveaux échanges :\n" + "\n".join(lignes) + "\n\nDonne le résumé mis à jour.")
        r = self.client.messages.create(model=MODELE_ECONOMIQUE, max_tokens=400, system=RESUME_SYSTEME,
                                        messages=[{"role": "user", "content": demande}])
        self._comptabiliser(MODELE_ECONOMIQUE, r.usage)
        resume = " ".join(b.text for b in r.content if b.type == "text").strip()
        if resume:
            self.memoire.definir_resume(resume)
        self.historique = self.historique[-self.tours_gardes:]
        return True

    def briefing(self, maintenant=None) -> str:
        """Accueil à la Iron Man, calculé localement (aucun appel à l'API, donc gratuit)."""
        heure = (maintenant or self.outils.horloge()).hour
        salut = "Bonjour" if 5 <= heure < 18 else "Bonsoir"
        parties = [f"{salut} {self.nom}. Nous sommes {self.outils.heure_et_date()}."]
        if self.outils.ville:
            parties.append(self.outils.meteo())
        from .systeme import batterie
        b = batterie(self.outils.executer_commande)
        if b:
            parties.append(b[0].upper() + b[1:] + ".")
        n = self.memoire.nombre()
        if n:
            parties.append(f"J'ai {n} souvenir{'s' if n > 1 else ''} en mémoire.")
        parties.append("Que puis-je faire pour vous ?")
        return " ".join(parties)

    def statistiques(self) -> dict:
        s = self.memoire.total_consommation()
        s["souvenirs"] = self.memoire.nombre()
        s["economie"] = s["cout_sans_cache"] - s["cout"]
        return s
