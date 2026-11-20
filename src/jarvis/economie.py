"""Tout ce qui sert à dépenser moins : tarifs, calcul des coûts, choix du modèle.

Tarifs en dollars par million de jetons (page "Prompt caching" de la
documentation Claude, novembre 2026). Les lectures de cache coûtent 5 % du
prix d'entrée pour Sonnet 5.5 et Opus 5.5, 10 % pour Haiku 5.5.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

D = Decimal
MILLION = D(1_000_000)

MODELE_ECONOMIQUE = "claude-haiku-5-5"
MODELE_PUISSANT = "claude-sonnet-5-5"


@dataclass(frozen=True)
class Tarif:
    entree: Decimal
    sortie: Decimal
    cache_ecriture: Decimal   # écriture en cache, durée de 5 minutes
    cache_lecture: Decimal


TARIFS = {
    "claude-haiku-5-5": Tarif(D("0.10"), D("0.50"), D("0.125"), D("0.01")),
    "claude-sonnet-5-5": Tarif(D("2"), D("10"), D("2.50"), D("0.10")),
    "claude-opus-5-5": Tarif(D("4"), D("20"), D("5"), D("0.20")),
}

#: Mots qui signalent une demande exigeante, confiée au modèle puissant.
MOTS_COMPLEXES = (
    "analyse", "explique en détail", "rédige", "code", "programme", "script", "compare", "stratégie",
    "démontre", "corrige", "traduis", "dissertation", "plan détaillé", "business plan", "calcule",
)
LONGUEUR_COMPLEXE = 500


def _champ(usage: Any, nom: str) -> int:
    valeur = usage.get(nom) if isinstance(usage, dict) else getattr(usage, nom, None)
    return int(valeur or 0)


def jetons(usage: Any) -> dict:
    """Jetons d'une réponse de l'API, champs absents comptés à zéro."""
    return {
        "entree": _champ(usage, "input_tokens"),
        "sortie": _champ(usage, "output_tokens"),
        "cache_ecriture": _champ(usage, "cache_creation_input_tokens"),
        "cache_lecture": _champ(usage, "cache_read_input_tokens"),
    }


def cout(modele: str, usage: Any) -> Decimal:
    """Coût réel d'un appel, en dollars."""
    t, j = TARIFS[modele], jetons(usage)
    return (j["entree"] * t.entree + j["sortie"] * t.sortie
            + j["cache_ecriture"] * t.cache_ecriture + j["cache_lecture"] * t.cache_lecture) / MILLION


def cout_sans_cache(modele: str, usage: Any) -> Decimal:
    """Ce qu'aurait coûté le même appel sans cache (pour mesurer l'économie)."""
    t, j = TARIFS[modele], jetons(usage)
    entree = j["entree"] + j["cache_ecriture"] + j["cache_lecture"]
    return (entree * t.entree + j["sortie"] * t.sortie) / MILLION


def estimer_jetons(texte: str) -> int:
    """Estimation grossière : environ 4 caractères par jeton."""
    return max(1, len(texte) // 4)


def choisir_modele(question: str, force: Optional[str] = None) -> str:
    """Modèle économique par défaut, modèle puissant pour les demandes longues ou exigeantes."""
    if force:
        return force
    q = question.lower()
    if len(q) > LONGUEUR_COMPLEXE or any(m in q for m in MOTS_COMPLEXES):
        return MODELE_PUISSANT
    return MODELE_ECONOMIQUE
