import asyncio

from brvm_mcp import serveur


def test_outils_exposes():
    noms = {t.name for t in asyncio.run(serveur.serveur.list_tools())}
    assert {"derniere_seance", "cours", "performance_risque", "comparer", "fondamentaux",
            "dividendes", "palmares", "correlations", "rechercher_societe"} <= noms


def test_outils_documentes():
    for t in asyncio.run(serveur.serveur.list_tools()):
        assert t.description and len(t.description) > 30, t.name
