"""Serveur MCP BRVM : expose les données de brvm-py et des mesures de risque à un assistant IA."""
from __future__ import annotations

import difflib
import unicodedata
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
Pour un chiffre tiré d'un rapport (`chiffres`), citer le document : `detail=True` donne la page et le lien du PDF.
Les outils `performances`, `risque`, `valorisation`, `ratios` et `etat_du_marche` suivent les conventions
de l'application BRVM Analytics ; `etat_du_marche` décrit le marché et ne constitue pas un signal.
Les résultats ne constituent pas un conseil en investissement."""

serveur = _Serveur("brvm", instructions=INSTRUCTIONS)


def _sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(texte)) if not unicodedata.combining(c)).lower()


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


# ---------------------------------------------------------------------------
# Rapports des sociétés et composition des indices (brvm-py 0.1 et suivants)
# ---------------------------------------------------------------------------

TYPES_RAPPORTS = ("etats_financiers", "rapport_activite", "rapport_annuel", "rapport_semestriel",
                  "rapport_cac", "rse")


@serveur.tool()
def rapports(ticker: str, type: str | None = None, exercice: int | None = None,
             periode: Literal["A", "S1", "T1", "T3", "T4"] | None = None, max_lignes: int = 30) -> dict:
    """Rapports publiés par une société cotée sur brvm.org, avec le lien du PDF (les `max_lignes` plus récents).

    `type` : etats_financiers, rapport_activite, rapport_annuel, rapport_semestriel, rapport_cac (commissaires
    aux comptes) ou rse. `periode` : A (annuel), S1 (premier semestre), T1, T3, T4 (trimestres).
    `chiffres_lus` compte les chiffres de l'outil `chiffres` tirés de ce document."""
    if type is not None and type not in TYPES_RAPPORTS:
        raise ValueError(f"type inconnu {type!r}, choisir parmi {TYPES_RAPPORTS}")
    t = _ticker(ticker)
    df = brvm.rapports(t, type=type, exercice=exercice, periode=periode)
    df = df.sort_values(["exercice", "date_publication"], na_position="first", kind="stable")
    df = df.reset_index(drop=True)
    cols = ["date_publication", "exercice", "periode", "type", "statut", "titre", "pages", "chiffres_lus", "url"]
    return {"ticker": t, **analyse.table(df[[c for c in cols if c in df.columns]], max_lignes)}


@serveur.tool()
def chiffres(ticker: str, indicateurs: list[str] | None = None, exercice: int | None = None,
             periode: Literal["A", "S1", "T1", "T3", "T4"] | None = None, detail: bool = False,
             max_lignes: int = 40) -> dict:
    """Chiffres lus dans les rapports officiels d'une société (états financiers, rapports d'activité), en
    millions de FCFA : annuels (A), semestriels (S1) et trimestriels (T1, T3, T4).

    Seules les lectures fiables sont publiées (contrôlées face à Sikafinance quand c'est possible). Les
    montants infra-annuels sont ceux publiés, en général cumulés depuis le début de l'exercice.
    Indicateurs : chiffre_affaires, produit_net_bancaire, resultat_net, resultat_avant_impot,
    resultat_exploitation, excedent_brut_exploitation, impot_resultat, total_bilan, capitaux_propres,
    depots_clientele, credits_clientele, cout_du_risque, dettes_financieres, flux_tresorerie_operationnel…
    Par défaut un tableau par exercice et période, une colonne par indicateur ; `detail=True` donne une
    ligne par chiffre avec son contrôle, la page et le lien du PDF, pour vérifier une valeur."""
    t = _ticker(ticker)
    if detail:
        df = brvm.chiffres(t, indicateur=indicateurs, exercice=exercice, periode=periode)
        cols = ["exercice", "periode", "indicateur", "valeur_mfcfa", "controle", "statut", "date_publication",
                "page", "libelle", "lectures", "url"]
        df = df[[c for c in cols if c in df.columns]]
    else:
        df = brvm.chiffres(t, indicateur=indicateurs, exercice=exercice, periode=periode, large=True)
        df = df.drop(columns=["ticker"], errors="ignore").dropna(axis=1, how="all")
    return {"ticker": t, "unite": "millions de FCFA", **analyse.table(df, max_lignes)}


