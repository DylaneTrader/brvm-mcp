"""Mesures de performance et de risque adaptées à la BRVM.

Fonctions pures sur des séries pandas, sans accès réseau : elles se testent seules.
Conventions : 252 séances par an, rendements calculés entre deux séances où le titre a
échangé (un jour sans échange n'a pas de ligne et ne compte pas comme un rendement nul).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

SEANCES_PAR_AN = 252


def _arrondi(x, n=4):
    if x is None:
        return None
    try:
        if isinstance(x, (float, np.floating)) and (math.isnan(x) or math.isinf(x)):
            return None
    except TypeError:
        pass
    return round(float(x), n)


def rendements(cloture: pd.Series) -> pd.Series:
    """Rendements simples entre séances d'échange successives."""
    c = cloture.dropna().astype(float)
    c = c[c > 0]
    return c.pct_change().dropna()


def perte_maximale(cloture: pd.Series) -> dict:
    """Perte maximale depuis un plus haut, avec ses dates."""
    c = cloture.dropna().astype(float)
    if len(c) < 2:
        return {"perte_max_pct": None, "sommet": None, "creux": None}
    sommets = c.cummax()
    baisse = c / sommets - 1
    creux = baisse.idxmin()
    sommet = c.loc[:creux].idxmax()
    return {
        "perte_max_pct": _arrondi(baisse.min() * 100, 2),
        "sommet": str(pd.Timestamp(sommet).date()),
        "creux": str(pd.Timestamp(creux).date()),
    }


def var_cvar(r: pd.Series, niveau: float = 0.95) -> tuple[float | None, float | None]:
    """VaR et CVaR historiques sur un jour, en perte positive (en %)."""
    r = r.dropna()
    if len(r) < 30:
        return None, None
    seuil = r.quantile(1 - niveau)
    queue = r[r <= seuil]
    return _arrondi(-seuil * 100, 2), _arrondi(-queue.mean() * 100, 2)


def beta(r_titre: pd.Series, r_ref: pd.Series) -> dict:
    """Bêta et corrélation sur les dates communes (minimum 31 observations)."""
    df = pd.concat([r_titre, r_ref], axis=1, join="inner").dropna()
    if len(df) < 31:
        return {"beta": None, "correlation": None, "observations": len(df)}
    a, b = df.iloc[:, 0], df.iloc[:, 1]
    var_ref = b.var()
    return {
        "beta": _arrondi(a.cov(b) / var_ref, 3) if var_ref > 0 else None,
        "correlation": _arrondi(a.corr(b), 3),
        "observations": int(len(df)),
    }


