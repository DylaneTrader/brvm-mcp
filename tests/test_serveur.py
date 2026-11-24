import asyncio
import sys

import pandas as pd
import pytest

import brvm
from brvm_mcp import serveur

NOUVEAUX = {"rapports", "chiffres", "composition", "performances", "rendement_total", "rendements_annuels",
            "rendements_mensuels", "risque", "valorisation", "ratios", "etat_du_marche"}


def test_outils_exposes():
    noms = {t.name for t in asyncio.run(serveur.serveur.list_tools())}
    assert {"derniere_seance", "cours", "performance_risque", "comparer", "fondamentaux",
            "dividendes", "palmares", "correlations", "rechercher_societe"} <= noms
    assert NOUVEAUX <= noms


def test_outils_documentes():
    for t in asyncio.run(serveur.serveur.list_tools()):
        assert t.description and len(t.description) > 30, t.name


def test_aucun_outil_actualites_ni_signaux():
    noms = {t.name for t in asyncio.run(serveur.serveur.list_tools())}
    assert not any(m in n for n in noms for m in ("actualit", "news", "signal"))


def test_composition(monkeypatch):
    poids = pd.Series({"SNTS.sn": 0.5, "ORAC.ci": 0.3, "SGBC.ci": 0.2}, name=pd.Timestamp("2026-11-20"))
    monkeypatch.setattr(brvm, "composition", lambda indice, date=None: poids)
    monkeypatch.setattr(brvm, "societes", lambda: pd.DataFrame(
        {"nom": ["SONATEL", "ORANGE CI", "SGBCI"]}, index=["SNTS.sn", "ORAC.ci", "SGBC.ci"]))
    r = serveur.composition("brvmc", nombre=2)
    assert r["seance"] == "2026-11-20" and r["titres_dans_indice"] == 3
    assert r["poids_pct"][0] == {"ticker": "SNTS.sn", "nom": "SONATEL", "poids_pct": 50.0}
    assert r["reste_pct"] == 20.0


def test_rapports_les_plus_recents(monkeypatch):
    df = pd.DataFrame({"ticker": "SNTS.sn", "exercice": [2025, 2024, 2026], "periode": ["A", "A", "S1"],
                       "type": "etats_financiers", "statut": "", "titre": ["b", "a", "c"],
                       "date_publication": pd.to_datetime(["2026-02-16", "2025-02-20", "2026-07-24"]),
                       "pages": 10, "chiffres_lus": 3, "url": "https://www.brvm.org/x.pdf"})
    monkeypatch.setattr(brvm, "resoudre", lambda c: "SNTS.sn")
    monkeypatch.setattr(brvm, "rapports", lambda *a, **k: df)
    r = serveur.rapports("snts", max_lignes=2)
    assert [l[r["colonnes"].index("titre")] for l in r["lignes"]] == ["b", "c"]
    with pytest.raises(ValueError):
        serveur.rapports("snts", type="inconnu")


def test_mesures_absent_message_clair(monkeypatch):
    monkeypatch.setitem(sys.modules, "brvm.mesures", None)
    monkeypatch.delattr(brvm, "mesures", raising=False)
    with pytest.raises(RuntimeError, match="brvm-py"):
        serveur._mesures()