INDICES_COMPOSITION = ("BRVMC", "BRVM_CB", "BRVM_CD", "BRVM_EN", "BRVM_IN", "BRVM_SF", "BRVM_TEL")


@serveur.tool()
def composition(indice: str = "BRVMC", date: str | None = None, nombre: int = 15) -> dict:
    """Poids des actions dans un indice à une séance (la dernière par défaut), du plus lourd au plus léger, en %.

    Indices couverts : BRVMC (toute la cote) et les sectoriels BRVM_CB, BRVM_CD, BRVM_EN, BRVM_IN, BRVM_SF,
    BRVM_TEL. Poids = capitalisation du titre / capitalisation de l'indice, au dernier cours connu ; ils
    reproduisent les rendements publiés à moins d'un point de base près en médiane. Le BRVM 30 et le BRVM
    Prestige ne sont pas couverts (liste de leurs membres non publiée)."""
    p = brvm.composition(indice, date=date or "2100-01-01")
    noms = brvm.societes()["nom"]
    tete = p.head(nombre)
    return {"indice": str(indice).upper(), "seance": str(pd.Timestamp(p.name).date()),
            "titres_dans_indice": int(len(p)),
            "poids_pct": [{"ticker": t, "nom": noms.get(t), "poids_pct": round(float(w) * 100, 2)}
                          for t, w in tete.items()],
            "reste_pct": round(float(p.iloc[nombre:].sum()) * 100, 2),
            "concentration_5_premiers_pct": round(float(p.head(5).sum()) * 100, 2)}


# ---------------------------------------------------------------------------
# Mesures aux conventions de BRVM Analytics (brvm.mesures)
# ---------------------------------------------------------------------------

def _mesures():
    """Le module brvm.mesures, ou une erreur claire si la version installée de brvm-py ne l'a pas."""
    try:
        from brvm import mesures
    except ImportError as exc:  # brvm-py sans le module mesures
        raise RuntimeError("Cette mesure demande brvm.mesures, absent de la version installée de brvm-py : "
                           "mettre brvm-py à jour.") from exc
    return mesures


Frequence = Literal["semaine", "seance"]


def _f(frequence: str) -> str:
    return "J" if frequence == "seance" else "S"


@serveur.tool()
def performances(tickers: list[str] | None = None, fin: str | None = None, dividendes: bool = False,
                 annualise: bool = False) -> dict:
    """Rendements en % sur les périodes de BRVM Analytics, une ligne par titre (toutes les actions par défaut ;
    on peut aussi passer des indices comme BRVMC).

    Colonnes : SEM, MOIS, TRIM, AN (semaine, mois, trimestre, année en cours) puis 1S, 1M, 3M, 6M, 1A, 3A, 5A,
    10A (périodes glissantes jusqu'à `fin`). `dividendes=True` : dividendes nets réinvestis (rendement total).
    `annualise=True` : rythme annuel au-delà d'un an. Vide quand le titre n'était pas coté au début."""
    m = _mesures()
    codes = [_ticker(t) for t in tickers[:60]] if tickers else None
    df = m.performances(codes, fin=fin, dividendes=dividendes, annualise=annualise)
    bases = {k: (str(v.date()) if v is not None and pd.notna(v) else None) for k, v in df.attrs["bases"].items()}
    return {"fin": str(df.attrs["fin"].date()), "dividendes_reinvestis": dividendes, "annualise": annualise,
            "unite": "%", "seances_de_base": bases, **analyse.table(analyse.en_pct(df), 100)}