def mesures(cours: pd.DataFrame, reference: pd.Series | None = None,
            taux_sans_risque: float = 0.0, seances_calendrier: int | None = None) -> dict:
    """Performance, risque et liquidité d'un titre sur la période des cours fournis.

    `cours` a un index de dates et les colonnes `cloture` et, si disponible, `volume_fcfa`.
    `reference` est la série de clôture d'un indice (BRVMC par défaut côté serveur).
    `taux_sans_risque` est annuel, en décimal (0.06 pour 6 %).
    `seances_calendrier` est le nombre de séances de la place sur la période, pour mesurer
    la part de séances où le titre a échangé.
    """
    c = cours["cloture"].dropna().astype(float)
    if len(c) < 2:
        return {"erreur": "Moins de deux séances d'échange sur la période."}
    r = rendements(c)
    debut, fin = c.index[0], c.index[-1]
    jours = max((pd.Timestamp(fin) - pd.Timestamp(debut)).days, 1)
    total = c.iloc[-1] / c.iloc[0] - 1
    annualise = (1 + total) ** (365.25 / jours) - 1 if total > -1 else None
    vol = r.std() * math.sqrt(SEANCES_PAR_AN) if len(r) > 1 else None
    rf_jour = (1 + taux_sans_risque) ** (1 / SEANCES_PAR_AN) - 1
    exces = r - rf_jour
    sharpe = exces.mean() / r.std() * math.sqrt(SEANCES_PAR_AN) if len(r) > 1 and r.std() > 0 else None
    neg = exces[exces < 0]
    dd = math.sqrt((neg ** 2).sum() / len(exces)) if len(exces) else 0
    sortino = exces.mean() / dd * math.sqrt(SEANCES_PAR_AN) if dd > 0 else None
    var95, cvar95 = var_cvar(r)
    res = {
        "periode": {"debut": str(pd.Timestamp(debut).date()), "fin": str(pd.Timestamp(fin).date()),
                    "seances_echangees": int(len(c))},
        "dernier_cours_fcfa": _arrondi(c.iloc[-1], 2),
        "rendement_total_pct": _arrondi(total * 100, 2),
        "rendement_annualise_pct": _arrondi(annualise * 100, 2) if annualise is not None else None,
        "volatilite_annualisee_pct": _arrondi(vol * 100, 2) if vol is not None else None,
        "sharpe": _arrondi(sharpe, 2),
        "sortino": _arrondi(sortino, 2),
        "var_95_1j_pct": var95,
        "cvar_95_1j_pct": cvar95,
        **perte_maximale(c),
        "seances_a_la_limite_7_5_pct": int((r.abs() >= 0.0745).sum()),
    }
    if seances_calendrier:
        res["part_seances_echangees_pct"] = _arrondi(len(c) / seances_calendrier * 100, 1)
    if "volume_fcfa" in cours:
        v = cours["volume_fcfa"].dropna()
        res["volume_median_fcfa"] = _arrondi(v.median(), 0) if len(v) else None
    if reference is not None:
        ref = reference.dropna().astype(float)
        ref = ref[(ref.index >= debut) & (ref.index <= fin)]
        res["reference"] = beta(r, rendements(ref))
        if len(ref) >= 2:
            res["reference"]["rendement_total_pct"] = _arrondi((ref.iloc[-1] / ref.iloc[0] - 1) * 100, 2)
    res["avertissement"] = ("Mesures historiques sur cours de clôture, sans dividendes. "
                            "Elles ne préjugent pas des performances futures.")
    return res


def reechantillonner(cours: pd.DataFrame, frequence: str) -> pd.DataFrame:
    """Barres hebdomadaires ou mensuelles ; une période sans échange n'a pas de ligne."""
    regle = {"semaine": "W-FRI", "mois": "ME"}.get(frequence)
    if regle is None:
        return cours
    agg = {"ouverture": "first", "plus_haut": "max", "plus_bas": "min", "cloture": "last",
           "volume_titres": "sum", "volume_fcfa": "sum"}
    agg = {k: v for k, v in agg.items() if k in cours.columns}
    try:
        out = cours.resample(regle).agg(agg)
    except ValueError:  # pandas < 2.2 : "M" au lieu de "ME"
        out = cours.resample(regle.replace("ME", "M")).agg(agg)
    out = out.dropna(subset=["cloture"])
    out["variation_pct"] = out["cloture"].pct_change().mul(100).round(2)
    return out


def table(df: pd.DataFrame, max_lignes: int = 60) -> dict:
    """Tableau compact pour un assistant : colonnes, dernières lignes, dates ISO."""
    d = df.tail(max_lignes)
    d = d.reset_index(drop=isinstance(d.index, pd.RangeIndex))
    for col in d.columns:
        if pd.api.types.is_datetime64_any_dtype(d[col]):
            d[col] = d[col].dt.strftime("%Y-%m-%d")
    d = d.astype(object).where(pd.notna(d), None)
    lignes = [[_arrondi(x, 4) if isinstance(x, (float, np.floating)) else
               (x.item() if hasattr(x, "item") else x) for x in row] for row in d.values.tolist()]
    return {"colonnes": [str(c) for c in d.columns], "lignes": lignes,
            "lignes_total": int(len(df)), "lignes_montrees": int(len(d))}
