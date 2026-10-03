"use strict";
/* Avatarize — interface. Conversa com o Python por window.pywebview.api; o Python avisa mudanças por AV.evento(). */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

/* ícones de traço (24x24, stroke = currentColor) */
const I = {
  chev: '<path d="M6 9l6 6 6-6"/>',
  refresh: '<path d="M20 12a8 8 0 1 1-2.34-5.66"/><path d="M20 4v5h-5"/>',
  sair: '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><path d="M10 17l-5-5 5-5"/><path d="M5 12h11"/>',
  imagem: '<rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="9" cy="10" r="1.8"/><path d="M21 16l-5-5-9 9"/>',
  enviar: '<path d="M12 15V4"/><path d="M7 9l5-5 5 5"/><path d="M5 15v3a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-3"/>',
  onda: '<path d="M4 10v4M8 7v10M12 4v16M16 8v8M20 11v2"/>',
  texto: '<path d="M5 7V5h14v2"/><path d="M12 5v14"/><path d="M9 19h6"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/>',
  pessoa: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  ajustes: '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
  pasta: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  brilho: '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
  cadeado: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  ligar: '<path d="M9 15l6-6"/><path d="M11 6l.7-.7a4.2 4.2 0 0 1 6 6l-.7.7"/><path d="M13 18l-.7.7a4.2 4.2 0 0 1-6-6l.7-.7"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  busca: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
  play: '<path d="M8 5.5v13l10.5-6.5z"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  alerta: '<path d="M12 3.5l9 16H3z"/><path d="M12 10v4"/><path d="M12 17h.01"/>',
  lixo: '<path d="M4 7h16"/><path d="M10 11v6M14 11v6"/><path d="M6 7l1 13h10l1-13"/><path d="M9 7V4h6v3"/>',
  relogio: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  carrega: '<path d="M12 3a9 9 0 1 0 9 9"/>',
  estrela: '<path d="M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.9-5.2-2.8-5.2 2.8 1-5.9-4.3-4.1 5.9-.8z"/>',
};
const ic = (n, cls = "") =>
  `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${I[n] || ""}</svg>`;
const icones = (root = document) => $$("i[data-ic]", root).forEach((e) => (e.outerHTML = ic(e.dataset.ic, e.className)));

const PRIVADAS = "__private__";
const MOTORES = [[PRIVADAS, "Minhas vozes"], ["", "Todas"], ["starfish", "Starfish"], ["elevenlabs", "ElevenLabs"],
  ["cartesia", "Cartesia"], ["fish", "Fish"], ["bytedance", "ByteDance"], ["panda", "Panda"]];
const ETAPA = { preparar: "Preparando os arquivos", foto: "Enviando a foto", audio: "Enviando o áudio",
  criar: "Criando o vídeo", gerando: "HeyGen gerando o vídeo", baixar: "Baixando o MP4" };
const EXPR = { low: "expressão baixa", medium: "expressão média", high: "expressão alta" };

const S = {
  conectado: false, conta: null, foto: null, audios: [], modo: "audio", voz: null,
  formato: "9:16", res: "1080p", expr: "medium", corte: false, nivel: "Médio", ffmpeg: true, pasta: "",
  jobs: new Map(), motor: PRIVADAS, vozes: {}, carregando: new Set(), cloneAudio: null, clonando: false, cancelou: false,
};
let api = null;

/* ------------------------------------------------------------------------------------------------ geral */

function toast(msg, tipo = "") {
  const d = document.createElement("div");
  d.className = tipo;
  d.innerHTML = (tipo === "erro" ? ic("alerta") : tipo === "ok" ? ic("check") : "") + `<span>${esc(msg)}</span>`;
  $("#toast").append(d);
  setTimeout(() => d.remove(), 4200);
}

function segmentado(id, aoMudar) {
  const el = $("#" + id);
  el.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b || el.classList.contains("trava")) return;
    $$("button", el).forEach((x) => { x.classList.toggle("on", x === b); x.setAttribute("aria-pressed", String(x === b)); });
    aoMudar(b.dataset.v);
  });
}

const hora = (ms) => (ms ? new Date(ms).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : "");

function motivo() {
  if (!S.conectado) return "Conecte sua conta HeyGen";
  if (!S.foto) return "Adicione a foto do avatar";
  if (S.modo === "audio") {
    if (!S.audios.length) return "Adicione o áudio da fala";
    if (S.corte && !S.ffmpeg) return "Cortar silêncios precisa do ffmpeg";
  } else {
    if (!S.voz) return "Escolha uma voz";
    if (!$("#txtScript").value.trim()) return "Escreva o texto da fala";
  }
  return "";
}

