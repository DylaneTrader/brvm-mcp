"""Serveur MCP BRVM : expose les données de brvm-py et des mesures de risque à un assistant IA."""
from __future__ import annotations

import difflib
from typing import Literal

import pandas as pd

import brvm

from . import analyse

try:  # SDK MCP 2.x
    from mcp.server.mcpserver import MCPServer as _Serveur
except ImportError:  # SDK MCP 1.x
    from mcp.server.fastmcp import FastMCP as _Serveur

INSTRUCTIONS = """Données de marché de la BRVM (Bourse Régionale des Valeurs Mobilières, UEMOA),
traitées par brvm-py et mises à jour chaque jour de séance. Montants en FCFA.
Règles à garder en tête : un titre qui n'échange pas un jour n'a pas de ligne ce jour-là ;
la variation d'un titre est limitée à ±7,5 % par séance ; un ordre passé en J s'exécute au mieux en J+1.
Appeler `derniere_seance` pour connaître la fraîcheur des données avant de commenter un cours.
Les résultats ne constituent pas un conseil en investissement."""

serveur = _Serveur("brvm", instructions=INSTRUCTIONS)


def _ticker(code: str) -> str:
    return brvm.resoudre(code)


def _periode(df: pd.DataFrame, debut: str | None, fin: str | None) -> pd.DataFrame:
    if debut:
        df = df[df.index >= pd.Timestamp(debut)]
    if fin:
        df = df[df.index <= pd.Timestamp(fin)]
    return df


def _cloture_indice(code: str) -> pd.Series:
    df = brvm.indice(code)
    col = "cloture" if "cloture" in df.columns else df.columns[-1]
    return df[col]


@serveur.tool()
def derniere_seance() -> dict:
    """Date de la dernière séance disponible, si elle est close, et opérations sur titres appliquées."""
    i = brvm.infos()
    return {k: i.get(k) for k in ("derniere_seance", "derniere_seance_close", "releve_cours",
                                  "exporte_le", "operations_titres", "taux_irvm_pct")}


@serveur.tool()
def rechercher_societe(texte: str) -> list[dict]:
    """Trouve des sociétés cotées par nom, code, secteur ou pays (ex. « banque », « Sénégal », « Orange »)."""
    s = brvm.societes()
    t = texte.strip().lower()
    champs = ["code", "nom", "secteur", "pays"]
    masque = s[champs].astype(str).apply(lambda col: col.str.lower().str.contains(t, regex=False)).any(axis=1)
    res = s[masque]
    if res.empty:
        noms = s["nom"].astype(str).tolist()
        proches = difflib.get_close_matches(texte.upper(), noms, n=5, cutoff=0.5)
        res = s[s["nom"].isin(proches)]
    cols = ["code", "nom", "pays", "secteur", "dernier_cours", "capitalisation_fcfa"]
    return res[[c for c in cols if c in res.columns]].astype(object).where(res.notna(), None).to_dict("records")


@serveur.tool()
def fiche_societe(ticker: str) -> dict:
    """Fiche d'une société : nom, ISIN, pays, secteur, nombre de titres, flottant, capitalisation, description."""
    f = dict(brvm.societe(_ticker(ticker)))
    return {k: (v.item() if hasattr(v, "item") else v) for k, v in f.items()
            if k not in ("adresse", "telephone")}


@serveur.tool()
def cours(ticker: str, debut: str | None = None, fin: str | None = None,
          frequence: Literal["jour", "semaine", "mois"] = "jour", max_lignes: int = 60) -> dict:
    """Cours d'une action (ouverture, plus haut, plus bas, clôture, volumes) ; dates au format AAAA-MM-JJ.

    Renvoie les `max_lignes` dernières lignes de la période. Les jours sans échange n'ont pas de ligne."""
    df = _periode(brvm.cours(_ticker(ticker)), debut, fin)
    df = analyse.reechantillonner(df, frequence)
    return {"ticker": _ticker(ticker), "frequence": frequence, **analyse.table(df, max_lignes)}


@serveur.tool()
def indice(code: str = "BRVMC", debut: str | None = None, fin: str | None = None,
           max_lignes: int = 60) -> dict:
    """Valeurs d'un indice : BRVMC (composite), BRVM30, BRVMPR (prestige), indices sectoriels (BRVM_SF, BRVM_TEL…)."""
    df = _periode(brvm.indice(code), debut, fin)
    return {"indice": code, **analyse.table(df, max_lignes)}


@serveur.tool()
def liste_indices() -> dict:
    """Indices disponibles, avec nom, ISIN et période couverte."""
    return analyse.table(brvm.indices(), 100)


