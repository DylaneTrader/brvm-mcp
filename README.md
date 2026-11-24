# brvm-mcp

Serveur [MCP](https://modelcontextprotocol.io) pour la **Bourse Régionale des Valeurs Mobilières** (BRVM, UEMOA). Il permet à un assistant IA (Claude, ChatGPT, Cursor, ou tout client MCP) d'interroger les cours, indices, dividendes et fondamentaux des actions cotées, les rapports publiés par les sociétés et les chiffres qu'on y lit, la composition des indices, et de calculer leurs mesures de performance, de risque et de valorisation, en respectant les règles du marché régional.

Les données viennent de [brvm-py](https://github.com/DylaneTrader/brvm-py) : cours ajustés des divisions du nominal, dividendes contrôlés, mis à jour chaque jour de séance.

Page de présentation, mise à jour chaque séance : **https://dylanetrader.github.io/brvm-mcp/** (la séance du jour vue par les outils du serveur, générée par `page/publier.py`). On peut y essayer le serveur sans rien installer : le visiteur saisit sa propre clé API Anthropic, Claude appelle les outils, et ces outils tournent dans son navigateur (le code Python du serveur chargé par Pyodide). La clé n'est envoyée qu'à `api.anthropic.com`.

## Ce qu'on peut demander

> « Compare Sonatel, Orange CI et Société Générale CI depuis janvier 2025 : rendement, volatilité, perte maximale et bêta face au BRVM Composite. »

> « Quelles banques sont cotées au Sénégal, et quel est leur PER au dernier cours ? »

> « Quelles actions ont le plus baissé sur les 20 dernières séances ? »

> « Quel est le résultat net de SGBCI au troisième trimestre 2026, et dans quel rapport est-il publié ? »

> « Quel est le poids de Sonatel dans le BRVM Composite, et quels titres pèsent le plus dans l'indice financier ? »

> « Classe les télécoms par PER et rendement du dividende au 31 décembre 2025, avec les comptes connus à cette date. »

## Outils

| Outil | Rôle |
|---|---|
| `derniere_seance` | Date et état (close ou provisoire) de la dernière séance, opérations sur titres appliquées |
| `rechercher_societe` | Sociétés par nom, code, secteur ou pays |
| `fiche_societe` | ISIN, pays, secteur, nombre de titres, flottant, capitalisation, description |
| `cours` | Cours quotidiens, hebdomadaires ou mensuels d'une action |
| `indice`, `liste_indices` | BRVM Composite, BRVM 30, Prestige, indices sectoriels |
| `dividendes` | Dividendes nets d'IRVM (profil particulier ou institutionnel) et leur contrôle de cohérence |
| `fondamentaux` | Comptes par exercice, PER et rendement recalculés au dernier cours |
| `performance_risque` | Rendement, volatilité, Sharpe, Sortino, VaR et CVaR historiques, perte maximale, bêta, liquidité |
| `comparer` | Les mêmes mesures pour plusieurs actions côte à côte |
| `palmares` | Plus fortes hausses et baisses sur N séances |
| `correlations` | Matrice de corrélation sur les dates communes d'échange |

### Rapports des sociétés et indices

| Outil | Rôle |
|---|---|
| `rapports` | Rapports publiés sur brvm.org (états financiers, rapports d'activité, annuels, semestriels, des commissaires aux comptes, RSE), avec le lien du PDF |
| `chiffres` | Chiffres lus dans ces rapports, en millions de FCFA, annuels, semestriels et trimestriels ; `detail=True` donne la page et le lien du PDF de chaque chiffre |
| `composition` | Poids des actions dans le BRVM Composite ou un indice sectoriel, à une séance |

### Mesures de BRVM Analytics

Ces outils reprennent `brvm.mesures`, qui reproduit les chiffres de l'application BRVM Analytics.

| Outil | Rôle |
|---|---|
| `performances` | Rendements sur la semaine, le mois, le trimestre, l'année en cours et de 1 semaine à 10 ans, dividendes réinvestis ou non |
| `rendement_total` | Placement dividendes nets d'IRVM réinvestis face au seul cours, part due aux dividendes |
| `rendements_annuels` | Rendement par année civile de plusieurs titres ou indices |
| `rendements_mensuels` | Grille des rendements mensuels et saisonnalité par mois |
| `risque` | Volatilité, VaR et CVaR, perte maximale (dates, reprise, perte courante), bêta avec intervalle de confiance, R² et alpha |
| `valorisation` | PER, cours / capitaux propres, ROE, cours / chiffre d'affaires, VE / EBE, rendement du dividende, à une date, avec les seuls comptes connus à cette date |
| `ratios` | Comptes annuels et ratios d'une société (marges, ROE, ROA, distribution ; coefficient d'exploitation et coût du risque pour une banque) |
| `etat_du_marche` | Régime de tendance de l'indice, participation (titres au-dessus de leur moyenne 200 séances) et Fear & Greed BRVM ; mesures descriptives, pas des signaux |

`performance_risque` et `risque` ne mesurent pas la même chose : le premier calcule ses rendements entre séances d'échange, en quotidien ; le second suit les conventions de l'application (cours reporté les jours sans échange, rendements hebdomadaires par défaut, bêta en excès d'un taux sans risque de 3 %). Les deux restent disponibles.

Le serveur n'expose ni actualités ni signaux d'achat ou de vente.

## Règles de la BRVM prises en compte

- Un titre qui n'échange pas un jour n'a pas de ligne ce jour-là : les rendements se calculent entre séances d'échange, jamais avec un rendement nul inventé. La part des séances échangées est donnée comme mesure de liquidité.
- La variation d'un titre est limitée à ±7,5 % par séance : le nombre de séances à la limite est signalé, car il rend la VaR historique trompeuse.
- Bêta et corrélations sont calculés sur les dates communes, avec 31 observations au minimum.
- Les barres hebdomadaires et mensuelles gardent les trous : une période sans échange n'a pas de barre.
- Annualisation sur 252 séances ; les mesures portent sur les cours de clôture, hors dividendes.

## Installation

Avec [uv](https://docs.astral.sh/uv/) :

```bash
uvx --from git+https://github.com/DylaneTrader/brvm-mcp brvm-mcp
```

Claude Desktop (`claude_desktop_config.json`) :

```json
{
  "mcpServers": {
    "brvm": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/DylaneTrader/brvm-mcp", "brvm-mcp"]
    }
  }
}
```

Claude Code :

```bash
claude mcp add brvm -- uvx --from git+https://github.com/DylaneTrader/brvm-mcp brvm-mcp
```

Le cache et la source des données se règlent comme dans brvm-py : variables `BRVM_DONNEES`, `BRVM_CACHE`, `BRVM_TTL`.

## Développement

```bash
pip install -e ".[test]"
pytest
```

Les mesures propres au serveur sont dans `src/brvm_mcp/analyse.py`, en fonctions pures testées sans réseau ; les outils MCP sont dans `src/brvm_mcp/serveur.py`. Compatible avec le SDK MCP 1.x et 2.x.

## Avertissement

Les données sont fournies telles quelles, sans garantie d'exactitude ni d'exhaustivité. Les résultats sont des mesures historiques et ne constituent pas un conseil en investissement. Vérifiez auprès des publications officielles de la BRVM avant toute décision.

Licence : MIT.