function atualizaGerar() {
  const m = motivo();
  const n = S.modo === "audio" ? S.audios.length : 1;
  $("#btnGerar").disabled = !!m;
  $("#gerarTxt").textContent = m || (n > 1 ? `Gerar ${n} vídeos` : "Gerar vídeo");
  $("#gerarPill").textContent = `${S.formato} · ${S.res}`;
}

function resumoAvancado() {
  const mov = $("#txtMov").value.trim();
  const pasta = S.pasta.split(/[\\/]/).filter(Boolean).slice(-2).join("\\");
  $("#avResumo").textContent = `${mov ? "movimento: " + mov : "sem movimento extra"} · ${pasta}`;
  $("#pastaTxt").textContent = S.pasta;
  $("#pastaTxt").title = S.pasta;
}

/* ------------------------------------------------------------------------------------------------ conta */

function setConta(c) {
  S.conectado = !!c;
  S.conta = c;
  $("#conta").classList.toggle("hidden", !c);
  if (c) {
    const email = c.email || "conta HeyGen";
    $("#contaTxt").innerHTML = `Conectado <em>· ${esc(email)}</em>`;
    $("#menuEmail").textContent = email;
    $("#menuPlano").textContent = c.plan ? `plano ${c.plan}` : "";
  }
  atualizaGerar();
}

const NOTA_PADRAO = "O acesso fica criptografado neste PC. Dá para sair quando quiser.";

function portao(estado, txt) {
  const p = $("#portao");
  if (estado === "fora") {
    p.classList.add("saindo");
    setTimeout(() => p.classList.add("hidden"), 300);
    return;
  }
  p.classList.remove("hidden", "saindo");
  const cfg = {
    abrindo: ["roda", "pessoa", "Abrindo…", ""],
    conferindo: ["roda", "pessoa", "Conferindo sua conta…", "Um instante, estamos falando com a HeyGen."],
    conectar: ["", "ligar", "Conecte sua conta HeyGen", "O login acontece no site da HeyGen, no seu navegador. Sua senha nunca passa pelo Avatarize."],
    aguardando: ["roda", "ligar", "Termine o login no navegador", "Abrimos a página da HeyGen. Entre na sua conta e autorize; depois é só voltar aqui."],
    erro: ["erro", "alerta", "Não deu para conectar", ""],
  }[estado];
  $("#pIc").className = "p-ic " + cfg[0];
  $("#pIc").innerHTML = ic(cfg[1]);
  $("#pTit").textContent = cfg[2];
  $("#pTxt").textContent = txt || cfg[3];
  $("#pTxt").classList.toggle("p-erro", estado === "erro");
  const btn = $("#btnConectar");
  btn.classList.toggle("hidden", !["conectar", "erro"].includes(estado));
  $(".gtxt", btn).textContent = estado === "erro" ? "Tentar de novo" : "Conectar HeyGen";
  $("#btnCancelarLogin").classList.toggle("hidden", estado !== "aguardando");
  $("#pNota").textContent = estado === "aguardando" ? "" : NOTA_PADRAO;
}

async function conectar(trocar = false) {
  S.cancelou = false;
  const r = await api.connect(trocar);
  if (r && r.erro) { toast(r.erro, "erro"); return; }
  if (trocar) setConta(null);
  portao("aguardando");
}

/* ------------------------------------------------------------------------------------------------ foto e áudios */

function setFoto(f) {
  S.foto = f;
  $("#dzFoto").classList.toggle("hidden", !!f);
  $("#fotoCard").classList.toggle("hidden", !f);
  if (f) {
    $("#fotoThumb").src = f.thumb || "logo.png";
    $("#fotoNome").textContent = f.name;
    $("#fotoNome").title = f.name;
    $("#fotoInfo").textContent = f.info;
  }
  atualizaGerar();
}

function addAudios(lista) {
  for (const a of lista || []) if (!S.audios.some((x) => x.id === a.id)) S.audios.push(a);
  renderAudios();
}

function renderAudios() {
  $("#listaAudio").innerHTML = S.audios.map((a) =>
    `<li>${ic("onda", "wave")}<b title="${esc(a.name)}">${esc(a.name)}</b><span>${esc(a.dur || "")}</span>` +
    `<button class="fantasma" data-rm="${esc(a.id)}" aria-label="Remover ${esc(a.name)}">${ic("x")}</button></li>`).join("");
  atualizaGerar();
}

