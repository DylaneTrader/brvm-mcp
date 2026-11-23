"""Page publique de brvm-mcp : présentation du serveur et séance du jour vue par ses outils.

Chaque bloc de la page est la réponse d'un outil MCP du serveur, appelé comme le ferait un assistant IA
(`derniere_seance`, `indice`, `palmares`, `comparer`). Les réponses brutes sont publiées à côté, en JSON.

La page contient aussi un chat : le visiteur saisit sa propre clé API Anthropic, Claude appelle les outils, et
ces outils tournent dans son navigateur (le vrai code Python du serveur, chargé par Pyodide dans
`statique/moteur.js`). Le site attend donc, dans le dossier de sortie :

- `paquets/*.whl` : les roues de brvm-py et de brvm-mcp (`pip wheel --no-deps`) ;
- `vendor/anthropic.mjs` : le SDK TypeScript d'Anthropic mis en un seul module (esbuild).

    python page/publier.py --sortie site

Le workflow `.github/workflows/page.yml` le relance chaque jour de séance et publie le site sur GitHub Pages.
"""
from __future__ import annotations

import argparse
import asyncio
import html
import json
import shutil
from pathlib import Path

import pandas as pd

import brvm
from brvm_mcp import serveur as S

INDICES = [("BRVMC", "BRVM Composite"), ("BRVM30", "BRVM 30"), ("BRVMPR", "BRVM Prestige")]
OUTILS = [
    ("derniere_seance", "Date et état (close ou provisoire) de la dernière séance, opérations sur titres appliquées"),
    ("rechercher_societe", "Sociétés par nom, code, secteur ou pays"),
    ("fiche_societe", "ISIN, pays, secteur, nombre de titres, flottant, capitalisation, description"),
    ("cours", "Cours quotidiens, hebdomadaires ou mensuels d'une action"),
    ("indice", "BRVM Composite, BRVM 30, Prestige, indices sectoriels"),
    ("liste_indices", "Les indices disponibles et leur historique"),
    ("dividendes", "Dividendes nets d'IRVM (particulier ou institutionnel) et leur contrôle de cohérence"),
    ("fondamentaux", "Comptes par exercice, PER et rendement recalculés au dernier cours"),
    ("performance_risque", "Rendement, volatilité, Sharpe, Sortino, VaR et CVaR, perte maximale, bêta, liquidité"),
    ("comparer", "Les mêmes mesures pour plusieurs actions côte à côte"),
    ("palmares", "Plus fortes hausses et baisses sur N séances"),
    ("correlations", "Matrice de corrélation sur les dates communes d'échange"),
]
INSTALL = {
    "Claude Code": "claude mcp add brvm -- uvx --from git+https://github.com/DylaneTrader/brvm-mcp brvm-mcp",
    "Claude Desktop (claude_desktop_config.json)": json.dumps({"mcpServers": {"brvm": {
        "command": "uvx", "args": ["--from", "git+https://github.com/DylaneTrader/brvm-mcp", "brvm-mcp"]}}},
        indent=2),
    "Ligne de commande (uv)": "uvx --from git+https://github.com/DylaneTrader/brvm-mcp brvm-mcp",
}
def _fr(x, d=2, signe=False) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "n.d."
    s = f"{x:+,.{d}f}" if signe else f"{x:,.{d}f}"
    return s.replace(",", " ").replace(".", ",")


def _classe(x) -> str:
    return "" if x is None or pd.isna(x) else ("hausse" if x > 0 else "baisse" if x < 0 else "")


def collecter() -> dict:
    seance = S.derniere_seance()
    fin = pd.Timestamp(seance["derniere_seance"])
    debut_an = f"{fin.year}-01-01"
    debut_1a = str((fin - pd.DateOffset(years=1)).date())
    noms = brvm.societes()
    if "ticker" in noms:
        noms = noms.set_index("ticker")
    indices = {}
    for code, _ in INDICES:
        r = S.indice(code, debut=str((fin - pd.DateOffset(years=1, days=10)).date()), max_lignes=400)
        df = pd.DataFrame(r["lignes"], columns=r["colonnes"]).set_index("date")
        df.index = pd.to_datetime(df.index)
        indices[code] = df
    grandes = (noms["capitalisation_fcfa"].dropna().sort_values(ascending=False).head(6).index.tolist())
    return {
        "derniere_seance": seance,
        "indices": indices,
        "palmares": S.palmares(seances=20, nombre=5),
        "comparer": S.comparer(grandes, debut=debut_1a),
        "appel_comparer": {"tickers": grandes, "debut": debut_1a},
        "debut_an": debut_an,
        "noms": noms["nom"].to_dict(),
    }


