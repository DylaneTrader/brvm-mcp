/* Moteur Python de la page : fait tourner le vrai code de brvm-mcp (et de brvm-py) dans le navigateur
   avec Pyodide, dans un Web Worker (module). Aucun serveur : les données sont lues directement sur la branche
   `donnees` du dépôt brvm-py, comme le fait le paquet installé sur un poste. */
const VERSION_PYODIDE = "314.0.7";
const SOURCES_PYODIDE = [
  `https://cdn.jsdelivr.net/pyodide/v${VERSION_PYODIDE}/full/`,
  `https://cdn.jsdelivr.net/npm/pyodide@${VERSION_PYODIDE}/`,
];

let pret = null;

function etat(texte) {
  self.postMessage({ type: "etat", texte });
}

const AMORCE = `
import sys, types, json

# Le serveur importe le SDK MCP pour s'enregistrer ; dans la page, les outils sont appelés directement.
class _ServeurLocal:
    def __init__(self, *a, **k): pass
    def tool(self, *a, **k): return lambda f: f
    def run(self, *a, **k): pass

for _nom in ("mcp", "mcp.server", "mcp.server.fastmcp"):
    sys.modules[_nom] = types.ModuleType(_nom)
sys.modules["mcp.server.fastmcp"].FastMCP = _ServeurLocal

# Téléchargement des fichiers de données par une requête synchrone du navigateur (pas de socket ici).
from js import XMLHttpRequest
from brvm import _source

def _telecharger(self, chemin):
    r = XMLHttpRequest.new()
    r.open("GET", self.url + chemin, False)
    r.send(None)
    if r.status != 200:
        raise OSError(f"HTTP {r.status} sur {chemin}")
    return str(r.responseText).encode("utf-8")

_source.Source._telecharger = _telecharger

from brvm_mcp import serveur as S

def appeler(nom, arguments):
    fonction = getattr(S, nom)
    return json.dumps(fonction(**json.loads(arguments)), ensure_ascii=False, default=str)
`;

async function chargerPyodide() {
  let erreur = null;
  for (const base of SOURCES_PYODIDE) {
    try {
      const { loadPyodide } = await import(base + "pyodide.mjs");
      return await loadPyodide({ indexURL: base });
    } catch (e) {
      erreur = e;
    }
  }
  throw erreur;
}

async function demarrer(paquets) {
  etat("Chargement de Python (Pyodide)…");
  const pyodide = await chargerPyodide();
  etat("Chargement de pandas et numpy…");
  await pyodide.loadPackage(["pandas", "micropip"]);
  etat("Installation de brvm-py et brvm-mcp…");
  const micropip = pyodide.pyimport("micropip");
  const adresses = paquets.map((p) => new URL(p, self.location.href).href);
  // Sans les dépendances : pandas est déjà là, et le SDK MCP n'est pas utile dans la page.
  await micropip.install.callKwargs(adresses, { deps: false });
  await pyodide.runPythonAsync(AMORCE);
  etat("Lecture de la dernière séance…");
  const appeler = pyodide.globals.get("appeler");
  appeler("derniere_seance", "{}");
  return appeler;
}

self.onmessage = async (ev) => {
  const m = ev.data;
  if (m.type === "demarrer") {
    try {
      pret = pret || demarrer(m.paquets);
      await pret;
      self.postMessage({ type: "pret" });
    } catch (e) {
      pret = null;
      self.postMessage({ type: "echec", texte: String(e && e.message ? e.message : e) });
    }
    return;
  }
  if (m.type === "appel") {
    try {
      const appeler = await pret;
      const resultat = appeler(m.nom, JSON.stringify(m.arguments || {}));
      self.postMessage({ type: "resultat", id: m.id, ok: true, contenu: resultat });
    } catch (e) {
      const texte = String(e && e.message ? e.message : e);
      // Une erreur Python arrive avec toute sa pile : on garde la dernière ligne, la plus parlante.
      const lignes = texte.trim().split("\n");
      self.postMessage({ type: "resultat", id: m.id, ok: false, contenu: lignes[lignes.length - 1] });
    }
  }
};