async function escolherFoto() {
  const f = await api.pick_photo();
  if (f) setFoto(f);
}

async function escolherAudios() {
  addAudios(await api.pick_audios());
}

function modo(v) {
  S.modo = v;
  $("#pAudio").classList.toggle("hidden", v !== "audio");
  $("#pTexto").classList.toggle("hidden", v !== "texto");
  $$("#segModo button").forEach((b) => b.classList.toggle("on", b.dataset.v === v));
  atualizaGerar();
}

function setVoz(v) {
  S.voz = v;
  $("#vozNome").textContent = v ? v.name : "Escolher voz";
  const extra = v ? [v.minha ? "sua voz clonada" : "", { female: "feminina", male: "masculina" }[v.gender] || "", v.language || ""].filter(Boolean).join(" · ") : "";
  $("#vozInfo").textContent = v ? extra || "voz da HeyGen" : "clonadas ou da biblioteca da HeyGen";
  atualizaGerar();
}

/* ------------------------------------------------------------------------------------------------ vozes */

function renderChips() {
  $("#chipsMotor").innerHTML = MOTORES.map(([k, n]) =>
    `<button data-m="${k}" class="${k === S.motor ? "on" : ""}">${k === PRIVADAS ? ic("estrela") : ""}${n}</button>`).join("");
}

async function carregaVozes(forcar = false) {
  const m = S.motor;
  if (!forcar && S.vozes[m]) return renderVozes();
  S.carregando.add(m);
  renderVozes();
  const r = await api.voices(m);
  S.carregando.delete(m);
  if (r.erro) { if (S.motor === m) renderVozes(r.erro); return; }
  S.vozes[m] = r.vozes;
  if (S.motor === m) renderVozes();
}

function renderVozes(erro) {
  const box = $("#listaVozes"), m = S.motor, q = $("#buscaVoz").value.trim().toLowerCase();
  $("#vozesQtd").textContent = "";
  if (S.carregando.has(m)) { box.innerHTML = `<div class="nota">${ic("carrega", "gira")}Carregando vozes…</div>`; return; }
  if (erro) { box.innerHTML = `<div class="nota">${ic("alerta")}${esc(erro)}</div>`; return; }
  const lista = (S.vozes[m] || []).filter((v) => !q || v.name.toLowerCase().includes(q));
  if (!lista.length) {
    const msg = q ? "Nenhuma voz com esse nome." : m === PRIVADAS
      ? "Você ainda não tem vozes clonadas.<br>Use “Clonar minha voz” ou escolha outro motor." : "Nenhuma voz neste motor.";
    box.innerHTML = `<div class="nota">${ic(m === PRIVADAS ? "mic" : "busca")}<span>${msg}</span></div>`;
    return;
  }
  $("#vozesQtd").textContent = `${lista.length} ${lista.length > 1 ? "vozes" : "voz"}`;
  box.innerHTML = lista.slice(0, 300).map((v) => {
    const av = m === PRIVADAS ? ic("estrela") : v.gender === "female" ? "♀" : v.gender === "male" ? "♂" : ic("pessoa");
    return `<button data-id="${esc(v.id)}" class="${S.voz && S.voz.id === v.id ? "on" : ""}"><span class="av">${av}</span>` +
      `<b>${esc(v.name)}</b><small>${esc(v.language || "")}</small></button>`;
  }).join("");
}

function abrirVozes() {
  renderChips();
  $("#buscaVoz").value = "";
  $("#dlgVoz").showModal();
  carregaVozes();
}

/* ------------------------------------------------------------------------------------------------ clonagem */

function abrirClone() {
  if (!S.clonando) {
    $("#cloneNome").value = "";
    S.cloneAudio = null;
    $("#cloneAudioNome").textContent = "Nenhum arquivo";
    cloneStatus("");
  }
  $("#dlgClone").showModal();
}

function cloneStatus(msg, tipo = "") {
  const st = $("#cloneStatus");
  st.textContent = msg;
  st.className = "status " + tipo;
}