@serveur.tool()
def rendement_total(ticker: str, debut: str | None = None, fin: str | None = None,
                    profil: Literal["particulier", "institutionnel"] = "particulier") -> dict:
    """Rendement d'un placement dividendes nets d'IRVM réinvestis, comparé au seul cours, sur une période.

    Renvoie la valeur finale en base 100, le rendement du cours, la part due aux dividendes, le nombre de
    dividendes crédités (seuls les dividendes contrôlés comme cohérents) et la valeur en fin de chaque année.
    Marche aussi pour BRVMC et les indices sectoriels (dividendes pondérés par la composition)."""
    df = _mesures().rendement_total(_ticker(ticker), debut=debut, fin=fin, profil=profil)
    val, px = df["valeur"], df["cloture"]
    jours = max((df.index[-1] - df.index[0]).days, 1)
    total = val.iloc[-1] / 100 - 1
    prix = px.iloc[-1] / px.iloc[0] - 1
    annuel = val.groupby(df.index.year).last().round(2)
    return analyse.propre({
        "ticker": _ticker(ticker), "profil": profil, "debut": df.attrs["debut"], "fin": df.attrs["fin"],
        "seances": df.attrs["seances"], "dividendes_credites": df.attrs["dividendes"],
        "valeur_finale_base_100": val.iloc[-1],
        "rendement_total_pct": total * 100, "rendement_du_cours_pct": prix * 100,
        "apport_des_dividendes_pct": (total - prix) * 100,
        "rendement_total_annualise_pct": ((1 + total) ** (365.25 / jours) - 1) * 100 if jours >= 365 else None,
        "valeur_fin_d_annee_base_100": {int(k): float(v) for k, v in annuel.items()},
    }, 2)


@serveur.tool()
def rendements_annuels(tickers: list[str], depuis: int = 2015, dividendes: bool = False) -> dict:
    """Rendement en % par année civile de chaque titre ou indice (dernière clôture de l'année face à celle
    de l'année précédente). L'année d'introduction en bourse est partielle et signalée."""
    m = _mesures()
    df = m.rendements_annuels([_ticker(t) for t in tickers[:30]], depuis=depuis, dividendes=dividendes)
    partielles = {t: a for t, a in df.attrs["partielles"].items() if a}
    df.columns = [str(c) for c in df.columns]
    return {"dividendes_reinvestis": dividendes, "unite": "%", "annees_partielles": partielles,
            **analyse.table(analyse.en_pct(df), 100)}


@serveur.tool()
def rendements_mensuels(ticker: str, dividendes: bool = False, annees: int = 10) -> dict:
    """Rendements mensuels en % d'un titre ou d'un indice (années en lignes, mois 1 à 12 en colonnes) et sa
    saisonnalité sur tout l'historique : rendement moyen, médian et part des années en hausse pour chaque mois.

    La saisonnalité décrit le passé ; avec une dizaine d'années, elle est rarement significative."""
    m = _mesures()
    t = _ticker(ticker)
    grille = m.rendements_mensuels(t, dividendes=dividendes)
    grille.columns = [str(c) for c in grille.columns]
    sais = m.saisonnalite(t, dividendes=dividendes)
    sais = analyse.en_pct(sais, ["moyenne", "mediane", "hausse"])
    sais.columns = ["moyenne_pct", "mediane_pct", "part_annees_en_hausse_pct", "annees"]
    return {"ticker": t, "dividendes_reinvestis": dividendes, "unite": "%",
            "grille": analyse.table(analyse.en_pct(grille), annees),
            "saisonnalite": analyse.table(sais, 12)}


