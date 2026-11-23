# brvm-mcp

Serveur [MCP](https://modelcontextprotocol.io) pour la **Bourse Régionale des Valeurs Mobilières** (BRVM, UEMOA). Il permet à un assistant IA (Claude, ChatGPT, Cursor, ou tout client MCP) d'interroger les cours, indices, dividendes et fondamentaux des actions cotées, et de calculer leurs mesures de performance et de risque, en respectant les règles du marché régional.

Les données viennent de [brvm-py](https://github.com/DylaneTrader/brvm-py) : cours ajustés des divisions du nominal, dividendes contrôlés, mis à jour chaque jour de séance.

Page de présentation, mise à jour chaque séance : **https://dylanetrader.github.io/brvm-mcp/** (la séance du jour vue par les outils du serveur, générée par `page/publier.py`).

## Ce qu'on peut demander

> « Compare Sonatel, Orange CI et Société Générale CI depuis janvier 2025 : rendement, volatilité, perte maximale et bêta face au BRVM Composite. »

> « Quelles banques sont cotées au Sénégal, et quel est leur PER au dernier cours ? »

> « Quelles actions ont le plus baissé sur les 20 dernières séances ? »

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

Les mesures sont dans `src/brvm_mcp/analyse.py`, en fonctions pures testées sans réseau ; les outils MCP sont dans `src/brvm_mcp/serveur.py`. Compatible avec le SDK MCP 1.x et 2.x.

## Avertissement

Les données sont fournies telles quelles, sans garantie d'exactitude ni d'exhaustivité. Les résultats sont des mesures historiques et ne constituent pas un conseil en investissement. Vérifiez auprès des publications officielles de la BRVM avant toute décision.

Licence : MIT.