function eventoClone(e) {
  if (e.estado === "progresso") { cloneStatus(e.msg); return; }
  S.clonando = false;
  const btn = $("#btnCloneOk");
  btn.disabled = false;
  if (e.estado === "erro") { cloneStatus(e.msg, "erro"); if (!$("#dlgClone").open) toast("A clonagem falhou: " + e.msg, "erro"); return; }
  delete S.vozes[PRIVADAS];
  setVoz({ ...e.voz, minha: true });
  modo("texto");
  cloneStatus("Voz clonada! Já está selecionada.", "ok");
  toast(`Voz “${e.voz.name}” clonada`, "ok");
  setTimeout(() => $("#dlgClone").open && $("#dlgClone").close(), 1400);
}

/* ------------------------------------------------------------------------------------------------ fila */

function jobHTML(j) {
  const badge = {
    queued: `<span class="badge b-fila">${ic("relogio")}Na fila</span>`,
    running: `<span class="badge b-gera">${ic("carrega", "gira")}Gerando</span>`,
    done: `<span class="badge b-ok">${ic("check")}Pronto</span>`,
    error: `<span class="badge b-erro">${ic("alerta")}Erro</span>`,
  }[j.state];
  const meta = [j.mode === "texto" ? `voz: ${j.voice}` : "", j.photo, `${j.aspect} · ${j.resolution}`, EXPR[j.expr]]
    .filter(Boolean).map(esc).join(" · ");
  let direita = "", corpo = "";
  if (j.state === "queued") {
    direita = `<button class="fantasma sm" data-a="remover">${ic("x")}Tirar da fila</button>`;
  } else if (j.state === "running") {
    const n = j.steps.length, i = j.step ? j.steps.indexOf(j.step) : 0;
    const pct = Math.max(4, Math.round(((i + (j.step === "gerando" ? 0.5 : 0.3)) / n) * 100));
    corpo = `<div class="etapa"><b>Etapa ${i + 1} de ${n} · ${esc(ETAPA[j.step] || "Iniciando")}</b>` +
      `<span class="tempo" data-inicio="${j.started || ""}"></span></div><div class="barra"><i style="width:${pct}%"></i></div>` +
      (j.msg ? `<div class="msg">${esc(j.msg)}</div>` : "");
  } else if (j.state === "done") {
    direita = `<span class="hora">${hora(j.finished)}</span><button class="fantasma icone-btn" data-a="remover" title="Tirar da lista">${ic("lixo")}</button>`;
    corpo = `<div class="acoes"><button class="azul" data-a="abrir">${ic("play")}Abrir vídeo</button>` +
      `<button class="contorno" data-a="pasta">${ic("pasta")}Abrir pasta</button><span class="arq" title="${esc(j.out)}">${esc(j.out)}</span></div>`;
  } else if (j.state === "error") {
    direita = `<button data-a="retry">${ic("refresh")}Tentar de novo</button><button class="fantasma icone-btn" data-a="remover" title="Tirar da lista">${ic("lixo")}</button>`;
    corpo = `<div class="erro-box">${ic("alerta")}<span>${esc(j.error)}</span></div>`;
  }
  return `<div class="job-topo"><img class="th" src="${esc(j.thumb || "logo.png")}" alt="">` +
    `<div class="job-tit"><div class="l1"><b title="${esc(j.title)}">${esc(j.title)}</b>${badge}</div><div class="meta">${meta}</div></div>` +
    `${direita}</div>${corpo}`;
}

function upsertJob(j) {
  S.jobs.set(j.id, j);
  let el = document.getElementById("job-" + j.id);
  if (!el) {
    el = document.createElement("article");
    el.id = "job-" + j.id;
    $("#lista").prepend(el);
  }
  el.className = "job" + (j.state === "running" ? " rodando" : j.state === "error" ? " erro" : "");
  el.innerHTML = jobHTML(j);
  tique();
  contadores();
}

function contadores() {
  const c = { running: 0, queued: 0, done: 0, error: 0 };
  S.jobs.forEach((j) => c[j.state]++);
  const b = [];
  if (c.running) b.push(`<span class="badge b-gera">${c.running} gerando</span>`);
  if (c.queued) b.push(`<span class="badge b-fila">${c.queued} na fila</span>`);
  if (c.done) b.push(`<span class="badge b-ok">${c.done} ${c.done > 1 ? "prontos" : "pronto"}</span>`);
  if (c.error) b.push(`<span class="badge b-erro">${c.error} com erro</span>`);
  $("#badges").innerHTML = b.join("");
  $("#lista").classList.toggle("hidden", !S.jobs.size);
  $("#vazio").classList.toggle("hidden", !!S.jobs.size);
}