@serveur.tool()
def dividendes(ticker: str, profil: Literal["particulier", "institutionnel"] = "particulier") -> dict:
    """Dividendes passés et à venir d'une action, nets d'IRVM selon le profil, avec leur contrôle de cohérence."""
    df = brvm.dividendes(_ticker(ticker), profil=profil)
    cols = ["exercice", "statut", "date_detachement", "date_paiement", "montant_net_fcfa",
            "montant_brut_fcfa", "rapport_division", "retenu"]
    return analyse.table(df[[c for c in cols if c in df.columns]], 40)


@serveur.tool()
def fondamentaux(ticker: str) -> dict:
    """Comptes par exercice (chiffre d'affaires, résultat net, BNPA, dividende), avec PER et rendement
    recalculés au dernier cours connu."""
    t = _ticker(ticker)
    df = brvm.fondamentaux(t).copy()
    dernier = brvm.cours(t)["cloture"].dropna()
    if len(dernier) and "bnpa_fcfa" in df:
        px = float(dernier.iloc[-1])
        df["per_au_dernier_cours"] = (px / df["bnpa_fcfa"]).where(df["bnpa_fcfa"] > 0).round(2)
        if "dividende_fcfa" in df:
            df["rendement_au_dernier_cours_pct"] = (df["dividende_fcfa"] / px * 100).round(2)
    return {"ticker": t, "dernier_cours_fcfa": float(dernier.iloc[-1]) if len(dernier) else None,
            **analyse.table(df.set_index("exercice") if "exercice" in df else df, 20)}


@serveur.tool()
def performance_risque(ticker: str, debut: str | None = None, fin: str | None = None,
                       reference: str = "BRVMC", taux_sans_risque: float = 0.0) -> dict:
    """Performance et risque d'une action sur une période : rendement, volatilité, Sharpe, Sortino,
    VaR et CVaR historiques à 95 % sur un jour, perte maximale, bêta face à un indice, liquidité.

    `taux_sans_risque` est annuel en décimal (0.06 pour 6 %). Sans `debut`, les 3 dernières années."""
    t = _ticker(ticker)
    df = brvm.cours(t)
    if not debut:
        debut = str((df.index.max() - pd.DateOffset(years=3)).date())
    df = _periode(df, debut, fin)
    ref = _periode(_cloture_indice(reference).to_frame("c"), debut, fin)["c"]
    seances = brvm.seances()
    seances = pd.to_datetime(pd.Series(seances.index if isinstance(seances, pd.DataFrame) else seances))
    n_cal = int(((seances >= df.index.min()) & (seances <= df.index.max())).sum()) if len(df) else None
    return {"ticker": t, "indice_reference": reference,
            **analyse.mesures(df, ref, taux_sans_risque, n_cal)}


@serveur.tool()
def comparer(tickers: list[str], debut: str | None = None, reference: str = "BRVMC") -> list[dict]:
    """Compare plusieurs actions sur la même période (rendement, volatilité, Sharpe, VaR, perte max, bêta)."""
    lignes = []
    for code in tickers[:15]:
        m = performance_risque(code, debut=debut, reference=reference)
        lignes.append({
            "ticker": m.get("ticker"), "rendement_total_pct": m.get("rendement_total_pct"),
            "volatilite_annualisee_pct": m.get("volatilite_annualisee_pct"), "sharpe": m.get("sharpe"),
            "var_95_1j_pct": m.get("var_95_1j_pct"), "perte_max_pct": m.get("perte_max_pct"),
            "beta": (m.get("reference") or {}).get("beta"),
            "part_seances_echangees_pct": m.get("part_seances_echangees_pct"),
        })
    return lignes


@serveur.tool()
def palmares(seances: int = 20, nombre: int = 5) -> dict:
    """Plus fortes hausses et baisses de la cote sur les `seances` dernières séances de la place."""
    pan = brvm.panneau("cloture")
    pan = pan.tail(seances + 1)
    debut = pan.ffill().iloc[0]
    fin = pan.ffill().iloc[-1]
    var = ((fin / debut - 1) * 100).dropna().round(2).sort_values()
    return {"du": str(pan.index[0].date()), "au": str(pan.index[-1].date()),
            "hausses_pct": var.tail(nombre)[::-1].to_dict(), "baisses_pct": var.head(nombre).to_dict()}


@serveur.tool()
def correlations(tickers: list[str], debut: str | None = None) -> dict:
    """Matrice de corrélation des rendements quotidiens sur les dates communes d'échange (31 au minimum)."""
    codes = [_ticker(t) for t in tickers[:12]]
    pan = brvm.panneau("cloture", codes)
    if debut:
        pan = pan[pan.index >= pd.Timestamp(debut)]
    r = pan.pct_change(fill_method=None)
    corr = r.corr(min_periods=31).round(3)
    return {"tickers": codes, "matrice": corr.astype(object).where(corr.notna(), None).values.tolist()}


def main() -> None:
    serveur.run()


if __name__ == "__main__":
    main()
