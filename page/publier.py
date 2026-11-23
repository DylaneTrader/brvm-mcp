"""Page publique de brvm-mcp : présentation du serveur et séance du jour vue par ses outils.

Chaque bloc de la page est la réponse d'un outil MCP du serveur, appelé comme le ferait un assistant IA
(`derniere_seance`, `indice`, `palmares`, `comparer`). Les réponses brutes sont publiées à côté, en JSON.

    python page/publier.py --sortie site

Le workflow `.github/workflows/page.yml` le relance chaque jour de séance et publie le site sur GitHub Pages.
"""
from __future__ import annotations

import argparse
import html
import json
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
QUESTIONS = [
    "Compare Sonatel, Orange CI et Société Générale CI depuis janvier 2025 : rendement, volatilité, "
    "perte maximale et bêta face au BRVM Composite.",
    "Quelles banques sont cotées au Sénégal, et quel est leur PER au dernier cours ?",
    "Quelles actions ont le plus baissé sur les 20 dernières séances ?",
]


def _fr(x, d=2, signe=False) -> str:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "n.d."
    s = f"{x:+,.{d}f}" if signe else f"{x:,.{d}f}"
    return s.replace(",", " ").replace(".", ",")


def _classe(x) -> str:
    return "" if x is None or pd.isna(x) else ("hausse" if x > 0 else "baisse" if x < 0 else "")


def _appel(nom: str, **kw) -> str:
    args = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in kw.items())
    return f'<p class="appel">Outil appelé : <code>{nom}({html.escape(args)})</code></p>'


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


def _svg_indice(s: pd.Series) -> str:
    s = s.dropna()
    L, H, g, d, h, b = 760, 220, 46, 12, 12, 26
    w, hh = L - g - d, H - h - b
    lo, hi = float(s.min()), float(s.max())
    pad = (hi - lo) * 0.06 or 1
    lo, hi = lo - pad, hi + pad
    x = lambda i: g + w * i / max(len(s) - 1, 1)  # noqa: E731
    y = lambda v: h + hh * (1 - (v - lo) / (hi - lo))  # noqa: E731
    p = [f'<svg viewBox="0 0 {L} {H}" role="img" aria-label="BRVM Composite sur un an">']
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        p.append(f'<line x1="{g}" x2="{L - d}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grille"/>')
        p.append(f'<text x="{g - 6}" y="{y(v) + 4:.1f}" text-anchor="end" class="ax">{_fr(v, 0)}</text>')
    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(s))
    p.append(f'<polyline points="{pts}" fill="none" stroke="#1f4e79" stroke-width="1.8"/>')
    mois = s.index.to_period("M")
    for i in range(1, len(s)):
        if mois[i] != mois[i - 1] and mois[i].month in (1, 4, 7, 10):
            p.append(f'<text x="{x(i):.1f}" y="{H - 8}" text-anchor="middle" class="ax">'
                     f'{s.index[i]:%m/%Y}</text>')
    p.append("</svg>")
    return "".join(p)


