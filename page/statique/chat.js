/* Chat de la page : Claude, avec la clé API du visiteur, interroge les outils de brvm-mcp.
   La clé ne quitte le navigateur que vers api.anthropic.com ; elle n'est jamais envoyée ailleurs.
   Les outils s'exécutent dans moteur.js (le vrai code Python du serveur, via Pyodide). */
import Anthropic from "./vendor/anthropic.mjs";

const CONFIG = JSON.parse(document.getElementById("config-chat").textContent);
const MODELES = {
  "claude-opus-5-5": { reflexion: true },
  "claude-sonnet-5-5": { reflexion: true },
  "claude-haiku-5-5": { reflexion: false },
};
const MAX_TOURS_OUTILS = 12;

const $ = (s) => document.querySelector(s);
const fil = $("#fil");
const champ = $("#question");
const bouton = $("#envoyer");
const champCle = $("#cle");
const etatMoteur = $("#etat-moteur");
const choixModele = $("#modele");

let messages = [];
let occupe = false;

/* ---------- Clé API ---------- */
try {
  const k = sessionStorage.getItem("brvm-mcp-cle");
  if (k) { champCle.value = k; $("#memoriser").checked = true; }
} catch (_) { /* stockage indisponible : la clé reste en mémoire */ }

function cle() {
  const k = champCle.value.trim();
  try {
    if ($("#memoriser").checked && k) sessionStorage.setItem("brvm-mcp-cle", k);
    else sessionStorage.removeItem("brvm-mcp-cle");
  } catch (_) {}
  return k;
}
$("#memoriser").addEventListener("change", cle);
$("#oublier").addEventListener("click", () => {
  champCle.value = ""; $("#memoriser").checked = false; cle();
});
$("#voir-cle").addEventListener("click", () => {
  champCle.type = champCle.type === "password" ? "text" : "password";
});

/* ---------- Moteur Python ---------- */
const moteur = new Worker("moteur.js", { type: "module" });
let moteurPret = null;
let resoudrePret, rejeterPret;
const attentes = new Map();
let compteur = 0;

function marquer(etat, texte) {
  etatMoteur.dataset.etat = etat;
  etatMoteur.querySelector("span").textContent = texte;
}

moteur.onmessage = (ev) => {
  const m = ev.data;
  if (m.type === "etat") marquer("charge", m.texte);
  else if (m.type === "pret") { marquer("pret", "Serveur prêt : 12 outils"); resoudrePret(); }
  else if (m.type === "echec") { marquer("echec", "Échec du chargement : " + m.texte); rejeterPret(new Error(m.texte)); moteurPret = null; }
  else if (m.type === "resultat") { attentes.get(m.id)?.(m); attentes.delete(m.id); }
};

function demarrerMoteur() {
  if (!moteurPret) {
    moteurPret = new Promise((ok, ko) => { resoudrePret = ok; rejeterPret = ko; });
    marquer("charge", "Chargement de Python…");
    moteur.postMessage({ type: "demarrer", paquets: CONFIG.paquets });
  }
  return moteurPret;
}
// Le moteur se charge dès que le visiteur s'approche du chat, pour ne pas attendre à la première question.
const observateur = new IntersectionObserver((e) => {
  if (e.some((x) => x.isIntersecting)) { demarrerMoteur().catch(() => {}); observateur.disconnect(); }
}, { rootMargin: "300px" });
observateur.observe($("#essayer"));

function executer(nom, args) {
  return new Promise((ok) => {
    const id = ++compteur;
    attentes.set(id, ok);
    moteur.postMessage({ type: "appel", id, nom, arguments: args });
  });
}

/* ---------- Validation des arguments (le flux des arguments est partiel tant qu'il n'est pas fini) ---------- */
function typeOk(v, s) {
  if (s.anyOf) return s.anyOf.some((x) => typeOk(v, x));
  if (s.enum && !s.enum.includes(v)) return false;
  switch (s.type) {
    case "string": return typeof v === "string";
    case "integer": return Number.isInteger(v);
    case "number": return typeof v === "number" && Number.isFinite(v);
    case "boolean": return typeof v === "boolean";
    case "null": return v === null;
    case "array": return Array.isArray(v) && (!s.items || v.every((x) => typeOk(x, s.items)));
    case "object": return v !== null && typeof v === "object" && !Array.isArray(v);
    default: return true;
  }
}
function valider(outil, entree) {
  if (!entree || typeof entree !== "object" || Array.isArray(entree)) return "arguments absents ou mal formés";
  const props = outil.input_schema.properties || {};
  for (const r of outil.input_schema.required || []) if (!(r in entree)) return `argument obligatoire manquant : ${r}`;
  for (const [k, v] of Object.entries(entree)) {
    if (!(k in props)) return `argument inconnu : ${k}`;
    if (!typeOk(v, props[k])) return `argument de type inattendu : ${k}`;
  }
  return null;
}