ICI = Path(__file__).resolve().parent
FAMILLES = {
    "derniere_seance": "Marché", "liste_indices": "Marché", "indice": "Marché", "palmares": "Marché",
    "rechercher_societe": "Sociétés", "fiche_societe": "Sociétés", "fondamentaux": "Sociétés",
    "dividendes": "Sociétés", "cours": "Cours",
    "performance_risque": "Risque", "comparer": "Risque", "correlations": "Risque",
}
QUESTIONS_CHAT = [
    "Quelle est la dernière séance disponible, et comment a fini le BRVM Composite ?",
    "Quelles actions ont le plus monté et le plus baissé sur les 20 dernières séances ?",
    "Compare Sonatel, Orange CI et SGB CI sur un an : rendement, volatilité, perte maximale et bêta.",
    "Quelles banques sont cotées au Sénégal, et quel est leur PER au dernier cours ?",
]


def _x(s: str) -> str:
    return html.escape(str(s), quote=True)


def _echelle(vals: list[float], marge: float = 0.06) -> tuple[float, float]:
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * marge or 1.0
    return lo - pad, hi + pad


def _svg_courbe(s: pd.Series, ident: str) -> str:
    """Grand graphique en aire : valeur de l'indice sur un an, axes en français."""
    s = s.dropna()
    L, H, g, d, h, b = 900, 470, 58, 14, 22, 30
    w, hh = L - g - d, H - h - b
    lo, hi = _echelle([float(v) for v in s])
    x = lambda i: g + w * i / max(len(s) - 1, 1)  # noqa: E731
    y = lambda v: h + hh * (1 - (v - lo) / (hi - lo))  # noqa: E731
    p = [f'<svg viewBox="0 0 {L} {H}" class="courbe" role="img" aria-label="Évolution sur un an">',
         f'<defs><linearGradient id="{ident}" x1="0" x2="0" y1="0" y2="1">'
         '<stop offset="0" stop-color="var(--accent)" stop-opacity=".28"/>'
         '<stop offset="1" stop-color="var(--accent)" stop-opacity="0"/></linearGradient></defs>']
    for k in range(5):
        v = lo + (hi - lo) * (k + .5) / 5
        p.append(f'<line x1="{g}" x2="{L - d}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grille"/>'
                 f'<text x="{g - 8}" y="{y(v) + 4:.1f}" text-anchor="end" class="ax">{_fr(v, 0)}</text>')
    pts = [f"{x(i):.1f},{y(float(v)):.1f}" for i, v in enumerate(s)]
    p.append(f'<polygon points="{g:.1f},{h + hh} {" ".join(pts)} {x(len(s) - 1):.1f},{h + hh}" fill="url(#{ident})"/>')
    p.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="var(--accent)" stroke-width="2.2" '
             'stroke-linejoin="round"/>')
    i_max = int(s.values.argmax())
    p.append(f'<circle cx="{x(len(s) - 1):.1f}" cy="{y(float(s.iloc[-1])):.1f}" r="4.5" fill="var(--accent)"/>')
    p.append(f'<text x="{x(i_max):.1f}" y="{y(float(s.iloc[i_max])) - 9:.1f}" text-anchor="middle" class="ax fort">'
             f'plus haut {_fr(float(s.iloc[i_max]), 2)}</text>')
    mois = s.index.to_period("M")
    noms_mois = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
    for i in range(1, len(s)):
        if mois[i] != mois[i - 1] and mois[i].month % 2 == 1:
            p.append(f'<text x="{x(i):.1f}" y="{H - 8}" text-anchor="middle" class="ax">'
                     f'{noms_mois[mois[i].month - 1]} {str(mois[i].year)[2:]}</text>')
    p.append("</svg>")
    return "".join(p)


def _svg_tendance(s: pd.Series) -> str:
    """Petite courbe d'une carte d'indice (trois derniers mois)."""
    s = s.dropna().tail(63)
    L, H = 220, 56
    lo, hi = _echelle([float(v) for v in s], .1)
    pts = " ".join(f"{L * i / max(len(s) - 1, 1):.1f},{H * (1 - (float(v) - lo) / (hi - lo)):.1f}"
                   for i, v in enumerate(s))
    sens = "hausse" if s.iloc[-1] >= s.iloc[0] else "baisse"
    return (f'<svg viewBox="0 0 {L} {H}" class="tendance {sens}" preserveAspectRatio="none" aria-hidden="true">'
            f'<polyline points="{pts}" fill="none" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>')