def page(c: dict) -> str:
    seance = c["derniere_seance"]
    fin = pd.Timestamp(seance["derniere_seance"])
    statut = "close" if seance.get("derniere_seance_close") else "provisoire"
    noms = c["noms"]

    lignes_ix = ""
    for code, nom in INDICES:
        df = c["indices"][code]
        cl = df["cloture"]
        v20 = (cl.iloc[-1] / cl.iloc[-21] - 1) * 100 if len(cl) > 21 else None
        avant = cl[cl.index < pd.Timestamp(c["debut_an"])]
        van = (cl.iloc[-1] / avant.iloc[-1] - 1) * 100 if len(avant) else None
        v1 = df["variation_pct"].iloc[-1]
        lignes_ix += (f"<tr><td>{nom}</td><td>{_fr(cl.iloc[-1])}</td>"
                      + "".join(f'<td class="{_classe(v)}">{_fr(v, 2, True)} %</td>' for v in (v1, v20, van))
                      + "</tr>")

    def lignes_pal(d):
        return "".join(f'<tr><td>{html.escape(str(noms.get(t, t)))}</td><td>{t.split(".")[0]}</td>'
                       f'<td class="{_classe(v)}">{_fr(v, 2, True)} %</td></tr>' for t, v in d.items())

    pal = c["palmares"]
    lignes_cmp = "".join(
        f'<tr><td>{html.escape(str(noms.get(m["ticker"], m["ticker"])))}</td>'
        f'<td class="{_classe(m["rendement_total_pct"])}">{_fr(m["rendement_total_pct"], 1, True)} %</td>'
        f'<td>{_fr(m["volatilite_annualisee_pct"], 1)} %</td><td>{_fr(m["sharpe"])}</td>'
        f'<td>{_fr(m["var_95_1j_pct"])} %</td><td>{_fr(m["perte_max_pct"], 1)} %</td>'
        f'<td>{_fr(m["beta"])}</td><td>{_fr(m["part_seances_echangees_pct"], 0)} %</td></tr>'
        for m in c["comparer"])
    outils = "".join(f"<tr><td><code>{n}</code></td><td>{html.escape(r)}</td></tr>" for n, r in OUTILS)
    install = "".join(f"<h3>{html.escape(k)}</h3><pre><code>{html.escape(v)}</code></pre>" for k, v in INSTALL.items())
    questions = "".join(f"<blockquote>« {html.escape(q)} »</blockquote>" for q in QUESTIONS)

    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>BRVM MCP</title>
