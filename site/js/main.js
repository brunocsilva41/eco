/* Eco — site. JavaScript puro, sem dependências nem rastreadores. */
(function () {
  "use strict";
  var doc = document, root = doc.documentElement;
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  var $ = function (s, c) { return (c || doc).querySelector(s); };
  var $$ = function (s, c) { return Array.prototype.slice.call((c || doc).querySelectorAll(s)); };

  /* ---------------- revelação ao rolar ---------------- */
  var revealEls = $$(".reveal");
  if ("IntersectionObserver" in window && !reduce.matches) {
    var ro = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("in"); ro.unobserve(e.target); } });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
    revealEls.forEach(function (el, i) { el.style.transitionDelay = (i % 4) * 60 + "ms"; ro.observe(el); });
  } else {
    revealEls.forEach(function (el) { el.classList.add("in"); });
  }

  /* ---------------- tema ---------------- */
  var themeBtn = $("#theme-btn");
  var modes = ["auto", "light", "dark"];
  var modeText = { auto: "automático", light: "claro", dark: "escuro" };
  function effectiveTheme() {
    var t = root.dataset.theme;
    if (t === "light" || t === "dark") return t;
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }
  function paintThemeBtn() {
    var m = root.dataset.theme || "auto";
    themeBtn.setAttribute("aria-label", "Alternar tema (atual: " + modeText[m] + ")");
    themeBtn.title = "Tema: " + modeText[m];
  }
  function swapShots() {
    var t = effectiveTheme();
    $$("img[data-shot]").forEach(function (img) {
      var want = "assets/shots/" + img.dataset.shot + "-" + t + ".png";
      if (img.getAttribute("src") === want) return;
      var probe = new Image();
      probe.onload = function () { img.src = want; };
      probe.onerror = function () { /* sem versão para este tema: mantém a atual */ };
      probe.src = want;
    });
  }
  themeBtn.addEventListener("click", function () {
    var cur = root.dataset.theme || "auto";
    var next = modes[(modes.indexOf(cur) + 1) % modes.length];
    root.dataset.theme = next;
    try { if (next === "auto") localStorage.removeItem("eco-theme"); else localStorage.setItem("eco-theme", next); } catch (e) {}
    paintThemeBtn(); swapShots();
  });
  window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", swapShots);
  paintThemeBtn(); swapShots();

  /* ---------------- Ilha interativa ---------------- */
  var island = $("#island"), labelEl = $("#island-label"), subEl = $("#island-sub");
  var chips = $$(".state[data-go]"), playBtn = $("#play");
  var STATES = {
    idle:       { label: "Em repouso",             sub: "Diga “Eco” ou segure F9" },
    listening:  { label: "Ouvindo",                sub: "“Abra o bloco de notas”" },
    thinking:   { label: "Pensando",               sub: "Cérebro local · sua GPU" },
    speaking:   { label: "Falando",                sub: "“Pronto, abri o Bloco de Notas.”" },
    confirming: { label: "Permitir e lembrar?",    sub: "Digitar texto no Bloco de Notas" },
    error:      { label: "Não consegui ouvir",     sub: "Microfone sem sinal. Reabrindo…" }
  };
  var ORDER = ["idle", "listening", "thinking", "speaking", "confirming", "error"];
  var cur = "idle", timer = null, auto = !reduce.matches, visible = true, userPicked = false;

  function setState(s, fromUser) {
    if (!STATES[s]) return;
    cur = s;
    island.dataset.state = s;
    labelEl.textContent = STATES[s].label;
    subEl.textContent = STATES[s].sub;
    island.setAttribute("aria-label", "Demonstração da Ilha do Eco. Estado: " + STATES[s].label + ". Pressione para avançar o estado.");
    chips.forEach(function (c) { c.setAttribute("aria-pressed", String(c.dataset.go === s)); });
    if (fromUser) userPicked = true;
  }
  function next() { setState(ORDER[(ORDER.indexOf(cur) + 1) % ORDER.length]); }
  function schedule() {
    clearTimeout(timer);
    if (!auto || !visible || doc.hidden) return;
    timer = setTimeout(function () { next(); schedule(); }, cur === "idle" ? 2200 : 3000);
  }
  function setAuto(on) {
    auto = on;
    playBtn.setAttribute("aria-pressed", String(on));
    playBtn.textContent = on ? "Pausar" : "Reproduzir";
    playBtn.setAttribute("aria-label", on ? "Pausar a demonstração automática" : "Reproduzir a demonstração automática");
    schedule();
  }
  island.addEventListener("click", function () { next(); setAuto(false); userPicked = true; });
  chips.forEach(function (c) {
    c.addEventListener("click", function () { setState(c.dataset.go, true); setAuto(false); });
    c.addEventListener("keydown", function (e) {
      var i = chips.indexOf(c), n = null;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") n = chips[(i + 1) % chips.length];
      if (e.key === "ArrowLeft" || e.key === "ArrowUp") n = chips[(i - 1 + chips.length) % chips.length];
      if (n) { e.preventDefault(); n.focus(); }
    });
  });
  playBtn.addEventListener("click", function () { setAuto(!auto); });
  doc.addEventListener("visibilitychange", schedule);
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (es) { visible = es[0].isIntersecting; schedule(); }, { threshold: 0.2 }).observe($("#stage"));
  }
  reduce.addEventListener && reduce.addEventListener("change", function () { setAuto(!reduce.matches); });
  setAuto(auto);

  /* ---------------- fluxo "como funciona" ---------------- */
  var flow = $("#flow"), steps = $$(".flow__step", flow), reached = 0;
  function reach(i) {
    if (i <= reached) return;
    reached = i;
    steps.forEach(function (s, k) { s.classList.toggle("on", k < i); });
    flow.style.setProperty("--p", String((i - 1) / (steps.length - 1)));
  }
  if ("IntersectionObserver" in window && !reduce.matches) {
    var so = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting) { reach(steps.indexOf(e.target) + 1); so.unobserve(e.target); } });
    }, { rootMargin: "0px 0px -18% 0px", threshold: 0.2 });
    steps.forEach(function (s) { so.observe(s); });
  } else { reach(steps.length); }

  /* ---------------- abas de capturas ---------------- */
  var tabs = $$('[role="tab"]');
  function selectTab(i, focus) {
    tabs.forEach(function (t, k) {
      var on = k === i, p = doc.getElementById(t.getAttribute("aria-controls"));
      t.setAttribute("aria-selected", String(on)); t.tabIndex = on ? 0 : -1;
      if (p) p.hidden = !on;
      if (on && focus) t.focus();
    });
  }
  tabs.forEach(function (t, i) {
    t.addEventListener("click", function () { selectTab(i); });
    t.addEventListener("keydown", function (e) {
      var k = null;
      if (e.key === "ArrowRight") k = (i + 1) % tabs.length;
      else if (e.key === "ArrowLeft") k = (i - 1 + tabs.length) % tabs.length;
      else if (e.key === "Home") k = 0; else if (e.key === "End") k = tabs.length - 1;
      if (k !== null) { e.preventDefault(); selectTab(k, true); }
    });
  });

  /* ---------------- downloads (releases.json) ---------------- */
  var dl = $("#dl"), dlVer = $("#dl-ver"), dlMeta = $("#dl-meta"), dlBtn = $("#dl-btn"), dlSha = $("#dl-sha"), dlNote = $("#dl-note");
  var heroVer = $("#hero-ver"), copyBtn = $("#copy-sha"), shaValue = "";
  function placeholder(msg) {
    dl.dataset.state = "placeholder";
    dlVer.innerHTML = '<span class="badge">Em breve</span><br>Primeira versão do Eco';
    dlMeta.textContent = "Ainda não há instalador publicado com o nome Eco.";
    dlBtn.setAttribute("aria-disabled", "true"); dlBtn.removeAttribute("download"); dlBtn.href = "#download";
    dlSha.textContent = "O hash SHA-256 será publicado junto com o instalador.";
    dlNote.textContent = msg || "";
    copyBtn.hidden = true;
  }
  function fmtSize(b) { return b >= 1048576 ? (b / 1048576).toFixed(0) + " MB" : Math.round(b / 1024) + " KB"; }
  function fmtDate(s) { var d = new Date(s); return isNaN(d) ? "" : d.toLocaleDateString("pt-BR", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" }); }
  function applyRelease(r) {
    /* so aceita download DIRETO do proprio GitHub (asset de release), nunca outro host */
    var okUrl = typeof r.url === "string" && /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/releases\/(latest\/download|download\/[^/]+)\/[\w.-]+\.exe$/i.test(r.url);
    var okSha = typeof r.sha256 === "string" && /^[0-9a-f]{64}$/i.test(r.sha256);
    if (!r || !r.version || !okUrl || !okSha) { placeholder(""); return; }
    dl.dataset.state = "ready";
    dlVer.textContent = "Eco " + r.version;
    var parts = ["Windows 10/11 · 64 bits"];
    if (r.size_bytes) parts.push(fmtSize(r.size_bytes));
    if (r.date) parts.push(fmtDate(r.date));
    dlMeta.textContent = parts.join(" · ");
    /* URL de asset do GitHub responde 302 para o CDN com Content-Disposition: attachment: o navegador baixa na hora,
       sem abrir a pagina do repositorio. O atributo download e so uma dica (ignorado entre origens). */
    dlBtn.href = r.url; dlBtn.rel = "noopener"; dlBtn.setAttribute("download", r.url.split("/").pop());
    dlBtn.removeAttribute("aria-disabled");
    shaValue = r.sha256.toLowerCase(); dlSha.textContent = shaValue; copyBtn.hidden = false;
    dlNote.innerHTML = r.notes_url && /^https:\/\//i.test(r.notes_url) ? '<a href="' + encodeURI(r.notes_url) + '" rel="noopener">Notas da versão</a>' : "";
    heroVer.textContent = "Versão " + r.version + " · Windows 10 (build 19044+) ou 11 · 64 bits";
  }
  dlBtn.addEventListener("click", function (e) { if (dlBtn.getAttribute("aria-disabled") === "true") e.preventDefault(); });
  copyBtn.addEventListener("click", function () {
    if (!shaValue) return;
    var done = function () { copyBtn.textContent = "Copiado"; setTimeout(function () { copyBtn.textContent = "Copiar hash"; }, 1800); };
    if (navigator.clipboard) navigator.clipboard.writeText(shaValue).then(done, function () {});
  });
  fetch("releases.json", { cache: "no-cache" })
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(applyRelease)
    .catch(function () { placeholder("Não foi possível ler releases.json (abra o site por um servidor, não por arquivo)."); });
})();