def _resume(s: pd.Series) -> str:
    """Chiffres clés de l'indice sur la fenêtre du graphique."""
    s = s.dropna()
    hi, lo, der = float(s.max()), float(s.min()), float(s.iloc[-1])
    r = s.pct_change().dropna()
    vol = float(r.std() * (252 ** .5) * 100)
    cases = [("Sur la période", _var((der / float(s.iloc[0]) - 1) * 100, 1)),
             ("Plus haut", f"{_fr(hi)}<small> le {s.idxmax():%d/%m}</small>"),
             ("Écart au plus haut", _var((der / hi - 1) * 100, 1)),
             ("Volatilité annualisée", f"{_fr(vol, 1)} %")]
    return '<dl class="resume">' + "".join(f"<div><dt>{a}</dt><dd>{b}</dd></div>" for a, b in cases) + "</dl>"


def _var(x, d=2) -> str:
    return f'<span class="{_classe(x)}">{_fr(x, d, True)} %</span>'


def _cartes_indices(c: dict) -> str:
    out = []
    for code, nom in INDICES:
        df = c["indices"][code]
        cl = df["cloture"]
        v20 = (cl.iloc[-1] / cl.iloc[-21] - 1) * 100 if len(cl) > 21 else None
        avant = cl[cl.index < pd.Timestamp(c["debut_an"])]
        van = (cl.iloc[-1] / avant.iloc[-1] - 1) * 100 if len(avant) else None
        v1 = df["variation_pct"].iloc[-1]
        out.append(f"""<article class="carte indice">
<header><span class="etiquette">{code}</span><h3>{_x(nom)}</h3></header>
<p class="valeur">{_fr(cl.iloc[-1])}</p>
<p class="jour">{_var(v1)} <small>sur la séance</small></p>
{_svg_tendance(cl)}
<dl><div><dt>20 séances</dt><dd>{_var(v20)}</dd></div><div><dt>Depuis le 1<sup>er</sup> janvier</dt><dd>{_var(van)}</dd></div></dl>
</article>""")
    return "".join(out)


def _palmares(c: dict) -> str:
    pal, noms = c["palmares"], c["noms"]
    tout = list(pal["hausses_pct"].values()) + list(pal["baisses_pct"].values())
    m = max((abs(v) for v in tout if v is not None), default=1) or 1

    def liste(d: dict) -> str:
        return "".join(
            f'<li><span class="nom">{_x(noms.get(t, t))}<small>{t.split(".")[0]}</small></span>'
            f'<span class="barre {_classe(v)}"><i style="width:{abs(v) / m * 100:.0f}%"></i></span>{_var(v, 1)}</li>'
            for t, v in d.items())
    return (f'<h4>Plus fortes hausses</h4><ol class="palmares">{liste(pal["hausses_pct"])}</ol>'
            f'<h4>Plus fortes baisses</h4><ol class="palmares">{liste(pal["baisses_pct"])}</ol>')


def _comparer(c: dict) -> str:
    noms = c["noms"]
    return "".join(
        f'<tr><th scope="row">{_x(noms.get(m["ticker"], m["ticker"]))}<small>{m["ticker"].split(".")[0]}</small></th>'
        f'<td>{_var(m["rendement_total_pct"], 1)}</td>'
        f'<td>{_fr(m["volatilite_annualisee_pct"], 1)} %</td><td>{_fr(m["sharpe"])}</td>'
        f'<td>{_fr(m["var_95_1j_pct"])} %</td><td class="baisse">{_fr(m["perte_max_pct"], 1)} %</td>'
        f'<td>{_fr(m["beta"])}</td><td>{_fr(m["part_seances_echangees_pct"], 0)} %</td></tr>'
        for m in c["comparer"])


def outils_claude() -> list[dict]:
    """Définitions des outils telles que le serveur MCP les annonce, au format de l'API Claude."""
    liste = asyncio.run(S.serveur.list_tools())
    out = []
    for t in liste:
        schema = getattr(t, "inputSchema", None) or getattr(t, "input_schema")
        out.append({"name": t.name, "description": t.description or "", "input_schema": schema})
    return out


