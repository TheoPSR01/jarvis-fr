# jarvis-fr

Un assistant personnel à la Jarvis, en français, qui tourne dans votre terminal et vous répond à voix haute. Il s'appuie sur l'API Claude et a été conçu pour deux choses : se souvenir de vous sur la durée, et coûter le moins possible.

```
Vous : Retiens que l'anniversaire de Léa est le 3 juin.
Jarvis : C'est noté. Je vous le rappellerai volontiers.
  [claude-haiku-5-5, 0,0002 $, économie due au cache 0,0000 $]
Vous : Quand est l'anniversaire de Léa ?
Jarvis : Le 3 juin.
```

## Installation

```bash
pip install git+https://github.com/TheoPSR01/jarvis-fr.git
# avec la reconnaissance vocale :
pip install "jarvis-fr[voix] @ git+https://github.com/TheoPSR01/jarvis-fr.git"
```

Python 3.10 ou plus récent. Il vous faut une clé d'API Claude, à créer sur https://platform.claude.com, puis à placer dans une variable d'environnement (ne la mettez jamais dans le code) :

```bash
export ANTHROPIC_API_KEY="votre-clé"
```

L'API est facturée à l'usage. Avec le modèle économique, une question courante coûte de l'ordre d'un dixième de centime ; la commande `/stats` affiche ce que vous avez dépensé.

## Utilisation

```bash
jarvis                      # au clavier ; réponses lues à voix haute sur Mac
jarvis --voix               # vous parlez au micro
jarvis --muet --nom Alex    # sans voix, et Jarvis vous appelle Alex
jarvis --puissant           # toujours le modèle le plus capable
```

Dans la conversation : `/stats` (coûts et économies), `/souvenirs`, `/oublie N`, `/resume`, `/quitter`. Un message qui commence par « ! » est confié au modèle puissant.

Jarvis sait donner l'heure et la date, retenir et retrouver des souvenirs, ajouter des notes datées dans `~/.jarvis/notes.md` et ouvrir une application sur Mac (il vous demande toujours confirmation).

## En Python

```python
from jarvis import Jarvis, Memoire

jarvis = Jarvis(memoire=Memoire("ma_memoire.db"), nom_utilisateur="Alex")
r = jarvis.repondre("Retiens que je préfère le thé au café")
print(r.texte, r.modele, r.cout, r.economie)
print(jarvis.statistiques())
```

La classe `Memoire` s'utilise aussi seule, dans n'importe quel projet qui appelle l'API Claude : `ajouter`, `rechercher`, `oublier`, `resume`.

## Comment Jarvis dépense moins

1. Cache de prompt. Les outils et la personnalité de Jarvis, puis l'historique de la conversation, sont marqués pour la mise en cache. D'un message à l'autre, cette partie est relue depuis le cache, facturée 5 % (Sonnet 5.5) ou 10 % (Haiku 5.5) du prix normal. Le cache dure 5 minutes et ne s'active qu'au-delà de 512 jetons.
2. Mémoire ciblée. La mémoire à long terme est une base SQLite locale avec recherche plein texte. Elle peut contenir des milliers de souvenirs : à chaque question, seuls les cinq plus pertinents sont envoyés.
3. Résumé glissant. Quand l'historique dépasse environ 3 000 jetons, les plus anciens échanges sont résumés en quelques phrases par le modèle économique ; seuls les quatre derniers tours restent en entier. Le résumé est conservé d'une session à l'autre.
4. Choix du modèle. Haiku 5.5 (0,10 $ par million de jetons en entrée) répond aux questions courantes ; Sonnet 5.5 (2 $) prend les demandes longues ou exigeantes (rédiger, analyser, coder...).

Chaque réponse affiche son coût réel et l'économie obtenue grâce au cache, calculés à partir des chiffres renvoyés par l'API.

## Confidentialité

La mémoire, le résumé, les notes et le suivi des coûts restent sur votre ordinateur, dans `~/.jarvis/`. Vos messages, accompagnés des souvenirs jugés pertinents, sont envoyés à l'API Claude pour obtenir une réponse. En mode `--voix`, l'audio est envoyé au service de reconnaissance vocale de Google. N'y confiez pas de mots de passe ni de numéros de carte.

## Limites

La voix fonctionne sur macOS (commande `say`) ; sur les autres systèmes, Jarvis répond par écrit. La recherche dans la mémoire porte sur les mots, pas sur le sens : « voiture » ne retrouve pas « automobile ». Les tarifs intégrés sont ceux de novembre 2026 ; mettez à jour `TARIFS` dans `economie.py` s'ils changent.

## Contribuer

Les tests n'appellent jamais l'API : un faux client remplace Claude.

```bash
git clone https://github.com/TheoPSR01/jarvis-fr.git
cd jarvis-fr
pip install -e ".[dev]"
pytest
```

## Licence

MIT
