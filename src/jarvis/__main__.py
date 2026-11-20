"""Ligne de commande : « jarvis » (clavier) ou « jarvis --voix »."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Callable, Optional

from . import __version__
from .assistant import Jarvis
from .economie import MODELE_PUISSANT
from .memoire import Memoire

AIDE = """Commandes : /stats (coûts et économies), /souvenirs (tout lister), /oublie N (effacer le souvenir N),
/resume (résumé en mémoire), /quitter. Commencez un message par « ! » pour forcer le modèle puissant."""


def _dollars(x) -> str:
    return f"{float(x):.4f} $".replace(".", ",")


def commande(jarvis: Jarvis, ligne: str) -> Optional[str]:
    """Traite une commande « /... » ; renvoie le texte à afficher, ou None pour quitter."""
    nom, _, arg = ligne[1:].partition(" ")
    if nom in ("quitter", "exit", "q"):
        return None
    if nom == "stats":
        s = jarvis.statistiques()
        return (f"{s['appels']} appels, {s['entree'] + s['cache_lecture']} jetons envoyés dont {s['cache_lecture']} "
                f"lus depuis le cache, {s['sortie']} jetons reçus. Coût : {_dollars(s['cout'])} "
                f"(sans cache : {_dollars(s['cout_sans_cache'])}). Souvenirs : {s['souvenirs']}.")
    if nom == "souvenirs":
        tous = jarvis.memoire.tous()
        return "\n".join(f"{s.id}. {s.contenu}" for s in tous) or "Aucun souvenir pour l'instant."
    if nom == "oublie":
        if not arg.strip().isdigit():
            return "Usage : /oublie N"
        return "Souvenir effacé." if jarvis.memoire.oublier(int(arg)) else "Souvenir introuvable."
    if nom == "resume":
        return jarvis.memoire.resume() or "Pas encore de résumé."
    return AIDE


def boucle(jarvis: Jarvis, lire: Callable[[], Optional[str]], ecrire: Callable[[str], None],
           parler: Optional[Callable[[str], object]] = None) -> None:
    ecrire("Jarvis : À votre service. (/aide pour les commandes)")
    while True:
        ligne = lire()
        if ligne is None:
            break
        ligne = ligne.strip()
        if not ligne:
            continue
        if ligne.startswith("/"):
            sortie = commande(jarvis, ligne)
            if sortie is None:
                ecrire("Jarvis : À bientôt.")
                break
            ecrire(sortie)
            continue
        try:
            r = jarvis.repondre(ligne)
        except Exception as exc:  # erreur réseau, clé invalide, quota...
            ecrire(f"Jarvis : un problème est survenu ({exc}).")
            continue
        ecrire(f"Jarvis : {r.texte}")
        ecrire(f"  [{r.modele}, {_dollars(r.cout)}, économie due au cache {_dollars(r.economie)}]")
        if parler:
            parler(r.texte)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="jarvis", description="Assistant personnel en français, économe en jetons.")
    p.add_argument("--version", action="version", version=f"jarvis-fr {__version__}")
    p.add_argument("--voix", action="store_true", help="parler à Jarvis au micro et l'entendre répondre")
    p.add_argument("--muet", action="store_true", help="ne pas lire les réponses à voix haute")
    p.add_argument("--nom", default="Monsieur", help="comment Jarvis vous appelle")
    p.add_argument("--memoire", help="fichier de mémoire (défaut : ~/.jarvis/memoire.db)")
    p.add_argument("--puissant", action="store_true", help="toujours utiliser " + MODELE_PUISSANT)
    args = p.parse_args(argv)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Définissez d'abord votre clé d'API : export ANTHROPIC_API_KEY=... "
              "(créez-la sur https://platform.claude.com).", file=sys.stderr)
        return 2
    jarvis = Jarvis(memoire=Memoire(args.memoire), nom_utilisateur=args.nom,
                    modele_force=MODELE_PUISSANT if args.puissant else None)

    parler = None
    if not args.muet:
        from .voix import parler as _parler, synthese_disponible
        if synthese_disponible():
            parler = _parler

    if args.voix:
        from .voix import ecouter

        def lire() -> Optional[str]:
            print("(je vous écoute...)")
            texte = ecouter()
            if texte:
                print(f"Vous : {texte}")
            return texte if texte is not None else ""
    else:
        def lire() -> Optional[str]:
            try:
                return input("Vous : ")
            except (EOFError, KeyboardInterrupt):
                return None

    try:
        boucle(jarvis, lire, print, parler)
    except KeyboardInterrupt:
        print("\nJarvis : À bientôt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