@serveur.tool()
def risque(ticker: str, debut: str | None = None, fin: str | None = None, reference: str = "BRVMC",
           frequence: Frequence = "semaine", taux_sans_risque: float = 0.03, niveau_var: float = 0.95) -> dict:
    """Risque d'un titre aux conventions de BRVM Analytics, pour retrouver les chiffres de l'application :
    volatilité annualisée, VaR et CVaR historiques, perte maximale (dates, durée de reprise, perte courante)
    et bêta face à une référence (régression en excès du taux sans risque, intervalle à 95 %, R², alpha).

    Par défaut sur rendements hebdomadaires (vendredi à vendredi, racine de 52), cours reportés les jours sans
    échange ; `frequence="seance"` pour du quotidien (racine de 252). Pas de bêta sous 26 semaines ou 60
    séances communes. Pour des mesures entre séances d'échange seulement, voir `performance_risque`.
    Résultats en %, sauf bêta, R² et corrélation."""
    m = _mesures()
    t, f = _ticker(ticker), _f(frequence)
    vol = m.volatilite(t, debut=debut, fin=fin, frequence=f)
    v = m.var(t, niveau=niveau_var, debut=debut, fin=fin, frequence=f)
    pm = m.perte_maximale(t, debut=debut, fin=fin)
    b = m.beta(t, reference=_ticker(reference), debut=debut, fin=fin, frequence=f,
               taux_sans_risque=taux_sans_risque)
    pct = lambda x: None if x is None or pd.isna(x) else float(x) * 100  # noqa: E731
    return analyse.propre({
        "ticker": t, "frequence": vol["frequence"], "debut": vol["debut"], "fin": vol["fin"],
        "volatilite_annualisee_pct": pct(vol["volatilite"]), "rendements": vol["n"],
        "var_pct": pct(v["var"]), "cvar_pct": pct(v["cvar"]), "niveau_var": niveau_var,
        "horizon_var": "une semaine" if f == "S" else "une séance",
        "perte_maximale": {"perte_max_pct": pct(pm["perte_max"]), "perte_courante_pct": pct(pm["perte_courante"]),
                           "date_sommet": pm["date_sommet"], "date_creux": pm["date_creux"],
                           "date_reprise": pm["date_reprise"], "seances_baisse": pm["seances_baisse"],
                           "seances_reprise": pm["seances_reprise"],
                           "plus_longue_baisse_jours": pm["plus_longue_baisse_jours"]},
        "beta": {"reference": b["reference"], "beta": b["beta"], "ic_95": [b["ic_bas"], b["ic_haut"]],
                 "r2": b["r2"], "correlation": b["correlation"], "alpha_annuel_pct": pct(b["alpha"]),
                 "vol_specifique_pct": pct(b["vol_specifique"]), "lecture": b["lecture"],
                 "observations": b["n"]},
        "avertissement": "Mesures historiques ; elles ne préjugent pas des performances futures.",
    }, 3)


@serveur.tool()
def valorisation(tickers: list[str] | None = None, date: str | None = None, secteur: str | None = None) -> dict:
    """Multiples de marché datés : PER, cours / capitaux propres (pb), ROE, cours / chiffre d'affaires (PNB pour
    une banque), VE / EBE (hors banques) et rendement du dividende, au cours de `date` (dernière séance par
    défaut) avec les seuls comptes connus à cette date. Toutes les actions par défaut, ou un `secteur`
    (Services Financiers, Consommation De Base, Consommation Discretionnaire, Industriels, Energie,
    Telecommunications, Services Publics, Transport).

    Un multiple manque quand son dénominateur est négatif ou nul, ou qu'il sort de bornes plausibles
    (chiffre probablement mal lu). Montants en millions de FCFA ; roe et rendement en %."""
    m = _mesures()
    codes = [_ticker(t) for t in tickers[:60]] if tickers else None
    df = m.valorisation(codes, date=date)
    seance = df.attrs.get("date")
    if secteur:
        cle = _sans_accents(secteur)
        df = df[df["secteur"].astype(str).map(_sans_accents).str.contains(cle, regex=False)]
    cols = ["nom", "secteur", "date_cours", "cours", "capitalisation_mfcfa", "exercice", "date_connue",
            "resultat_net_mfcfa", "bnpa_fcfa", "dividende_net_fcfa", "per", "pb", "roe", "p_ca", "ve_ebe", "rendement"]
    df = analyse.en_pct(df[[c for c in cols if c in df.columns]], ["roe", "rendement"])
    df = df.rename(columns={"roe": "roe_pct", "rendement": "rendement_pct"})
    return {"seance": str(pd.Timestamp(seance).date()) if seance is not None else None, **analyse.table(df, 100)}