<meta name="description" content="Serveur MCP pour la BRVM : un assistant IA interroge cours, indices, dividendes, fondamentaux et risque des actions cotées.">
<style>
:root{{--fond:#fff;--texte:#1d1d1f;--doux:#5f6368;--trait:#e3e3e3;--code:#f4f5f7;--hausse:#1f6f3a;--baisse:#a32020}}
@media (prefers-color-scheme:dark){{:root{{--fond:#121417;--texte:#e8e8e8;--doux:#a0a4aa;--trait:#2c3036;--code:#1c2026;--hausse:#5fbf7a;--baisse:#ef7d7d}}}}
body{{margin:0;background:var(--fond);color:var(--texte);font-family:"Times New Roman",Times,serif;line-height:1.5}}
main{{max-width:860px;margin:0 auto;padding:24px 16px 48px}}
h1{{font-size:1.9rem;margin:0 0 4px}} h2{{margin-top:36px}} h3{{font-size:1.05rem;margin:18px 0 6px}}
.sous{{color:var(--doux);margin:0 0 20px;font-size:1.1rem}}
.bandeau{{border-left:4px solid #1f4e79;padding:8px 12px;background:var(--code);margin:16px 0}}
table{{border-collapse:collapse;width:100%;margin:8px 0 6px;font-size:.97rem}}
.defile{{overflow-x:auto}}
td,th{{border-bottom:1px solid var(--trait);padding:5px 8px;text-align:left;white-space:nowrap}}
td:not(:first-child),th:not(:first-child){{text-align:right}}
.outils td{{white-space:normal}} .outils td:last-child{{text-align:left}}
.hausse{{color:var(--hausse)}} .baisse{{color:var(--baisse)}}
.deux{{display:grid;grid-template-columns:1fr 1fr;gap:20px}} @media (max-width:640px){{.deux{{grid-template-columns:1fr}}}}
code{{font-family:Consolas,"DejaVu Sans Mono",monospace;font-size:.86em;background:var(--code);padding:1px 4px;border-radius:3px}}
pre{{background:var(--code);padding:10px 12px;border-radius:4px;overflow-x:auto}} pre code{{padding:0;background:none}}
.appel{{color:var(--doux);font-size:.9rem;margin:2px 0 0}}
blockquote{{margin:8px 0;padding:6px 12px;border-left:3px solid var(--trait);font-style:italic}}
svg{{width:100%;height:auto}} svg .ax{{font-size:11px;fill:var(--doux)}} svg .grille{{stroke:var(--trait)}}
footer,.note{{color:var(--doux);font-size:.92rem}} a{{color:#3d7cc9}}
</style></head><body><main>
<h1>BRVM MCP</h1>
<p class="sous">Le marché d'actions de la BRVM, branché sur votre assistant IA.</p>
<p><b>brvm-mcp</b> est un serveur <a href="https://modelcontextprotocol.io">Model Context Protocol</a> : il donne à Claude, ChatGPT, Cursor ou tout client MCP douze outils pour interroger les cours, indices, dividendes et fondamentaux des actions cotées à la Bourse Régionale des Valeurs Mobilières, et calculer leurs mesures de performance et de risque selon les règles du marché régional. L'assistant répond alors avec les vraies données de la séance, pas de mémoire.</p>
<div class="bandeau">Données de la séance du <b>{fin:%d/%m/%Y}</b> ({statut}). Chaque bloc ci-dessous est la réponse d'un outil du serveur, appelé comme le ferait un assistant.</div>

<h2>Les indices</h2>
<div class="defile"><table><thead><tr><th>Indice</th><th>Clôture</th><th>Séance</th><th>20 séances</th><th>Depuis le 1er janvier</th></tr></thead><tbody>{lignes_ix}</tbody></table></div>
{_appel("indice", code="BRVMC")}
{_svg_indice(c["indices"]["BRVMC"]["cloture"])}
<p class="note">BRVM Composite sur un an.</p>

<h2>Le palmarès des 20 dernières séances</h2>
<p class="note">Du {pd.Timestamp(pal["du"]):%d/%m/%Y} au {pd.Timestamp(pal["au"]):%d/%m/%Y}, variation du cours de clôture.</p>
<div class="deux">
<div><h3>Plus fortes hausses</h3><table><tbody>{lignes_pal(pal["hausses_pct"])}</tbody></table></div>
<div><h3>Plus fortes baisses</h3><table><tbody>{lignes_pal(pal["baisses_pct"])}</tbody></table></div>
</div>
{_appel("palmares", seances=20, nombre=5)}

<h2>Les plus grandes capitalisations sur un an</h2>
<div class="defile"><table><thead><tr><th>Société</th><th>Rendement</th><th>Volatilité</th><th>Sharpe</th><th>VaR 95 % 1 j</th><th>Perte max.</th><th>Bêta</th><th>Échanges</th></tr></thead><tbody>{lignes_cmp}</tbody></table></div>
{_appel("comparer", **c["appel_comparer"])}
<p class="note">Rendement hors dividendes, volatilité annualisée sur 252 séances, VaR historique sur un jour, bêta face au BRVM Composite sur les dates communes d'échange, part des séances où le titre a échangé.</p>

<h2>Ce qu'on peut lui demander</h2>
{questions}

<h2>Installer</h2>
{install}

<h2>Les douze outils</h2>
<table class="outils"><tbody>{outils}</tbody></table>

<h2>Les règles de la BRVM prises en compte</h2>
<ul>
<li>Un titre qui n'échange pas un jour n'a pas de ligne ce jour-là : les rendements se calculent entre séances d'échange, jamais avec un rendement nul inventé.</li>
<li>La variation d'un titre est limitée à ±7,5 % par séance : les séances à la limite sont signalées, car elles rendent la VaR historique trompeuse.</li>
<li>Bêta et corrélations sur les dates communes d'échange, 31 observations au minimum.</li>
<li>Cours ajustés des divisions du nominal ; dividendes nets d'IRVM contrôlés.</li>
</ul>

<p>Réponses brutes des outils : <a href="seance.json">JSON</a> · <a href="https://github.com/DylaneTrader/brvm-mcp">code</a> · <a href="https://github.com/DylaneTrader/brvm-py">données (brvm-py)</a></p>
<footer>Données de marché : brvm-py (Sikafinance, brvm.org), fournies sans garantie. Mesures historiques, ce n'est pas un conseil en investissement. Dylane NDOUDY-BAMOUENIZO.</footer>
</main></body></html>
"""


def main(argv=None) -> None:
    a = argparse.ArgumentParser()
    a.add_argument("--sortie", default="site")
    sortie = Path(a.parse_args(argv).sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    c = collecter()
    (sortie / "index.html").write_text(page(c), encoding="utf-8")
    (sortie / "seance.json").write_text(json.dumps({
        "derniere_seance": c["derniere_seance"],
        "palmares": c["palmares"],
        "comparer": {"appel": c["appel_comparer"], "reponse": c["comparer"]},
    }, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"Séance du {c['derniere_seance']['derniere_seance']} : page écrite dans {sortie}")


if __name__ == "__main__":
    main()