function tique() {
  $$(".tempo[data-inicio]").forEach((t) => {
    if (!t.dataset.inicio) return;
    const s = Math.max(0, Math.floor((Date.now() - Number(t.dataset.inicio)) / 1000));
    t.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  });
}
setInterval(tique, 1000);

/* ------------------------------------------------------------------------------------------------ eventos do Python */

window.AV = {
  evento(e) {
    switch (e.tipo) {
      case "conta":
        if (e.estado === "ok") {
          setConta(e.conta);
          portao("fora");
          if (e.conta && e.conta.aviso) toast("Não consegui confirmar a conta agora: " + e.conta.aviso, "erro");
        } else if (e.estado === "fora") {
          setConta(null);
          portao("conectar", e.msg);
        } else if (S.cancelou) {
          setConta(null);
          portao("conectar");
        } else {
          setConta(null);
          portao("erro", e.msg);
        }
        break;
      case "status":
        if (!S.conectado) $("#pNota").textContent = e.msg;
        break;
      case "job":
        upsertJob(e.job);
        if (e.job.state === "done") toast(`Vídeo pronto: ${e.job.out}`, "ok");
        break;
      case "clone":
        eventoClone(e);
        break;
      case "drop":
        if (e.foto) setFoto(e.foto);
        if (e.audios && e.audios.length) { modo("audio"); addAudios(e.audios); }
        if (e.outros && !e.foto && !(e.audios || []).length) toast("Arraste uma foto ou um áudio.", "erro");
        break;
    }
  },
};

/* ------------------------------------------------------------------------------------------------ ligações */