def page(c: dict, outils: list[dict], paquets: list[str]) -> str:
    seance = c["derniere_seance"]
    fin = pd.Timestamp(seance["derniere_seance"])
    statut = "close" if seance.get("derniere_seance_close") else "provisoire"
    pal = c["palmares"]
    descr = {n: r for n, r in OUTILS}
    cartes_outils = "".join(
        f'<article class="outil-carte"><span class="famille f-{FAMILLES.get(o["name"], "Marché").lower()}">'
        f'{FAMILLES.get(o["name"], "Marché")}</span><h3><code>{o["name"]}</code></h3>'
        f'<p>{_x(descr.get(o["name"], o["description"].splitlines()[0]))}</p>'
        f'<button class="lien" data-question="{_x(_question_outil(o["name"]))}">Essayer</button></article>'
        for o in outils)
    onglets = "".join(f'<button role="tab" aria-selected="{"true" if i == 0 else "false"}" data-onglet="{i}">{_x(k)}</button>'
                      for i, k in enumerate(INSTALL))
    panneaux = "".join(f'<div class="panneau" data-panneau="{i}"{"" if i == 0 else " hidden"}><pre><code>{_x(v)}</code></pre>'
                       f'<button class="copier">Copier</button></div>' for i, v in enumerate(INSTALL.values()))
    puces = "".join(f'<button class="puce" data-question="{_x(q)}">{_x(q)}</button>' for q in QUESTIONS_CHAT)
    config = {"outils": outils, "instructions": S.INSTRUCTIONS, "paquets": paquets}
    remplacements = {
        "DATE": f"{fin:%d/%m/%Y}",
        "STATUT": statut,
        "NB_SOCIETES": str(len(c["noms"])),
        "CARTES_INDICES": _cartes_indices(c),
        "COURBE": _svg_courbe(c["indices"]["BRVMC"]["cloture"], "aire-brvmc"),
        "RESUME": _resume(c["indices"]["BRVMC"]["cloture"]),
        "PALMARES": _palmares(c),
        "PAL_DU": f'{pd.Timestamp(pal["du"]):%d/%m/%Y}',
        "PAL_AU": f'{pd.Timestamp(pal["au"]):%d/%m/%Y}',
        "COMPARER": _comparer(c),
        "APPEL_COMPARER": _x(", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in c["appel_comparer"].items())),
        "PUCES": puces,
        "OUTILS": cartes_outils,
        "ONGLETS": onglets,
        "PANNEAUX": panneaux,
        "CONFIG": json.dumps(config, ensure_ascii=False).replace("</", "<\\/"),
    }
    texte = (ICI / "modele.html").read_text(encoding="utf-8")
    for k, v in remplacements.items():
        texte = texte.replace("{{" + k + "}}", v)
    return texte


def _question_outil(nom: str) -> str:
    return {
        "derniere_seance": "Quelle est la dernière séance disponible, et est-elle close ?",
        "rechercher_societe": "Quelles sociétés de télécommunications sont cotées à la BRVM ?",
        "fiche_societe": "Donne-moi la fiche de Sonatel.",
        "cours": "Montre les cours mensuels d'Orange Côte d'Ivoire depuis janvier 2025.",
        "indice": "Comment a évolué le BRVM 30 sur les 20 dernières séances ?",
        "liste_indices": "Quels indices sont disponibles, et depuis quand ?",
        "dividendes": "Quels dividendes Sonatel a-t-il versés, nets d'IRVM pour un particulier ?",
        "fondamentaux": "Quels sont les fondamentaux de la SGB CI, avec le PER au dernier cours ?",
        "performance_risque": "Quel est le profil de risque de Sonatel sur un an : volatilité, VaR, perte maximale, bêta ?",
        "comparer": "Compare Sonatel, Orange CI et SGB CI sur un an.",
        "palmares": "Quelles actions ont le plus monté sur les 5 dernières séances ?",
        "correlations": "Quelle est la corrélation entre Sonatel, Orange CI et SGB CI depuis un an ?",
    }.get(nom, f"Utilise l'outil {nom}.")


def main(argv=None) -> None:
    a = argparse.ArgumentParser()
    a.add_argument("--sortie", default="site")
    sortie = Path(a.parse_args(argv).sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    for f in (ICI / "statique").iterdir():
        shutil.copy(f, sortie / f.name)
    paquets = sorted(f"paquets/{p.name}" for p in (sortie / "paquets").glob("*.whl"))
    if not paquets:
        print("Attention : aucune roue dans paquets/, le chat de la page ne pourra pas charger le serveur.")
    if not (sortie / "vendor" / "anthropic.mjs").exists():
        print("Attention : vendor/anthropic.mjs absent, le chat de la page ne pourra pas appeler Claude.")
    c = collecter()
    (sortie / "index.html").write_text(page(c, outils_claude(), paquets), encoding="utf-8")
    (sortie / "seance.json").write_text(json.dumps({
        "derniere_seance": c["derniere_seance"],
        "palmares": c["palmares"],
        "comparer": {"appel": c["appel_comparer"], "reponse": c["comparer"]},
    }, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"Séance du {c['derniere_seance']['derniere_seance']} : page écrite dans {sortie}")


if __name__ == "__main__":
    main()