/* ---------- Affichage ---------- */
function echapper(t) {
  return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function enLigne(t) {
  return t
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
}
function markdown(src) {
  const lignes = echapper(src).split("\n");
  let html = "", i = 0;
  while (i < lignes.length) {
    const l = lignes[i];
    if (/^\s*\|.*\|\s*$/.test(l) && i + 1 < lignes.length && /^\s*\|[\s:|-]+\|\s*$/.test(lignes[i + 1])) {
      const cellules = (x) => x.trim().replace(/^\||\|$/g, "").split("|").map((c) => enLigne(c.trim()));
      html += "<div class='defile'><table><thead><tr>" + cellules(l).map((c) => `<th>${c}</th>`).join("") + "</tr></thead><tbody>";
      i += 2;
      while (i < lignes.length && /^\s*\|.*\|\s*$/.test(lignes[i])) {
        html += "<tr>" + cellules(lignes[i]).map((c) => `<td>${c}</td>`).join("") + "</tr>";
        i++;
      }
      html += "</tbody></table></div>";
      continue;
    }
    if (/^```/.test(l)) {
      let code = ""; i++;
      while (i < lignes.length && !/^```/.test(lignes[i])) code += lignes[i++] + "\n";
      html += `<pre><code>${code}</code></pre>`; i++; continue;
    }
    const titre = l.match(/^(#{1,4})\s+(.*)$/);
    if (titre) { html += `<h4>${enLigne(titre[2])}</h4>`; i++; continue; }
    if (/^\s*([-*]|\d+[.)])\s+/.test(l)) {
      const ordonnee = /^\s*\d/.test(l);
      html += ordonnee ? "<ol>" : "<ul>";
      while (i < lignes.length && /^\s*([-*]|\d+[.)])\s+/.test(lignes[i])) {
        html += "<li>" + enLigne(lignes[i].replace(/^\s*([-*]|\d+[.)])\s+/, "")) + "</li>"; i++;
      }
      html += ordonnee ? "</ol>" : "</ul>"; continue;
    }
    if (!l.trim()) { i++; continue; }
    let para = l; i++;
    while (i < lignes.length && lignes[i].trim() && !/^(#|```|\s*\||\s*([-*]|\d+[.)])\s)/.test(lignes[i])) para += " " + lignes[i++];
    html += `<p>${enLigne(para)}</p>`;
  }
  return html;
}

function bulle(role) {
  const d = document.createElement("div");
  d.className = "msg " + role;
  fil.append(d);
  $("#accueil")?.remove();
  return d;
}
function defiler() { fil.scrollTop = fil.scrollHeight; }

function puceOutil(conteneur, nom, args) {
  const det = document.createElement("details");
  det.className = "outil en-cours";
  const a = Object.entries(args || {}).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ");
  det.innerHTML = `<summary><span class="rond"></span><code>${echapper(nom)}(${echapper(a)})</code></summary><pre></pre>`;
  conteneur.append(det);
  return det;
}

function erreurVisible(texte) {
  const d = bulle("systeme");
  d.textContent = texte;
  defiler();
}

/* ---------- Boucle Claude + outils ---------- */
async function tourner() {
  const k = cle();
  if (!k) { erreurVisible("Saisissez d'abord votre clé API Anthropic (elle commence par sk-ant-)."); champCle.focus(); return false; }
  const client = new Anthropic({ apiKey: k, dangerouslyAllowBrowser: true, maxRetries: 2 });
  const modele = choixModele.value;
  const outils = CONFIG.outils.map((o) => ({ ...o, eager_input_streaming: true }));

  try { await demarrerMoteur(); }
  catch (e) { erreurVisible("Le moteur Python n'a pas pu se charger. Rechargez la page pour réessayer."); return false; }

  let reprisesFlux = 0;
  for (let tour = 0; tour < MAX_TOURS_OUTILS; tour++) {
    const zone = bulle("assistant");
    zone.innerHTML = "<div class='pensee'><span></span><span></span><span></span></div>";
    let texte = "";
    const params = {
      model: modele,
      max_tokens: 16000,
      system: CONFIG.instructions,
      tools: outils,
      messages,
    };
    if (MODELES[modele]?.reflexion) params.thinking = { type: "adaptive" };

    let message;
    try {
      const flux = client.messages.stream(params);
      flux.on("text", (delta) => {
        texte += delta;
        zone.innerHTML = markdown(texte);
        defiler();
      });
      message = await flux.finalMessage();
    } catch (e) {
      zone.remove();
      if (e instanceof Anthropic.AuthenticationError) { erreurVisible("Clé API refusée par Anthropic. Vérifiez-la dans la console Anthropic."); return false; }
      if (e instanceof Anthropic.PermissionDeniedError) { erreurVisible("Cette clé n'a pas accès à ce modèle. Essayez un autre modèle."); return false; }
      if (e instanceof Anthropic.RateLimitError) { erreurVisible("Limite de débit atteinte sur votre clé. Patientez une minute puis réessayez."); return false; }
      if (e instanceof Anthropic.APIError) { erreurVisible(`Erreur de l'API Anthropic (${e.status ?? "réseau"}) : ${e.message}`); return false; }
      // Connexion coupée en plein flux ou arguments d'outil illisibles : on relance le même tour.
      if (reprisesFlux++ < 2) { tour--; continue; }
      erreurVisible("La connexion a été interrompue. Réessayez."); return false;
    }
    reprisesFlux = 0;
    if (!texte) zone.innerHTML = "";

    messages.push({ role: "assistant", content: message.content });
    const appels = message.content.filter((b) => b.type === "tool_use");

    if (message.stop_reason === "refusal") { erreurVisible("Claude a refusé de répondre à cette demande."); return true; }
    if (message.stop_reason === "pause_turn") { if (!zone.innerHTML) zone.remove(); continue; }
    if (message.stop_reason === "max_tokens") {
      if (appels.length) { messages.pop(); erreurVisible("Réponse coupée (longueur maximale atteinte) pendant un appel d'outil. Reformulez plus simplement."); }
      return true;
    }
    if (message.stop_reason !== "tool_use" || !appels.length) { if (!zone.innerHTML) zone.remove(); return true; }

    // Tous les résultats d'un même tour partent dans un seul message utilisateur.
    const resultats = await Promise.all(appels.map(async (b) => {
      const def = CONFIG.outils.find((o) => o.name === b.name);
      const puce = puceOutil(zone, b.name, b.input);
      defiler();
      const invalide = def ? valider(def, b.input) : `outil inconnu : ${b.name}`;
      let r;
      if (invalide) r = { ok: false, contenu: invalide };
      else r = await executer(b.name, b.input);
      puce.classList.remove("en-cours");
      puce.classList.add(r.ok ? "fait" : "rate");
      let apercu = r.contenu;
      try { apercu = JSON.stringify(JSON.parse(r.contenu), null, 1); } catch (_) {}
      puce.querySelector("pre").textContent = apercu.length > 6000 ? apercu.slice(0, 6000) + "\n…" : apercu;
      return { type: "tool_result", tool_use_id: b.id, content: r.contenu, ...(r.ok ? {} : { is_error: true }) };
    }));
    messages.push({ role: "user", content: resultats });
  }
  erreurVisible("Trop d'appels d'outils pour une seule question : la réponse s'arrête ici.");
  return true;
}

async function envoyer(q) {
  q = (q ?? champ.value).trim();
  if (!q || occupe) return;
  occupe = true; bouton.disabled = true;
  const avant = messages.length;
  bulle("utilisateur").textContent = q;
  champ.value = ""; ajuster();
  messages.push({ role: "user", content: q });
  defiler();
  const ok = await tourner();
  // Une question qui n'a pas abouti est retirée de l'historique, pour pouvoir la reposer.
  if (!ok) messages = messages.slice(0, avant);
  occupe = false; bouton.disabled = false; champ.focus();
}

function ajuster() { champ.style.height = "auto"; champ.style.height = Math.min(champ.scrollHeight, 180) + "px"; }
champ.addEventListener("input", ajuster);
champ.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); envoyer(); }
});
bouton.addEventListener("click", () => envoyer());
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-question]");
  if (!b) return;
  document.getElementById("essayer").scrollIntoView({ behavior: "smooth" });
  envoyer(b.dataset.question);
});
$("#effacer").addEventListener("click", () => {
  if (occupe) return;
  messages = [];
  fil.innerHTML = "";
  fil.append($("#modele-accueil").content.cloneNode(true));
});