function liga() {
  segmentado("segModo", modo);
  segmentado("segFormato", (v) => { S.formato = v; atualizaGerar(); });
  segmentado("segRes", (v) => { S.res = v; atualizaGerar(); });
  segmentado("segExpr", (v) => { S.expr = v; });
  segmentado("segCorte", (v) => { S.nivel = v; });

  for (const [zona, acao] of [["#dzFoto", escolherFoto], ["#dzAudio", escolherAudios]]) {
    $(zona).addEventListener("click", acao);
    $(zona).addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); acao(); } });
  }
  $("#btnTrocarFoto").onclick = escolherFoto;
  $("#listaAudio").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-rm]");
    if (!b) return;
    S.audios = S.audios.filter((a) => a.id !== b.dataset.rm);
    api.remove_file(b.dataset.rm);
    renderAudios();
  });

  // arrastar e soltar: o Python recebe o caminho real (pywebview); aqui só o realce
  document.addEventListener("dragover", (e) => {
    e.preventDefault();
    $$(".drop").forEach((d) => d.classList.toggle("sobre", d.contains(e.target)));
  });
  document.addEventListener("dragleave", (e) => { if (!e.relatedTarget) $$(".drop").forEach((d) => d.classList.remove("sobre")); });
  document.addEventListener("drop", (e) => { e.preventDefault(); $$(".drop").forEach((d) => d.classList.remove("sobre")); });

  $("#chkCorte").addEventListener("change", (e) => {
    S.corte = e.target.checked;
    $("#segCorte").classList.toggle("trava", !S.corte);
    atualizaGerar();
  });
  $("#txtScript").addEventListener("input", (e) => {
    const n = e.target.value.length;
    $("#contador").textContent = `${n.toLocaleString("pt-BR")} ${n === 1 ? "caractere" : "caracteres"}`;
    atualizaGerar();
  });
  $("#txtMov").addEventListener("input", resumoAvancado);
  $("#btnPasta").onclick = async () => {
    const p = await api.pick_out_dir();
    if (p) { S.pasta = p; resumoAvancado(); }
  };

  $("#btnVoz").onclick = abrirVozes;
  $("#chipsMotor").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-m]");
    if (!b) return;
    S.motor = b.dataset.m;
    renderChips();
    carregaVozes();
  });
  $("#buscaVoz").addEventListener("input", () => renderVozes());
  $("#btnAtualizarVozes").onclick = () => carregaVozes(true);
  $("#listaVozes").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-id]");
    if (!b) return;
    const v = (S.vozes[S.motor] || []).find((x) => x.id === b.dataset.id);
    if (!v) return;
    setVoz({ ...v, minha: S.motor === PRIVADAS });
    $("#dlgVoz").close();
  });

  $("#btnClonar").onclick = abrirClone;
  $("#btnCloneAudio").onclick = async () => {
    const f = await api.pick_clone_audio();
    if (f) { S.cloneAudio = f; $("#cloneAudioNome").textContent = f.name; }
  };
  $("#btnCloneOk").onclick = async () => {
    const nome = $("#cloneNome").value.trim();
    if (!nome || !S.cloneAudio) { cloneStatus("Preencha o nome e escolha o áudio.", "erro"); return; }
    const r = await api.clone(S.cloneAudio.id, nome);
    if (r.erro) { cloneStatus(r.erro, "erro"); return; }
    S.clonando = true;
    $("#btnCloneOk").disabled = true;
    cloneStatus("Começando…");
  };
  $$("[data-fecha]").forEach((b) => (b.onclick = () => b.closest("dialog").close()));

  $("#btnGerar").onclick = async () => {
    if (motivo()) return;
    const btn = $("#btnGerar");
    btn.disabled = true;
    try {
      const r = await api.generate({
        modo: S.modo, audios: S.audios.map((a) => a.id), texto: $("#txtScript").value.trim(), voz: S.voz,
        formato: S.formato, res: S.res, expr: S.expr, corte: S.corte, nivel: S.nivel, movimento: $("#txtMov").value.trim(),
      });
      if (r.erro) { toast(r.erro, "erro"); return; }
      r.jobs.forEach(upsertJob);
      toast(r.jobs.length > 1 ? `${r.jobs.length} vídeos na fila` : "Vídeo na fila", "ok");
      if (S.modo === "audio") { S.audios = []; renderAudios(); }
    } finally {
      atualizaGerar();
    }
  };

  $("#lista").addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-a]");
    if (!b) return;
    const card = b.closest(".job"), id = Number(card.id.slice(4));
    const a = b.dataset.a;
    if (a === "abrir") { const r = await api.open_video(id); if (r && r.erro) toast(r.erro, "erro"); }
    else if (a === "pasta") api.open_folder();
    else if (a === "retry") { const j = await api.retry(id); if (j) upsertJob(j); }
    else if (a === "remover" && (await api.remove(id))) { S.jobs.delete(id); card.remove(); contadores(); }
  });
  $("#btnAbrirPasta").onclick = () => api.open_folder();

  const menu = $("#menuConta");
  $("#btnConta").onclick = (e) => {
    e.stopPropagation();
    menu.classList.toggle("hidden");
    $("#btnConta").setAttribute("aria-expanded", String(!menu.classList.contains("hidden")));
  };
  document.addEventListener("click", (e) => { if (!menu.contains(e.target)) menu.classList.add("hidden"); });
  $("#btnTrocar").onclick = () => { menu.classList.add("hidden"); conectar(true); };
  $("#btnSair").onclick = async () => {
    menu.classList.add("hidden");
    const r = await api.logout();
    if (r && r.erro) { toast(r.erro, "erro"); return; }
    setConta(null);
    S.vozes = {};
    setVoz(null);
    portao("conectar");
  };
  $("#btnConectar").onclick = () => conectar(false);
  $("#btnCancelarLogin").onclick = () => { S.cancelou = true; api.cancel_connect(); portao("conectar"); };
  $$("#devBy, .devlink").forEach((a) => (a.onclick = (e) => { e.preventDefault(); api.open_dev(); }));
}

/* ------------------------------------------------------------------------------------------------ início */

let iniciado = false;
async function inicia() {
  if (iniciado || !window.pywebview || !window.pywebview.api || !window.pywebview.api.init) return;
  iniciado = true;
  api = window.pywebview.api;
  const st = await api.init();
  $("#ver").textContent = "v" + st.versao;
  S.ffmpeg = st.ffmpeg;
  S.pasta = st.pasta;
  const ff = $("#ffTxt");
  ff.className = "ff" + (st.ffmpeg ? "" : " aviso");
  ff.innerHTML = st.ffmpeg ? "<i></i>ffmpeg pronto" : "<i></i>ffmpeg não encontrado: cortar silêncio e converter áudio ficam desligados";
  if (!st.ffmpeg) {
    $("#chkCorte").disabled = true;
    $("#dicaCorte").textContent = "Precisa do ffmpeg instalado neste PC.";
    $("#dicaCorte").classList.add("aviso");
  }
  (st.jobs || []).forEach(upsertJob);
  contadores();
  resumoAvancado();
  atualizaGerar();
  if (st.conectado) { portao("conferindo"); api.check_account(); }
  else portao("conectar");
}

icones();
liga();
portao("abrindo");
window.addEventListener("pywebviewready", inicia);
inicia();
