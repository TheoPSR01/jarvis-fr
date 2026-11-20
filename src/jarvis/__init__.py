"""jarvis : assistant personnel en français, économe en jetons, avec mémoire locale."""

from .assistant import Jarvis, Reponse
from .economie import MODELE_ECONOMIQUE, MODELE_PUISSANT, TARIFS, choisir_modele, cout, cout_sans_cache
from .memoire import Memoire, Souvenir
from .outils import Outils

__version__ = "0.2.0"

__all__ = [
    "Jarvis", "MODELE_ECONOMIQUE", "MODELE_PUISSANT", "Memoire", "Outils", "Reponse", "Souvenir", "TARIFS",
    "choisir_modele", "cout", "cout_sans_cache",
]
