"""Mémoire locale persistante de Jarvis (SQLite, recherche plein texte).

La mémoire peut grossir sans limite : à chaque question, seuls les souvenirs
pertinents (quelques lignes) sont envoyés au modèle, pas la mémoire entière.
C'est ce qui permet une grosse mémoire sans faire exploser le nombre de jetons.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

CHEMIN_DEFAUT = Path.home() / ".jarvis" / "memoire.db"

MOTS_VIDES = {
    "les", "des", "une", "est", "que", "qui", "quoi", "dans", "pour", "par", "sur", "avec", "sans",
    "mon", "mes", "ton", "tes", "son", "ses", "notre", "nos", "votre", "vos", "leur", "leurs",
    "elle", "ils", "elles", "nous", "vous", "moi", "toi", "lui", "pas", "plus", "tout", "tous",
    "cette", "ces", "cet", "aux", "comment", "pourquoi", "quand", "quel", "quelle", "quels",
    "quelles", "est-ce", "suis", "sont", "était", "avoir", "être", "fait", "faire", "peux", "peut",
    "the", "and", "you", "what",
}


@dataclass(frozen=True)
class Souvenir:
    id: int
    contenu: str
    categorie: str
    cree_le: str


def _maintenant() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Memoire:
    """Souvenirs, résumé de la conversation et suivi de la consommation."""

    def __init__(self, chemin: Union[str, Path, None] = None):
        chemin = CHEMIN_DEFAUT if chemin is None else chemin
        if str(chemin) != ":memory:":
            Path(chemin).expanduser().parent.mkdir(parents=True, exist_ok=True)
            chemin = Path(chemin).expanduser()
        self.db = sqlite3.connect(str(chemin))
        self.db.row_factory = sqlite3.Row
        self.fts = self._creer_tables()

    def _creer_tables(self) -> bool:
        c = self.db
        c.execute("CREATE TABLE IF NOT EXISTS souvenirs (id INTEGER PRIMARY KEY, contenu TEXT NOT NULL, "
                  "categorie TEXT NOT NULL DEFAULT 'fait', cree_le TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS resume (id INTEGER PRIMARY KEY CHECK (id = 1), texte TEXT NOT NULL, "
                  "maj_le TEXT NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS consommation (id INTEGER PRIMARY KEY, date TEXT, modele TEXT, "
                  "entree INTEGER, sortie INTEGER, cache_ecriture INTEGER, cache_lecture INTEGER, "
                  "cout REAL, cout_sans_cache REAL)")
        try:
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS souvenirs_fts USING fts5(contenu, "
                      "tokenize='unicode61 remove_diacritics 2')")
            fts = True
        except sqlite3.OperationalError:
            fts = False
        c.commit()
        return fts

    # --- souvenirs -----------------------------------------------------------

    def ajouter(self, contenu: str, categorie: str = "fait") -> int:
        """Ajoute un souvenir et renvoie son numéro (sans doublon exact)."""
        contenu = " ".join(contenu.split())
        if not contenu:
            raise ValueError("souvenir vide")
        existant = self.db.execute("SELECT id FROM souvenirs WHERE contenu = ?", (contenu,)).fetchone()
        if existant:
            return existant["id"]
        cur = self.db.execute("INSERT INTO souvenirs (contenu, categorie, cree_le) VALUES (?, ?, ?)",
                              (contenu, categorie, _maintenant()))
        if self.fts:
            self.db.execute("INSERT INTO souvenirs_fts (rowid, contenu) VALUES (?, ?)", (cur.lastrowid, contenu))
        self.db.commit()
        return cur.lastrowid

    def oublier(self, identifiant: int) -> bool:
        ligne = self.db.execute("SELECT contenu FROM souvenirs WHERE id = ?", (identifiant,)).fetchone()
        if not ligne:
            return False
        self.db.execute("DELETE FROM souvenirs WHERE id = ?", (identifiant,))
        if self.fts:
            self.db.execute("DELETE FROM souvenirs_fts WHERE rowid = ?", (identifiant,))
        self.db.commit()
        return True

    def tous(self) -> list:
        return [Souvenir(**dict(r)) for r in self.db.execute("SELECT * FROM souvenirs ORDER BY id")]

    def nombre(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM souvenirs").fetchone()[0]

    @staticmethod
    def _mots(requete: str) -> list:
        mots = re.findall(r"\w+", requete.lower())
        return [m for m in dict.fromkeys(mots) if len(m) >= 3 and m not in MOTS_VIDES]

    def rechercher(self, requete: str, limite: int = 5) -> list:
        """Souvenirs les plus pertinents pour une question, du plus au moins pertinent."""
        mots = self._mots(requete)
        if not mots:
            return []
        if self.fts:
            expr = " OR ".join('"' + m.replace('"', '') + '"*' for m in mots)
            lignes = self.db.execute(
                "SELECT s.* FROM souvenirs_fts f JOIN souvenirs s ON s.id = f.rowid "
                "WHERE souvenirs_fts MATCH ? ORDER BY bm25(souvenirs_fts) LIMIT ?", (expr, limite)).fetchall()
        else:
            cond = " OR ".join("contenu LIKE ?" for _ in mots)
            lignes = self.db.execute(f"SELECT * FROM souvenirs WHERE {cond} ORDER BY id DESC LIMIT ?",
                                     [f"%{m}%" for m in mots] + [limite]).fetchall()
        return [Souvenir(**dict(r)) for r in lignes]

    # --- résumé de la conversation -----------------------------------------

    def resume(self) -> str:
        ligne = self.db.execute("SELECT texte FROM resume WHERE id = 1").fetchone()
        return ligne["texte"] if ligne else ""

    def definir_resume(self, texte: str) -> None:
        self.db.execute("INSERT INTO resume (id, texte, maj_le) VALUES (1, ?, ?) "
                        "ON CONFLICT(id) DO UPDATE SET texte = excluded.texte, maj_le = excluded.maj_le",
                        (texte, _maintenant()))
        self.db.commit()

    # --- consommation -------------------------------------------------------

    def enregistrer_consommation(self, modele: str, entree: int, sortie: int, cache_ecriture: int,
                                 cache_lecture: int, cout: float, cout_sans_cache: float) -> None:
        self.db.execute("INSERT INTO consommation (date, modele, entree, sortie, cache_ecriture, cache_lecture, "
                        "cout, cout_sans_cache) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (_maintenant(), modele, entree, sortie, cache_ecriture, cache_lecture, cout, cout_sans_cache))
        self.db.commit()

    def total_consommation(self) -> dict:
        r = self.db.execute("SELECT COUNT(*) AS appels, COALESCE(SUM(entree), 0) AS entree, "
                            "COALESCE(SUM(sortie), 0) AS sortie, COALESCE(SUM(cache_lecture), 0) AS cache_lecture, "
                            "COALESCE(SUM(cout), 0) AS cout, COALESCE(SUM(cout_sans_cache), 0) AS cout_sans_cache "
                            "FROM consommation").fetchone()
        return dict(r)

    def fermer(self) -> None:
        self.db.close()