@serveur.tool()
def ratios(ticker: str, exercices: int = 8) -> dict:
    """Comptes annuels et ratios d'une société, un exercice par ligne (montants en millions de FCFA, ratios
    en %) : croissance du chiffre d'affaires et du résultat, marge nette, ROE, ROA, taux d'impôt, taux de
    distribution ; pour une banque coefficient d'exploitation, coût du risque / PNB, crédits / dépôts, fonds
    propres / bilan ; sinon marge d'EBE, marge d'exploitation, endettement, dette nette / EBE, conversion
    en trésorerie et flux libre. Sources de chaque chiffre dans source_ca et source_rn."""
    m = _mesures()
    df = m.ratios(_ticker(ticker))
    fr = ["croissance_ca", "croissance_rn", "marge_nette", "roe", "roa", "taux_impot", "taux_distribution",
          "coef_exploitation", "cout_risque_pnb", "credits_depots", "fonds_propres_bilan", "marge_ebe",
          "marge_exploitation", "endettement", "conversion"]
    df = analyse.en_pct(df, fr).rename(columns={c: f"{c}_pct" for c in fr})
    df = df.dropna(axis=1, how="all")
    return {"ticker": _ticker(ticker), "banque": bool(df.attrs.get("financier", False)),
            **analyse.table(df, exercices)}


@serveur.tool()
def etat_du_marche(indice: str = "BRVMC", historique_seances: int = 0) -> dict:
    """Description de l'état du marché, méthodes de BRVM Analytics : régime de tendance de l'indice (moyennes
    50 et 200 filtrées : Strong Bull, Correction, Transition haussière, Transition baissière, Rebond,
    Strong Bear) depuis quand, participation (part des actions au-dessus de leur moyenne 200 séances) et
    Fear & Greed BRVM (humeur de 0, peur extrême, à 100, cupidité extrême, avec ses trois piliers).

    Ce sont des mesures descriptives du passé récent, pas des signaux d'achat ou de vente.
    `historique_seances` > 0 ajoute les dernières valeurs de chaque série."""
    m = _mesures()
    c = _ticker(indice)
    reg = m.regime(c)
    part = m.participation().dropna()
    fg = m.fear_greed().dropna(subset=["score"])
    dernier = fg.iloc[-1]
    changements = reg["regime"].dropna()
    episodes = changements[changements != changements.shift()].tail(6)
    res = {
        "indice": c,
        "regime": {"actuel": reg.attrs["regime_actuel"], "depuis": reg.attrs["depuis"],
                   "seances_depuis": reg.attrs["seances_depuis"],
                   "episodes_recents": [{"debut": d, "regime": r} for d, r in episodes.items()]},
        "participation_mm200_pct": {"seance": part.index[-1], "valeur": float(part.iloc[-1]),
                                    "lecture": "faible" if part.iloc[-1] <= 40 else
                                    "large" if part.iloc[-1] >= 60 else "intermédiaire"},
        "fear_greed": {"seance": fg.index[-1], "score": float(dernier["score"]), "libelle": dernier["libelle"],
                       "piliers": {k.replace("pilier_", ""): float(dernier[k])
                                   for k in fg.columns if k.startswith("pilier_")},
                       "il_y_a_1_mois": float(fg["score"].iloc[-22]) if len(fg) > 22 else None},
    }
    if historique_seances > 0:
        n = int(historique_seances)
        h = pd.concat([reg["regime"], part.rename("participation_pct"), fg["score"].rename("fear_greed")], axis=1)
        res["historique"] = analyse.table(h.dropna(how="all").tail(n), n)
    return analyse.propre(res, 2)


def main() -> None:
    serveur.run()


if __name__ == "__main__":
    main()
