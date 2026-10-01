import { locale, initLocale, localize } from "./i18n.js";
import { StrategyBoard } from "./board.js";
import {
  POWERS,
  COLORS,
  ACTIONS,
  titleCase,
  escapeHTML as esc,
  provinceKey,
  orderKey,
  orderAction,
  groupLegal,
  reconcileDraft,
  humanOrder,
  phaseLabel,
  adjustmentQuota,
  actionTargets,
} from "./rules.js";

const $ = (id) => document.getElementById(id);
const storage = {
  get(key) {
    try {
      return JSON.parse(sessionStorage.getItem(key));
    } catch {
      return null;
    }
  },
  set(key, value) {
    try {
      sessionStorage.setItem(key, JSON.stringify(value));
    } catch {}
  },
  remove(key) {
    try {
      sessionStorage.removeItem(key);
    } catch {}
  },
};
let session = storage.get("diplomind.session") || {},
  state = null,
  boardData = null,
  source = null,
  activeView = "home",
  activeTab = "orders",
  activeChannel = "群聊",
  draft = {},
  selectedUnit = null,
  editorAction = null,
  editorChoice = null,
  lastTurn = null,
  lastPhase = null,
  fetchGeneration = 0,
  loadingBoard = false,
  connected = false,
  busy = new Set(),
  chatSeen = {},
  lastChatSignature = "",
  sound = false,
  lastOrderSignature = "",
  checkingSession = false;
let providerInfo = null;
let composeIdentity = null,
  composeDrafts = {},
  composeBoundChannel = null;
let composeStatuses = {},
  composePending = {},
  openedChannels = new Set();
let privateOpenGeneration = 0;
let readyActivation = null,
  readyHeldKey = null;
const roomCatalog = new Map();
const retryRequests = new Map();
const names = () =>
  Object.fromEntries(
    (boardData?.provinces || []).map((p) => [
      p.id,
      locale === "zh" ? p.name_zh || p.name : p.name,
    ]),
  );
const board = new StrategyBoard($("board-host"), {
  onSelect: selectMap,
  onHover: showProvince,
  onMode: updateViewMode,
  onError: (message) => toast(message, "warning"),
});
const draftsKey = () =>
  `diplomind.draft.${session.code || ""}.${state?.human || "observer"}`;
function toast(message, type = "info") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  while ($("toast-region").children.length >= 2)
    $("toast-region").firstElementChild.remove();
  $("toast-region").append(el);
  setTimeout(() => el.remove(), type === "error" ? 7000 : 3200);
}
function errorMessage(error) {
  const friendly = {
    badpass: "That passcode does not match. Check with the host and try again.",
    seatunavailable:
      "That power already has a player, or the game has started. Choose an open seat or observe.",
    notfound: "That table could not be found. Check the room code.",
    invalidpower: "Choose one of the seven powers or observe.",
  };
  if (friendly[error.message]) return friendly[error.message];
  if (error.status === 401)
    return "Your session is no longer valid. Rejoin the table with your saved seat or choose an open power.";
  if (error.status === 409)
    return (
      error.message ||
      "The table has moved on. Your view has been refreshed; review your next action."
    );
  return error.message || "The connection was interrupted. Please try again.";
}
async function api(path, { method = "GET", body, signal } = {}) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal,
      cache: "no-store",
    });
  } catch (error) {
    throw Object.assign(
      new Error("Cannot reach the table. Check your connection and try again."),
      { network: true },
    );
  }
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(
      "The server returned an unreadable response. Please retry.",
    );
  }
  if (!response.ok) {
    let detail = data.detail;
    if (Array.isArray(detail)) detail = detail.map((d) => d.msg).join("; ");
    throw Object.assign(
      new Error(detail || data.reason || `Request failed (${response.status})`),
      { status: response.status },
    );
  }
  if (data.ok === false)
    throw Object.assign(
      new Error(data.reason || "The action could not be completed."),
      { status: 409 },
    );
  return data;
}
function authPath(path) {
  return `${path}${path.includes("?") ? "&" : "?"}token=${encodeURIComponent(session.token || "")}`;
}
async function act(key, path, extra = {}, options = {}) {
  if (busy.has(key)) return null;
  busy.add(key);
  renderControls();
  if (["say", "orders"].includes(key)) {
    const fingerprint = JSON.stringify({ ...extra, request_id: null });
    const prior = retryRequests.get(key);
    if (prior?.fingerprint === fingerprint) extra.request_id = prior.id;
    else retryRequests.set(key, { fingerprint, id: extra.request_id });
  }
  try {
    const result = await api(path, {
      method: "POST",
      body: { token: session.token, ...extra },
    });
    retryRequests.delete(key);
    if (result.state) renderState(result.state);
    else if (options.refresh !== false) await refreshState();
    return result;
  } catch (error) {
    if (!error.network) retryRequests.delete(key);
    toast(errorMessage(error), "error");
    if (error.status === 409 || error.status === 403)
      await refreshState().catch(() => {});
    return null;
  } finally {
    busy.delete(key);
    renderControls();
  }
}
function actionBody(extra = {}) {
  return { turn_id: state?.turn_id, request_id: crypto.randomUUID(), ...extra };
}
function composeKey() {
  return `diplomind.compose.${session.code || ""}.${state?.human || "observer"}`;
}
function persistCompose() {
  if (!composeIdentity) return;
  storage.set(composeIdentity, {
    activeChannel,
    drafts: composeDrafts,
    pending: composePending,
    opened: [...openedChannels],
  });
}
function validComposeChannel(channel) {
  const info = channelInfo(channel);
  return (
    info.public ||
    Boolean(
      state?.human &&
        info.powers.includes(state.human) &&
        info.recipients.length,
    )
  );
}
function ensureCompose() {
  const identity = composeKey();
  if (composeIdentity === identity) return;
  composeIdentity = identity;
  const saved = storage.get(identity) || {};
  composeDrafts = Object.fromEntries(
    Object.entries(saved.drafts || {}).filter(
      ([channel, text]) =>
        validComposeChannel(channel) && typeof text === "string",
    ),
  );
  composePending = saved.pending || {};
  composeStatuses = {};
  openedChannels = new Set((saved.opened || []).filter(validComposeChannel));
  activeChannel = validComposeChannel(saved.activeChannel || "")
    ? saved.activeChannel
    : "群聊";
  composeBoundChannel = activeChannel;
  $("message-input").value = composeDrafts[activeChannel] || "";
}
function captureCompose() {
  if (!composeIdentity || !composeBoundChannel) return;
  const text = $("message-input").value;
  if (text) composeDrafts[composeBoundChannel] = text;
  else delete composeDrafts[composeBoundChannel];
  persistCompose();
}
function setComposeStatus(channel, text, kind = "draft", requestId = "") {
  composeStatuses[channel] = { text, kind, requestId };
  renderComposeStatus();
}
function renderComposeStatus() {
  let node = $("message-status");
  if (!node) {
    node = document.createElement("p");
    node.id = "message-status";
    node.className = "panel-footnote";
    node.setAttribute("role", "status");
    node.setAttribute("aria-live", "polite");
    $("message-form").append(node);
  }
  const status = composeStatuses[activeChannel];
  node.textContent =
    status?.text ||
    (composeDrafts[activeChannel] ? "Unsent draft saved on this device." : "");
  node.dataset.state = status?.kind || "draft";
  node.dataset.channel = activeChannel;
  node.dataset.requestId = status?.requestId || "";
  node.hidden = !node.textContent;
  $("message-form").dataset.channel = activeChannel;
}
function switchChannel(channel) {
  if (!validComposeChannel(channel)) return;
  captureCompose();
  activeChannel = channel;
  composeBoundChannel = channel;
  $("message-input").value = composeDrafts[channel] || "";
  lastChatSignature = "";
  persistCompose();
  renderChat();
}
function composerAvailable() {
  return Boolean(
    state?.status === "playing" &&
      state.mode === "NEGO" &&
      state.your_turn &&
      state.human &&
      !state.settling &&
      !busy.has("private") &&
      !$("private-dialog").open,
  );
}
function saveDraft() {
  storage.set(draftsKey(), { turn_id: state?.turn_id, draft });
  board.setDraft(draft);
}
function closeDialogs() {
  document.querySelectorAll("dialog[open]").forEach((el) => el.close());
}
function openDialog(id) {
  const dialog = $(id);
  if (!dialog.open) dialog.showModal();
}
function startSound() {
  if (!sound) return;
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator(),
      gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(523, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(784, ctx.currentTime + 0.14);
    gain.gain.setValueAtTime(0.055, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.35);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.36);
    osc.onended = () => ctx.close();
  } catch {}
}
function showView(view) {
  activeView = view;
  $("home-view").hidden = view !== "home";
  $("game-view").hidden = view !== "game";
  $(view === "home" ? "home-board-slot" : "game-board-slot").append(
    $("board-host"),
  );
  requestAnimationFrame(() => board.resize());
  document.title =
    view === "game" && state
      ? `${phaseLabel(state.phase)} · DiploMind`
      : "DiploMind — The diplomatic table";
}
async function goHome() {
  source?.close();
  source = null;
  connected = false;
  showView("home");
  $("header-context").innerHTML =
    '<span class="status-dot"></span> A game of words. A world of consequences.';
  await listRooms();
  loadBoard(false);
  $("resume-session").hidden = !session.token;
}
function setup(kind = "create", code = "") {
  openDialog("setup-dialog");
  document
    .querySelectorAll("[data-setup]")
    .forEach((b) => b.classList.toggle("active", b.dataset.setup === kind));
  $("create-form").hidden = kind !== "create";
  $("join-form").hidden = kind !== "join";
  document
    .querySelectorAll("#setup-dialog .form-error")
    .forEach((el) => (el.textContent = ""));
  if (code) {
    $("join-code").value = code;
    updateJoinPowers(code);
  }
  // Focus only during this synchronous transition. A delayed focus can steal
  // the next field while the user (or an accessibility tool) is already typing.
  $(kind === "join" ? "join-code" : "room-name").focus();
}
function updateJoinPowers(code) {
  const room = roomCatalog.get(String(code).toUpperCase());
  const select = $("join-power");
  for (const opt of select.options) {
    opt.disabled = false;
    if (!opt.value) continue;
    const saved = (storage.get("diplomind.seats") || {})[
      String(code).toUpperCase()
    ];
    const occupied = Array.isArray(room?.seats)
      ? room.seats.includes(opt.value)
      : Boolean(room?.seats && Object.hasOwn(room.seats, opt.value));
    const unavailable =
      !saved && (occupied || Boolean(room && room.status !== "lobby"));
    opt.disabled = unavailable;
    opt.textContent =
      titleCase(opt.value) +
      (unavailable
        ? room?.status !== "lobby"
          ? " · game in progress"
          : " · occupied"
        : "");
  }
  if (select.selectedOptions[0]?.disabled) select.value = "";
}
async function listRooms() {
  try {
    const data = await api("/api/rooms");
    roomCatalog.clear();
    for (const room of data.rooms || []) roomCatalog.set(room.code, room);
    $("rooms-list").innerHTML = (data.rooms || []).length
      ? data.rooms
          .map(
            (r) =>
              `<button class="room-card" data-room="${esc(r.code)}"><span class="eyebrow">${esc(r.game_mode === "plus" ? "PLUS PREVIEW" : "CLASSIC")} · ${esc(r.status || "lobby")}${r.locked ? " · PASSCODE" : ""}</span><span class="room-arrow">→</span><h3>${esc(r.name || "An open table")}</h3><p><span>${esc(r.code)} · ${r.humans || 0}/7 HUMAN POWERS</span><span>${r.phase && r.phase !== "-" ? esc(phaseLabel(r.phase)) : "Waiting to begin"}</span></p></button>`,
          )
          .join("")
      : `<div class="empty-rooms"><span class="empty-icon">♧</span><div><strong>A fresh page in history.</strong><p>No open tables yet. Yours could be the first.</p></div><button class="button secondary" id="empty-create">Create a table →</button></div>`;
    $("rooms-list")
      .querySelectorAll("[data-room]")
      .forEach((b) => (b.onclick = () => setup("join", b.dataset.room)));
    $("empty-create")?.addEventListener("click", () => setup("create"));
  } catch (error) {
    $("rooms-list").innerHTML =
      '<div class="empty-rooms"><div><strong>The table list is unavailable</strong><p>Try Refresh, or create a table when the server reconnects.</p></div></div>';
    toast(errorMessage(error), "error");
  }
}
async function submitSetup(event, kind) {
  event.preventDefault();
  const form = event.currentTarget,
    button = form.querySelector("[type=submit]"),
    error = form.querySelector(".form-error");
  if (button.disabled) return;
  button.disabled = true;
  error.textContent = "";
  try {
    const data = Object.fromEntries(new FormData(form));
    data.power = data.power || null;
    if (kind === "join") {
      data.code = data.code.trim().toUpperCase();
      const seats = storage.get("diplomind.seats") || {};
      data.token = seats[data.code] || null;
    }
    const response = await api(`/api/room/${kind}`, {
      method: "POST",
      body: data,
    });
    if (!response.token || !response.code)
      throw new Error("The server did not return a seat. Please retry.");
    session = { token: response.token, code: response.code };
    storage.set("diplomind.session", session);
    const seats = storage.get("diplomind.seats") || {};
    seats[session.code] = session.token;
    storage.set("diplomind.seats", seats);
    closeDialogs();
    await enterTable();
  } catch (e) {
    error.textContent = errorMessage(e);
  } finally {
    button.disabled = false;
  }
}
async function enterTable() {
  if (!session.token) return;
  captureCompose();
  composeIdentity = null;
  composeBoundChannel = null;
  source?.close();
  lastPhase = null;
  lastTurn = null;
  selectedUnit = null;
  draft = {};
  activeChannel = "群聊";
  chatSeen = {};
  lastChatSignature = "";
  try {
    const data = await api(authPath("/api/state"));
    if (data.mode === "MENU")
      throw new Error("This table is no longer available.");
    showView("game");
    const cleanURL = new URL(location.href);
    cleanURL.searchParams.delete("join");
    window.history.replaceState(
      {},
      "",
      cleanURL.pathname + cleanURL.search + cleanURL.hash,
    );
    renderState(data);
    connect();
    loadBoard(true);
    if (data.status === "lobby" && data.owner) openRoom();
  } catch (error) {
    toast(errorMessage(error), "error");
    if (error.status === 401) {
      storage.remove("diplomind.session");
      session = {};
    }
    goHome();
  }
}
function connect() {
  source?.close();
  source = new EventSource(
    `/api/stream/${encodeURIComponent(session.code)}?token=${encodeURIComponent(session.token)}`,
  );
  source.onopen = () => {
    connected = true;
    updateConnection();
  };
  source.onerror = async () => {
    connected = false;
    updateConnection();
    if (checkingSession) return;
    checkingSession = true;
    try {
      await api(authPath("/api/state"));
    } catch (error) {
      if (error.status === 401) {
        source?.close();
        source = null;
        storage.remove("diplomind.session");
        const seats = storage.get("diplomind.seats") || {};
        delete seats[session.code];
        storage.set("diplomind.seats", seats);
        session = {};
        toast(
          "Your seat is no longer active. Return to an open table or ask the host for a new invitation.",
          "warning",
        );
        goHome();
      }
    } finally {
      checkingSession = false;
    }
  };
  source.addEventListener("clock", (event) => {
    try {
      const clock = JSON.parse(event.data);
      // An action response may already have supplied a newer full snapshot.
      if (!state || clock.room !== state.room || clock.version !== state.version ||
          clock.turn_id !== (state.turn_id ?? null)) return;
      const presenceChanged = JSON.stringify(state.dropped) !== JSON.stringify(clock.dropped);
      state.secs_left = clock.secs_left;
      state.dropped = clock.dropped;
      state.short = clock.short;
      if (!connected) {
        connected = true;
        updateConnection();
      }
      renderClock();
      if (presenceChanged) renderNotice();
    } catch (error) {
      console.warn("Ignored incomplete clock update.");
    }
  });
  source.onmessage = (event) => {
    try {
      const next = JSON.parse(event.data);
      if (next.error) {
        connected = false;
        updateConnection();
        toast(next.error, "error");
        return;
      }
      connected = true;
      updateConnection();
      renderState(next);
    } catch (error) {
      console.warn("Ignored incomplete state update.");
    }
  };
}
function updateConnection() {
  const el = $("connection-status");
  el.classList.toggle("offline", !connected);
  el.innerHTML = `<i></i>${connected ? "Live" : "Reconnecting"}`;
  el.title = connected
    ? "Connected to the table"
    : "Your local drafts are safe. Reconnecting automatically.";
  renderControls();
}
async function refreshState() {
  if (!session.token || activeView !== "game") return;
  const data = await api(authPath("/api/state"));
  renderState(data);
  return data;
}
async function loadBoard(auth) {
  const generation = ++fetchGeneration;
  loadingBoard = true;
  try {
    const data = await api(auth ? authPath("/api/board") : "/api/board");
    if (generation !== fetchGeneration) return;
    boardData = data;
    board.setData(data);
    renderOrders();
  } catch (error) {
    if (generation === fetchGeneration)
      toast(
        "The map could not refresh. Your command desk is still available.",
        "warning",
      );
  } finally {
    loadingBoard = false;
  }
}
function renderState(next) {
  if (!next || !next.mode) return;
  const previous = state;
  state = next;
  ensureCompose();
  window._last = state;
  const changedTurn = next.turn_id !== lastTurn;
  const changedPhase = next.phase !== lastPhase;
  if (changedTurn) {
    lastTurn = next.turn_id;
    const saved = storage.get(draftsKey());
    draft =
      saved && saved.turn_id === next.turn_id
        ? reconcileDraft(saved.draft, next.legal || [])
        : {};
    selectedUnit = null;
    editorAction = null;
    editorChoice = null;
    if (previous?.turn_id && next.mode === "ORDERS") {
      toast("The command desk is open. Write your orders.");
      startSound();
      selectTab("orders");
    } else if (previous?.turn_id && next.mode === "NEGO") {
      selectTab("diplomacy");
    }
    saveDraft();
  } else draft = reconcileDraft(draft, next.legal || []);
  if (next.order_submitted && Array.isArray(next.submitted_orders)) {
    draft = Object.fromEntries(
      next.submitted_orders.map((o) => [orderKey(o), o]),
    );
    saveDraft();
  }
  if (changedPhase) {
    lastPhase = next.phase;
    if (activeView === "game") loadBoard(true);
    if (
      previous?.phase &&
      previous.phase !== "-" &&
      next.phase !== previous.phase
    ) {
      toast(
        `${phaseLabel(next.phase)} · ${next.phase_type === "R" ? "Retreats required" : next.phase_type === "A" ? "Winter adjustments" : "A new diplomatic chapter"}`,
      );
      startSound();
    }
  }
  $("header-context").innerHTML =
    `<span class="status-dot"></span>${esc(next.rname || "The diplomatic table")} <span style="opacity:.45"> / </span> ${esc(next.room || session.code)}`;
  $("room-label").textContent =
    `TABLE ${next.room || session.code} / ${next.rname || "THE EUROPEAN ACCORD"}`;
  $("phase-title").textContent = phaseLabel(next.phase);
  $("phase-subtitle").textContent =
    next.status === "lobby"
      ? "Claim a power. Invite your allies. Shape what comes next."
      : next.phase_type === "R"
        ? "A retreat can be the beginning of a comeback."
        : next.phase_type === "A"
          ? "The balance of power is changing."
          : next.mode === "NEGO"
            ? `Negotiation round ${next.round || 1} · Make your words count`
            : "All orders resolve together. Choose your next move.";
  $("mode-pill").textContent =
    next.game_mode === "plus" ? "PLUS PREVIEW" : "CLASSIC";
  document.title = `${phaseLabel(next.phase)} · DiploMind`;
  for (const stage of document.querySelectorAll("[data-stage]"))
    stage.classList.toggle(
      "active",
      stage.dataset.stage === (next.settling ? "RESOLVING" : next.mode),
    );
  renderClock();
  renderNotice();
  renderSeat();
  renderPowers();
  renderOrders();
  renderChat();
  renderControls();
  if ($("room-dialog").open) renderRoom();
  if (next.end || next.status === "ended") renderResult();
}
function renderClock() {
  if (!state) return;
  const secs = state.secs_left;
  $("round-clock").textContent =
    state.status === "paused"
      ? "Ⅱ Paused"
      : state.status === "lobby"
        ? "Waiting for host"
        : secs != null
          ? `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")} remaining`
          : "No time limit";
  $("round-clock").classList.toggle(
    "urgent",
    secs != null && secs < 30 && state.status === "playing",
  );
}
function renderNotice() {
  const s = state,
    el = $("game-notice");
  let message = "",
    button = "";
  if (s.status === "lobby") {
    message = s.owner
      ? "Your table is ready. Invite friends or start with AI filling the open powers."
      : "Waiting for the host to start. Your seat has been reserved.";
    if (s.owner)
      button =
        '<button class="button secondary compact" id="notice-start">Start game →</button>';
  } else if (s.status === "paused") {
    message =
      "The table is paused. Drafts are saved; play resumes when the host is ready.";
    if (s.owner)
      button =
        '<button class="button secondary compact" id="notice-resume">Resume →</button>';
  } else if (s.status === "ended" || s.end) {
    message = s.end?.winner
      ? `${titleCase(s.end.winner)} has prevailed. The chronicle is ready.`
      : s.end?.draw
        ? "The surviving powers share a draw."
        : "The host has ended this game.";
    button =
      '<button class="button secondary compact" id="notice-result">View chronicle →</button>';
  } else if (!s.human)
    message =
      "You’re observing. Public messages and the board are visible; private conversations and orders stay private.";
  else if (s.dropped?.length)
    message = `Waiting for disconnected players: ${s.dropped.map(titleCase).join(", ")}. Their seats remain reserved.`;
  el.hidden = !message;
  el.innerHTML = message ? `<span>${esc(message)}</span>${button}` : "";
  $("notice-start")?.addEventListener("click", startGame);
  $("notice-resume")?.addEventListener("click", togglePause);
  $("notice-result")?.addEventListener("click", openHistory);
}
function renderSeat() {
  const p = state.human,
    c = p ? COLORS[p] : "#829286";
  $("seat-header").style.setProperty("--power-color", c);
  $("seat-header").innerHTML =
    `<div class="seat-crest">${p ? titleCase(p)[0] : "◈"}</div><div><p class="eyebrow">${p ? "YOUR POWER" : "A VIEW FROM THE GALLERY"}</p><h2>${p ? titleCase(p) : "Observer"}</h2><p>${p ? `<span data-no-translate>${esc(state.seat_names?.[p] || "You")}</span> · ${(state.centers || {})[p] ?? "—"} supply centers` : "The public table, unfolding"}</p></div><span class="seat-badge">${state.owner ? "HOST" : p ? "HUMAN" : "GUEST"}</span>`;
}
function renderPowers() {
  const s = state;
  $("powers-list").innerHTML = POWERS.map((p) => {
    const n = s.centers?.[p] ?? boardData?.centers?.[p]?.length ?? 0;
    return `<div class="power-card ${s.human === p ? "you" : ""}" style="--power-color:${COLORS[p]}"><div class="power-name"><span class="power-dot"></span>${titleCase(p)}</div><div class="power-score">${n}<span>${s.human === p ? "YOU" : s.seats?.includes(p) ? "HUMAN" : "AI"}</span></div><div class="power-progress"><i style="width:${Math.min(100, (n / 18) * 100)}%"></i></div></div>`;
  }).join("");
}
function orderEditable() {
  return Boolean(
    state?.human &&
      state.mode === "ORDERS" &&
      state.status === "playing" &&
      !state.order_submitted &&
      !state.settling &&
      !busy.has("orders"),
  );
}
function displayGroups() {
  if (state?.mode === "ORDERS") return groupLegal(state.legal || []);
  const units = (boardData?.units || []).filter(
    (u) => u.power === state?.human && !u.dislodged,
  );
  return Object.fromEntries(units.map((u) => [provinceKey(u.location), []]));
}
function renderOrders() {
  if (!state) return;
  const signature = JSON.stringify([
    state.human,
    state.mode,
    state.status,
    state.phase,
    state.order_submitted,
    state.settling,
    state.legal,
    state.adjustment_count,
    selectedUnit,
    draft,
    boardData?.phase,
    boardData?.units,
  ]);
  if (signature === lastOrderSignature) {
    renderReadiness();
    renderControls();
    return;
  }
  lastOrderSignature = signature;
  const s = state,
    groups = displayGroups(),
    unitKeys = Object.keys(groups),
    n = Object.keys(draft).length,
    quota = s.adjustment_count ?? adjustmentQuota(boardData, s.human),
    adjust = s.phase_type === "A";
  $("order-count").textContent = String(n);
  $("desk-eyebrow").textContent = !s.human
    ? "OBSERVER DESK"
    : s.status === "lobby"
      ? "THE OPENING POSITION"
      : s.phase_type === "R"
        ? "RETREAT ORDERS"
        : adjust
          ? "WINTER ADJUSTMENTS"
          : "YOUR ORDERS";
  $("desk-title").textContent = !s.human
    ? "A world in motion."
    : s.order_submitted
      ? "Orders are sealed."
      : s.settling
        ? "The board is changing."
        : s.phase_type === "R"
          ? "Live to fight again."
          : adjust
            ? "A changing balance."
            : "Every move matters.";
  $("desk-description").textContent = !s.human
    ? "Follow the powers, their public negotiations, and the unfolding map."
    : s.status === "lobby"
      ? "Your pieces are in position. The host will open the first round of diplomacy."
      : s.order_submitted
        ? "Your orders are ready. Withdraw them to edit before resolution begins."
        : s.mode !== "ORDERS"
          ? "Diplomacy comes first. Your units will be ready when the command desk opens."
          : s.phase_type === "R"
            ? "Choose a retreat for each dislodged unit. Units without retreat orders are disbanded."
            : adjust
              ? quota > 0
                ? `You may build ${quota} ${quota === 1 ? "unit" : "units"} at vacant home centers. Unused builds are waived.`
                : `Choose ${Math.abs(quota)} ${Math.abs(quota) === 1 ? "unit" : "units"} to disband. Only legal adjustments are shown.`
              : "Choose a unit on the map or below. Draft one legal order for each unit.";
  $("unit-list").innerHTML = unitKeys.length
    ? unitKeys
        .map((loc) => {
          const u = boardData?.units.find(
              (u) => u.power === s.human && provinceKey(u.location) === loc,
            ),
            options = groups[loc],
            type = u?.type || options[0]?.split(" ")[0] || "A";
          const ordered = draft[loc];
          return `<article class="unit-card ${selectedUnit === loc ? "selected" : ""} ${ordered ? "has-order" : ""}" style="--power-color:${COLORS[s.human]}"><button class="unit-button" data-unit="${loc}" ${!orderEditable() ? "disabled" : ""} aria-label="${esc((names()[loc] || loc) + " " + (ordered ? humanOrder(ordered, names()) : "choose order"))}"><span class="unit-symbol">${adjust && quota > 0 ? "+" : type === "F" ? "▰" : "▲"}</span><span><span class="unit-location">${esc(names()[loc] || loc)}</span><span class="unit-order">${ordered ? esc(humanOrder(ordered, names())) : s.mode === "ORDERS" ? (adjust ? "Choose adjustment" : s.phase_type === "R" ? "Retreat or disband" : "Awaiting your command") : (type === "F" ? "Fleet" : "Army") + " · " + loc}</span></span>${ordered ? '<span class="draft-badge">' + (s.order_submitted ? "SEALED" : "DRAFT") + "</span>" : '<span class="unit-chevron">›</span>'}</button></article>`;
        })
        .join("")
    : `<div class="empty-desk"><span class="empty-icon">${s.human ? "♧" : "◈"}</span>${!s.human ? "Great strategies reveal themselves over time." : s.mode === "ORDERS" ? "No units need orders this phase. Submit to confirm readiness." : "Your table is coming together."}</div>`;
  $("unit-list")
    .querySelectorAll("[data-unit]")
    .forEach(
      (button) => (button.onclick = () => selectUnit(button.dataset.unit)),
    );
  if (selectedUnit && !groups[selectedUnit]) selectedUnit = null;
  renderEditor();
  renderReadiness();
  $("orders-summary").innerHTML =
    s.mode === "ORDERS"
      ? `<span>${s.order_submitted ? "✓ Ready for resolution" : `${n} ${n === 1 ? "order" : "orders"} drafted`}</span><span>${adjust ? `${Math.max(0, Math.abs(quota) - n)} ${quota >= 0 ? "builds unused" : "disbands left"}` : `${Math.max(0, unitKeys.length - n)} ${s.phase_type === "R" ? "will disband" : "will hold"}`}</span>`
      : "";
  $("submit-orders").innerHTML =
    s.mode !== "ORDERS"
      ? "Orders open after diplomacy"
      : s.settling
        ? "Resolving orders…"
        : s.order_submitted
          ? "Orders submitted ✓"
          : `Submit ${n ? n + " order" + (n === 1 ? "" : "s") : s.phase_type === "R" ? "disbands" : adjust ? "adjustments" : "holds"} <span>→</span>`;
  $("order-footnote").textContent = s.order_submitted
    ? "You can withdraw only before the table begins resolving."
    : s.mode === "ORDERS"
      ? "Drafts stay on your device until you submit."
      : "Use the Diplomacy tab to propose your next alliance.";
  renderControls();
}
function selectUnit(loc) {
  if (!orderEditable()) return;
  selectedUnit = provinceKey(loc);
  const existing = draft[selectedUnit];
  editorAction = existing ? orderAction(existing) : null;
  editorChoice = existing || null;
  board.setSelection(selectedUnit);
  renderOrders();
  $("map-status").textContent =
    `${names()[selectedUnit] || selectedUnit} selected · choose an order`;
}
function renderEditor() {
  const el = $("order-editor"),
    opts = groupLegal(state?.legal || [])[selectedUnit];
  el.hidden = !selectedUnit || !opts || !orderEditable();
  if (el.hidden) return;
  const actions = [...new Set(opts.map(orderAction))];
  if (!actions.includes(editorAction))
    editorAction = actions.includes("H") ? "H" : actions[0];
  const choices = opts.filter((o) => orderAction(o) === editorAction);
  if (!choices.includes(editorChoice)) editorChoice = choices[0];
  el.innerHTML = `<h3>${esc(names()[selectedUnit] || selectedUnit)}</h3><p>${esc(selectedUnit)} · ${draft[selectedUnit] ? "Edit your draft order" : "Choose from engine-legal orders"}</p><label for="order-action">Order type</label><select id="order-action">${actions.map((a) => `<option value="${a}" ${editorAction === a ? "selected" : ""}>${ACTIONS[a] || a}</option>`).join("")}</select><label for="order-choice">${["-", "R"].includes(editorAction) ? "Destination" : editorAction === "S" ? "Unit and action to support" : editorAction === "C" ? "Army and convoy destination" : "Legal order"}</label><select id="order-choice">${choices.map((o) => `<option value="${esc(o)}" ${editorChoice === o ? "selected" : ""}>${esc(humanOrder(o, names()))} · ${esc(o)}</option>`).join("")}</select><div class="editor-actions"><button class="button primary" id="save-order">${draft[selectedUnit] ? "Update draft" : "Add to orders"} ✓</button><button class="button secondary" id="remove-order" ${draft[selectedUnit] ? "" : "disabled"} aria-label="Remove this draft order">Remove</button><button class="icon-button" id="close-editor" aria-label="Close order editor">×</button></div>`;
  $("order-action").onchange = (e) => {
    editorAction = e.target.value;
    editorChoice = null;
    renderEditor();
  };
  $("order-choice").onchange = (e) => {
    editorChoice = e.target.value;
  };
  $("save-order").onclick = saveOrder;
  $("remove-order").onclick = () => {
    delete draft[selectedUnit];
    saveDraft();
    renderOrders();
  };
  $("close-editor").onclick = () => {
    selectedUnit = null;
    board.setSelection(null);
    renderOrders();
  };
}
function saveOrder() {
  if (!orderEditable() || !editorChoice) return;
  const quota =
    state.adjustment_count ?? adjustmentQuota(boardData, state.human);
  if (
    state.phase_type === "A" &&
    !draft[selectedUnit] &&
    Object.keys(draft).length >= Math.abs(quota)
  ) {
    toast(
      `You may issue only ${Math.abs(quota)} adjustment ${Math.abs(quota) === 1 ? "order" : "orders"} this winter.`,
      "warning",
    );
    return;
  }
  draft[selectedUnit] = editorChoice;
  saveDraft();
  renderOrders();
}
function selectMap(hit) {
  if (activeView !== "game") {
    showProvince(hit);
    return;
  }
  const loc = hit.province,
    groups = displayGroups();
  if (!orderEditable()) {
    showProvince(hit);
    return;
  }
  if (hit.unit?.power === state.human && groups[loc]) {
    selectUnit(loc);
    return;
  }
  if (selectedUnit) {
    const candidates = (
      groupLegal(state.legal || [])[selectedUnit] || []
    ).filter((o) => actionTargets(o).includes(loc));
    if (candidates.length) {
      const same = candidates.filter((o) => orderAction(o) === editorAction);
      editorChoice = (same.length ? same : candidates)[0];
      editorAction = orderAction(editorChoice);
      renderEditor();
      $("map-status").textContent =
        `${humanOrder(editorChoice, names())} · Add to orders to confirm`;
      return;
    }
  }
  if (groups[loc]) {
    selectUnit(loc);
    return;
  }
  showProvince(hit);
}
function showProvince(hit) {
  const tip = $("province-tooltip");
  if (!hit || activeView !== "game") {
    tip.hidden = true;
    return;
  }
  const p = boardData?.provinces.find((p) => p.id === hit.province);
  if (!p) return;
  tip.textContent = `${names()[p.id] || p.name} · ${p.id}${p.center ? " · Supply center" : ""}${p.owner ? " · " + titleCase(p.owner) : ""}${hit.unit ? " · " + (hit.unit.type === "A" ? "Army" : "Fleet") : ""}`;
  tip.hidden = false;
}
function renderReadiness() {
  const s = state;
  if (s.status === "lobby") {
    $("readiness-list").innerHTML =
      '<div class="readiness-title">HUMANS AT THE TABLE</div>' +
      POWERS.map(
        (p) =>
          `<div class="readiness-row"><span class="power-dot" style="--power-color:${COLORS[p]}"></span>${titleCase(p)}<span>${s.seats?.includes(p) ? `<span data-no-translate>${esc(s.seat_names?.[p] || "Human player")}</span>` : "AI fills this seat"}</span></div>`,
      ).join("");
    return;
  }
  const pending = s.mode === "ORDERS" ? s.order_pending || [] : s.pending || [];
  const humans = s.seats || s.humans || [];
  $("readiness-list").innerHTML =
    `<div class="readiness-title"><span>AT THE TABLE</span><span>${s.mode === "ORDERS" ? "ORDER STATUS" : "NEGOTIATION"}</span></div>` +
    humans
      .map(
        (p) =>
          `<div class="readiness-row ${!pending.includes(p) ? "ready" : ""}"><span class="power-dot" style="--power-color:${COLORS[p]}"></span>${titleCase(p)}${p === s.human ? " · you" : ""}<span>${pending.includes(p) ? "Considering…" : "✓ Ready"}</span></div>`,
      )
      .join("") +
    `<div class="readiness-row"><span>◈</span>${7 - humans.length} AI ${7 - humans.length === 1 ? "power" : "powers"}<span>${s.settling ? "Resolving…" : "At the table"}</span></div>`;
}
function selectTab(tab) {
  activeTab = tab;
  $("orders-panel").hidden = tab !== "orders";
  $("diplomacy-panel").hidden = tab !== "diplomacy";
  $("orders-tab").setAttribute("aria-selected", String(tab === "orders"));
  $("diplomacy-tab").setAttribute("aria-selected", String(tab === "diplomacy"));
  if (tab === "diplomacy") renderChat();
}
function channelInfo(channel) {
  const publicChannel =
    channel === "群聊" || channel === "broadcast" || channel === "Public";
  const powers = publicChannel
    ? []
    : channel.split("·").filter((p) => POWERS.includes(p));
  return {
    public: publicChannel,
    powers,
    recipients: powers.filter((p) => p !== state?.human),
  };
}
function renderChat() {
  if (!state) return;
  const channels = { ...(state.channels || { 群聊: [] }) };
  for (const channel of openedChannels)
    if (validComposeChannel(channel)) channels[channel] ||= [];
  if (!Object.hasOwn(channels, activeChannel)) {
    // A channel acknowledged by /open can briefly be absent from an older SSE
    // snapshot. Keep its destination; never silently reroute a private draft.
    if (
      validComposeChannel(activeChannel) &&
      !channelInfo(activeChannel).public
    ) {
      channels[activeChannel] = [];
      openedChannels.add(activeChannel);
    } else {
      captureCompose();
      activeChannel =
        Object.keys(channels).find((c) => channelInfo(c).public) || "群聊";
      composeBoundChannel = activeChannel;
      $("message-input").value = composeDrafts[activeChannel] || "";
    }
  }
  const info = channelInfo(activeChannel);
  let unread = 0;
  for (const [c, m] of Object.entries(channels))
    if (c !== activeChannel)
      unread += Math.max(0, m.length - (chatSeen[c] || 0));
  $("message-count").textContent = String(unread);
  $("channel-list").innerHTML = Object.entries(channels)
    .map(([channel, messages]) => {
      const inf = channelInfo(channel);
      const label = inf.public
        ? "◎ Public"
        : `◌ ${inf.recipients.map((p) => titleCase(p)).join(" + ") || "Private"}`;
      return `<button class="${channel === activeChannel ? "active" : ""} ${channel !== activeChannel && messages.length > (chatSeen[channel] || 0) ? "unread" : ""}" role="tab" aria-selected="${channel === activeChannel}" data-channel="${esc(channel)}">${esc(label)}</button>`;
    })
    .join("");
  $("channel-list")
    .querySelectorAll("[data-channel]")
    .forEach(
      (button) =>
        (button.onclick = () => {
          switchChannel(button.dataset.channel);
        }),
    );
  $("recipient-banner").classList.toggle("private", !info.public);
  $("recipient-banner").textContent = info.public
    ? "PUBLIC CHANNEL · Visible to all powers and observers"
    : `PRIVATE · Visible only to ${info.powers.map(titleCase).join(", ")}`;
  const messages = channels[activeChannel] || [];
  const signature = JSON.stringify([activeChannel, messages]);
  if (signature !== lastChatSignature) {
    const nearBottom =
      $("chat-log").scrollHeight -
        $("chat-log").scrollTop -
        $("chat-log").clientHeight <
      90;
    lastChatSignature = signature;
    $("chat-log").innerHTML = messages.length
      ? messages
          .map((raw) => {
            const text =
              typeof raw === "string" ? raw : raw.text || raw.content || "";
            const match = text.match(
              /(?:^|\s|\()(AUSTRIA|ENGLAND|FRANCE|GERMANY|ITALY|RUSSIA|TURKEY)(?:\)?\s*[:：]|\])/,
            );
            const power = match?.[1];
            return `<article class="chat-message ${power === state.human ? "own" : ""}"><div class="chat-meta">${power ? `<span class="power-dot" style="--power-color:${COLORS[power]}"></span>${titleCase(power)}` : "DIPLOMATIC DISPATCH"}</div><div class="chat-body">${esc(text.replace(/^(?:[SFW]\d+ )?R\d+ (?:我\()?[^:：]+[：:] /, ""))}</div></article>`;
          })
          .join("")
      : `<div class="chat-empty">${info.public ? "Every alliance begins<br>with a few words." : "Some words are best<br>shared in confidence."}<small>${state.status === "lobby" ? "The conversation opens when the game begins." : "Be the first to make a proposal."}</small></div>`;
    if (nearBottom || messages.length < 4)
      $("chat-log").scrollTop = $("chat-log").scrollHeight;
  }
  if (activeTab === "diplomacy") chatSeen[activeChannel] = messages.length;
  $("staged-messages").innerHTML = (state.staged_msgs || []).length
    ? "<span>QUEUED FOR ROUND-END DELIVERY</span>" +
      state.staged_msgs
        .map((text) => `<div class="staged-message">${esc(text)}</div>`)
        .join("")
    : "";
  $("messages-left").textContent =
    `${state.msgs_left ?? 3} ${(state.msgs_left ?? 3) === 1 ? "message" : "messages"} left this round`;
  $("ready-negotiation").textContent = state.human_done
    ? "✓ Ready · waiting for the table"
    : state.mode === "NEGO"
      ? "Ready · finish this round"
      : "Negotiation opens next movement phase";
  $("negotiation-footnote").textContent = !state.human
    ? "Observers can read public messages. Private channels remain hidden."
    : state.human_done
      ? "Your messages are queued. Waiting for the other powers to finish."
      : "Your third message automatically readies you. Choose Ready earlier to finish with fewer messages.";
  renderControls();
}
function renderControls() {
  if (!state) return;
  const playing = state.status === "playing",
    nego = Boolean(
      playing &&
        state.mode === "NEGO" &&
        state.your_turn &&
        state.human &&
        !state.settling,
    );
  const sendBusy = busy.has("say"),
    available = composerAvailable();
  $("message-input").disabled = !available;
  $("send-message").disabled =
    !available ||
    sendBusy ||
    !(state.msgs_left > 0) ||
    !$("message-input").value.trim();
  $("ready-negotiation").disabled = !available || sendBusy || Boolean(state.human_done);
  $("private-form").querySelector('[type="submit"]').disabled =
    busy.has("private");
  $("private-form")
    .querySelectorAll("input")
    .forEach((input) => (input.disabled = busy.has("private")));
  renderComposeStatus();
  $("new-private-button").disabled =
    !state.human || !playing || state.mode !== "NEGO" || busy.has("private");
  $("submit-orders").disabled = !orderEditable();
  $("submit-orders").hidden = Boolean(state.order_submitted);
  $("cancel-orders").hidden = !state.order_submitted;
  $("cancel-orders").disabled =
    !playing || state.settling || busy.has("cancel");
  $("clear-orders").disabled = !orderEditable() || !Object.keys(draft).length;
  $("clear-orders").hidden =
    state.mode !== "ORDERS" || Boolean(state.order_submitted);
  $("start-game").disabled = busy.has("start");
  $("pause-game").disabled = busy.has("pause") || state.settling;
}
async function sendMessage(event) {
  event.preventDefault();
  if (!composerAvailable() || busy.has("say")) return;
  captureCompose();
  const channel = composeBoundChannel,
    raw = composeDrafts[channel] || "",
    content = raw.trim();
  if (!content) {
    setComposeStatus(channel, "Write a message before sending.", "empty");
    return;
  }
  const identity = composeIdentity,
    thirdMessage = state.msgs_left === 1,
    inf = channelInfo(channel);
  const prior = composePending[channel];
  const requestId =
    prior?.turn_id === state.turn_id && prior?.content === content
      ? prior.request_id
      : crypto.randomUUID();
  composePending[channel] = {
    turn_id: state.turn_id,
    content,
    request_id: requestId,
  };
  persistCompose();
  setComposeStatus(
    channel,
    "Sending… Your draft stays saved until the server acknowledges it.",
    "sending",
    requestId,
  );
  const result = await act("say", "/api/say", {
    turn_id: state.turn_id,
    request_id: requestId,
    scope: inf.public ? "broadcast" : "private",
    recipient: [...inf.recipients],
    content,
    skip: false,
  });
  if (composeIdentity !== identity) return;
  if (result) {
    // A delayed acknowledgement must never erase newer text or another channel.
    if (composeDrafts[channel] === raw) {
      delete composeDrafts[channel];
      if (composeBoundChannel === channel && $("message-input").value === raw)
        $("message-input").value = "";
    }
    delete composePending[channel];
    persistCompose();
    setComposeStatus(
      channel,
      composeDrafts[channel]
        ? "Message acknowledged. Your newer draft is still unsent."
        : "Message acknowledged and staged for round-end delivery.",
      "acknowledged",
      requestId,
    );
    toast(thirdMessage
      ? "Your third message was accepted. You’re automatically ready for that round."
      : "Message staged. It will be delivered when the round closes.");
  } else {
    setComposeStatus(
      channel,
      "Delivery unconfirmed. Your draft is saved; retry when ready.",
      "unconfirmed",
      requestId,
    );
  }
  renderControls();
}
function captureReadyInteraction(event) {
  if (event.type === "keydown") {
    if (!["Enter", " ", "Spacebar"].includes(event.key)) return;
    // Holding Enter must not finish another round after an SSE update.
    if (event.repeat || readyHeldKey) {
      event.preventDefault();
      return;
    }
    readyHeldKey = event.key;
  } else if (event.type === "pointerdown" && event.button !== 0) return;
  readyActivation = {
    turn_id: state?.turn_id,
    eligible: composerAvailable() && !busy.has("say") && !state?.human_done,
  };
}
function releaseReadyKey(event) {
  if (event.key === readyHeldKey) readyHeldKey = null;
  // Space activates on keyup: keep its captured turn until the ensuing click.
}
function cancelReadyInteraction() {
  readyActivation = null;
  readyHeldKey = null;
}
async function readyNegotiation(event) {
  const activation = readyActivation;
  readyActivation = null;
  // A double-click is one intent, even if its first request advances the round.
  if ((event?.detail || 0) > 1) return;
  // Pointer clicks must belong to a captured press. A detail=0 accessibility or
  // programmatic activation without a press intentionally targets the current
  // enabled button; it is not mistaken for an old-round physical gesture.
  if (!activation && ((event?.detail || 0) > 0 || readyHeldKey)) return;
  if (!composerAvailable() || busy.has("say") || state?.human_done) return;
  if (activation && (!activation.eligible || activation.turn_id !== state.turn_id)) {
    toast("The round changed during your click. Review this round before choosing Ready.", "warning");
    return;
  }
  const turn = activation?.turn_id ?? state.turn_id;
  const result = await act(
    "say",
    "/api/say",
    actionBody({ turn_id: turn, scope: "broadcast", recipient: [], content: "", skip: true }),
  );
  if (result) toast(state.turn_id === turn
    ? "You’re ready. Waiting for the remaining powers."
    : "Ready confirmed for the previous round. Review the new round before your next action.");
}

function openPrivate() {
  if (!state.human || busy.has("private")) return;
  captureCompose();
  $("recipient-options").innerHTML = POWERS.filter((p) => p !== state.human)
    .map(
      (p) =>
        `<label class="recipient-option"><input type="checkbox" name="recipient" value="${p}"><span class="power-dot" style="--power-color:${COLORS[p]}"></span>${titleCase(p)}</label>`,
    )
    .join("");
  $("private-form").querySelector(".form-error").textContent = "";
  openDialog("private-dialog");
  renderControls();
}
async function createPrivate(event) {
  event.preventDefault();
  if (busy.has("private")) return;
  const recipient = new FormData(event.currentTarget).getAll("recipient");
  if (!recipient.length) {
    event.currentTarget.querySelector(".form-error").textContent =
      "Choose at least one power for this private conversation.";
    return;
  }
  const generation = ++privateOpenGeneration,
    identity = composeIdentity;
  const result = await act(
    "private",
    "/api/open",
    { turn_id: state.turn_id, recipient },
    { refresh: false },
  );
  if (
    result?.channel &&
    composeIdentity === identity &&
    generation === privateOpenGeneration
  ) {
    openedChannels.add(result.channel);
    state.channels ||= {};
    state.channels[result.channel] ||= [];
    // Respect Cancel during a slow request: save the acknowledged channel but
    // do not move the user out of the conversation they chose to keep.
    if ($("private-dialog").open) {
      switchChannel(result.channel);
      $("private-dialog").close();
      selectTab("diplomacy");
      renderControls();
      $("message-input").focus();
    }
    persistCompose();
  }
  renderControls();
}
async function submitOrders() {
  if (!orderEditable()) return;
  const orders = Object.values(reconcileDraft(draft, state.legal));
  const quota =
    state.adjustment_count ?? adjustmentQuota(boardData, state.human);
  if (
    state.phase_type === "A" &&
    quota < 0 &&
    orders.length < Math.abs(quota) &&
    !confirm(
      `You selected ${orders.length} of ${Math.abs(quota)} required disbands. The engine will remove additional units automatically. Submit?`,
    )
  )
    return;
  if (
    state.phase_type === "R" &&
    orders.length < Object.keys(groupLegal(state.legal)).length &&
    !confirm(
      "Units without retreat orders will be disbanded. Submit these orders?",
    )
  )
    return;
  const result = await act("orders", "/api/orders", actionBody({ orders }));
  if (result) {
    toast(
      state?.order_submitted
        ? "Orders sealed. You’re ready for resolution."
        : "Orders accepted. The table is moving forward.",
    );
    startSound();
  }
}
async function cancelOrders() {
  const result = await act("cancel", "/api/orders/cancel", actionBody());
  if (result) toast("Orders withdrawn. Your draft is ready to edit.");
}
function openRoom() {
  renderRoom();
  openDialog("room-dialog");
}
function renderRoom() {
  if (!state) return;
  const s = state;
  $("room-modal-title").textContent = s.rname || "The European Accord";
  $("room-details").innerHTML =
    `<div class="room-detail-row"><span>Room code</span><strong>${esc(s.room || session.code)}</strong></div><div class="room-detail-row"><span>Rules</span><strong>${s.game_mode === "plus" ? "Plus · extension preview" : "Classic Diplomacy"}</strong></div><div class="room-detail-row"><span>Your seat</span><strong>${s.human ? titleCase(s.human) : "Observer"}</strong></div><div class="room-detail-row"><span>Players</span><strong>${s.seats?.length || 0} humans · ${7 - (s.seats?.length || 0)} AI</strong></div><div class="room-detail-row"><span>Status</span><strong>${titleCase(s.status)}</strong></div>${s.max_year ? `<div class="room-detail-row"><span>Year limit</span><strong>${s.max_year}</strong></div>` : ""}`;
  $("room-members").innerHTML = (s.seats || [])
    .map(
      (p) =>
        `<div class="room-member"><span class="power-dot" style="--power-color:${COLORS[p]}"></span><span><strong>${titleCase(p)}</strong><small><span data-no-translate>${esc(s.seat_names?.[p] || "Human player")}</span>${p === s.human ? " · you" : ""}</small></span>${s.owner && p !== s.human ? `<button class="text-button" data-transfer="${p}" ${s.settling ? "disabled" : ""}>Make host</button><button class="text-button danger" data-kick="${p}" ${s.settling ? "disabled" : ""}>Remove</button>` : ""}</div>`,
    )
    .join("");
  $("room-members")
    .querySelectorAll("[data-transfer]")
    .forEach(
      (b) =>
        (b.onclick = async () => {
          if (
            confirm(
              `Make ${titleCase(b.dataset.transfer)} the host? You will keep your power but lose host controls.`,
            )
          )
            await act("transfer", "/api/room/transfer", {
              power: b.dataset.transfer,
            });
        }),
    );
  $("room-members")
    .querySelectorAll("[data-kick]")
    .forEach(
      (b) =>
        (b.onclick = async () => {
          if (
            confirm(
              `Remove ${titleCase(b.dataset.kick)} from the table? Their seat token will be revoked and AI will take over their power.`,
            )
          )
            await act("kick", "/api/room/kick", { power: b.dataset.kick });
        }),
    );
  $("room-owner-actions").hidden = !s.owner;
  $("start-game").hidden = s.status !== "lobby";
  $("pause-game").hidden = !["playing", "paused"].includes(s.status);
  $("pause-game").textContent =
    s.status === "paused" ? "Resume game →" : "Pause game";
  $("save-game").disabled =
    s.status === "lobby" || s.settling || busy.has("save");
  $("show-saves").disabled = s.status === "lobby";
  $("end-game").hidden = s.status === "ended";
  $("timer-select").value = String(s.timer_on ? s.secs : 0);
  renderControls();
}
async function startGame() {
  const result = await act("start", "/api/room/start");
  if (result) {
    $("room-dialog").close();
    selectTab("diplomacy");
    toast("The game begins. The first round of diplomacy is open.");
  }
}
async function togglePause() {
  await act("pause", "/api/room/pause", {
    status: state.status === "paused" ? "playing" : "paused",
  });
  renderRoom();
}
async function saveGame() {
  const name = prompt(
    "Name this room’s checkpoint",
    `${state.phase}-${new Date().toISOString().slice(11, 16).replace(":", "")}`,
  );
  if (!name) return;
  try {
    await api(authPath(`/api/save?name=${encodeURIComponent(name)}`), {
      method: "POST",
    });
    toast("Checkpoint saved for this room.");
  } catch (error) {
    toast(errorMessage(error), "error");
  }
}
async function showSaves() {
  const el = $("saves-list");
  el.hidden = false;
  el.innerHTML = '<p class="pending-save">Loading room checkpoints…</p>';
  try {
    const data = await api(authPath("/api/saves"));
    el.innerHTML = data.saves?.length
      ? data.saves
          .map(
            (name) =>
              `<button data-save="${esc(typeof name === "string" ? name : name.name)}">↶ ${esc(typeof name === "string" ? name : name.name)}</button>`,
          )
          .join("")
      : '<p class="pending-save">No checkpoints yet. Save your current table first.</p>';
    el.querySelectorAll("[data-save]").forEach(
      (button) =>
        (button.onclick = async () => {
          if (
            !confirm(
              `Restore “${button.dataset.save}”? This replaces the current board and pauses the game for everyone.`,
            )
          )
            return;
          try {
            await api(
              authPath(
                `/api/load?name=${encodeURIComponent(button.dataset.save)}`,
              ),
              { method: "POST" },
            );
            draft = {};
            storage.remove(draftsKey());
            lastPhase = null;
            await refreshState();
            loadBoard(true);
            toast("Checkpoint restored. The table is paused for review.");
          } catch (error) {
            toast(errorMessage(error), "error");
          }
        }),
    );
  } catch (error) {
    el.textContent = errorMessage(error);
  }
}
async function endGame() {
  if (
    !confirm(
      "End this game for everyone at the table? Save a checkpoint first if you may want to return.",
    )
  )
    return;
  const result = await act("end", "/api/room/end");
  if (result) {
    $("room-dialog").close();
    toast("The host has closed this game.");
  }
}
async function invite() {
  const url = `${location.origin}/?join=${encodeURIComponent(session.code)}`;
  try {
    await navigator.clipboard.writeText(url);
    toast(`Invitation copied. Room ${session.code}`);
  } catch {
    prompt("Share this invitation link", url);
  }
}
function renderResult() {
  const s = state;
  let text = "The story of this table is still unfolding.",
    heading = "The final chapter.";
  if (s.end?.winner) {
    heading = `${titleCase(s.end.winner)} prevails.`;
    text = `${s.end.centers} supply centers. A solo victory.`;
  } else if (s.end?.draw) {
    heading = "A shared peace.";
    text = `Surviving powers: ${(s.end.survivors || []).map(titleCase).join(", ")}`;
  } else if (s.status === "ended") text = "The host has ended the game.";
  $("result-summary").innerHTML =
    s.end || s.status === "ended"
      ? `<div class="result-banner"><h3>${esc(heading)}</h3><p>${esc(text)}</p></div>`
      : "";
}
async function openHistory() {
  renderResult();
  openDialog("history-dialog");
  try {
    const data = await api(authPath("/api/chronicle"));
    $("history-content").textContent =
      data.text ||
      "The first chapter is yet to be written. Complete a movement phase to begin the chronicle.";
  } catch (error) {
    $("history-content").textContent = errorMessage(error);
  }
}
function updateViewMode(mode, available) {
  $("view-3d").classList.toggle("active", mode === "3d");
  $("view-2d").classList.toggle("active", mode === "2d");
  $("view-3d").setAttribute("aria-pressed", String(mode === "3d"));
  $("view-2d").setAttribute("aria-pressed", String(mode === "2d"));
  $("view-3d").disabled = !available;
  $("map-help").textContent =
    mode === "3d"
      ? "Drag to pan · Scroll to zoom · Right-drag to orbit"
      : "Click a unit · Choose a legal order";
}
async function loadProviders() {
  try {
    providerInfo = await api("/api/providers");
  } catch {
    providerInfo = { selected: "unknown", providers: [] };
  }
  renderProvider();
}
function renderProvider() {
  if (!providerInfo) return;
  const mock = providerInfo.selected === "mock";
  const selected = (providerInfo.providers || []).find(
    (p) => p.id === providerInfo.selected,
  );
  const label = mock
    ? "Offline demo AI"
    : providerInfo.selected === "unknown"
      ? "Provider status unavailable"
      : `${selected?.label || providerInfo.selected} · ${providerInfo.model || "configured"}`;
  for (const id of ["provider-status", "home-provider", "setup-provider"]) {
    const el = $(id);
    if (el) el.textContent = label;
  }
  $("provider-details").innerHTML =
    `<p><strong>${esc(label)}</strong></p><p>${mock ? "Deterministic heuristic opponents. No language-model inference." : "Configured provider · connection unverified"}</p><details><summary>Provider readiness</summary>${(providerInfo.providers || []).map((p) => `<div class="provider-row"><span>${esc(p.label)}</span><small>${esc(p.status)}</small></div>`).join("")}<p>Available does not mean authenticated or live-tested.</p></details>`;
}
function updateSoundButton() {
  const label =
    locale === "zh"
      ? sound
        ? "关闭回合提示音"
        : "开启回合提示音"
      : sound
        ? "Disable turn alerts"
        : "Enable turn alerts";
  $("sound-button").title = label;
  $("sound-button").setAttribute("aria-label", label);
  $("sound-button").setAttribute("aria-pressed", String(sound));
  $("sound-button").style.color = sound ? "#b58b44" : "";
}
function bind() {
  const options =
    POWERS.map(
      (p) =>
        `<option value="${p}" ${p === "FRANCE" ? "selected" : ""}>${titleCase(p)}</option>`,
    ).join("") + '<option value="">Observe the table</option>';
  $("create-power").innerHTML = options;
  $("join-power").innerHTML = options;
  $("new-game-button").onclick = () => setup("create");
  $("join-game-button").onclick = () => setup("join");
  $("refresh-rooms").onclick = listRooms;
  document
    .querySelectorAll("[data-setup]")
    .forEach((button) => (button.onclick = () => setup(button.dataset.setup)));
  $("create-form").onsubmit = (e) => submitSetup(e, "create");
  $("join-form").onsubmit = (e) => submitSetup(e, "join");
  $("join-code").oninput = (e) => updateJoinPowers(e.target.value);
  $("resume-button").onclick = enterTable;
  document
    .querySelectorAll("[data-close]")
    .forEach(
      (button) => (button.onclick = () => button.closest("dialog").close()),
    );
  document.querySelectorAll("dialog").forEach((dialog) =>
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) {
        const box = dialog.getBoundingClientRect();
        if (
          event.clientX < box.left ||
          event.clientX > box.right ||
          event.clientY < box.top ||
          event.clientY > box.bottom
        )
          dialog.close();
      }
    }),
  );
  $("help-button").onclick = () => openDialog("help-dialog");
  $("sound-button").onclick = () => {
    sound = !sound;
    updateSoundButton();
    startSound();
  };
  $("orders-tab").onclick = () => selectTab("orders");
  $("diplomacy-tab").onclick = () => selectTab("diplomacy");
  $("submit-orders").onclick = submitOrders;
  $("cancel-orders").onclick = cancelOrders;
  $("clear-orders").onclick = () => {
    draft = {};
    saveDraft();
    renderOrders();
  };
  $("message-form").onsubmit = sendMessage;
  $("message-input").addEventListener("input", () => {
    captureCompose();
    delete composeStatuses[composeBoundChannel];
    renderControls();
  });
  $("private-dialog").addEventListener("close", () => renderControls());
  window.addEventListener("pagehide", captureCompose);
  $("ready-negotiation").addEventListener("pointerdown", captureReadyInteraction);
  $("ready-negotiation").addEventListener("keydown", captureReadyInteraction);
  $("ready-negotiation").addEventListener("keyup", releaseReadyKey);
  $("ready-negotiation").addEventListener("pointercancel", cancelReadyInteraction);
  $("ready-negotiation").addEventListener("blur", cancelReadyInteraction);
  $("ready-negotiation").onclick = readyNegotiation;
  $("new-private-button").onclick = openPrivate;
  $("private-form").onsubmit = createPrivate;
  $("room-button").onclick = openRoom;
  $("chronicle-button").onclick = openHistory;
  $("home-button").onclick = goHome;
  $("table-tab").onclick = () =>
    window.scrollTo({ top: 0, behavior: "smooth" });
  $("invite-button").onclick = invite;
  $("start-game").onclick = startGame;
  $("pause-game").onclick = togglePause;
  $("save-game").onclick = saveGame;
  $("show-saves").onclick = showSaves;
  $("end-game").onclick = endGame;
  $("timer-select").onchange = (event) =>
    act("timer", "/api/room/secs", { secs: Number(event.target.value) });
  $("view-3d").onclick = () => board.setMode("3d");
  $("view-2d").onclick = () => board.setMode("2d");
  $("zoom-in").onclick = () => board.zoom(1.2);
  $("zoom-out").onclick = () => board.zoom(1 / 1.2);
  $("reset-view").onclick = () => {
    if (board.mode === "2d") {
      board.svgZoom = 1;
      board.build2D();
    } else board.reset();
  };
  $("brand-link")?.addEventListener("click", (e) => {
    e.preventDefault();
    goHome();
  });
  window.addEventListener("online", () => {
    if (activeView === "game") {
      refreshState().catch(() => {});
      connect();
    }
  });
  window.addEventListener("offline", () => {
    connected = false;
    updateConnection();
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && activeView === "game")
      refreshState().catch(() => {});
  });
  // Mobile retains the same owner and navigation actions without a hidden rail.
  $("room-label").style.cursor = "pointer";
  $("room-label").title = "Open room settings";
  $("room-label").tabIndex = 0;
  $("room-label").setAttribute("role", "button");
  $("room-label").onclick = openRoom;
  $("room-label").onkeydown = (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openRoom();
    }
  };
}
async function boot() {
  bind();
  initLocale(() => {
    updateSoundButton();
    lastOrderSignature = "";
    lastChatSignature = "";
    if (state) {
      renderState(state);
      renderRoom();
    }
    renderProvider();
  });
  document.querySelector('#create-form [name="lang"]').value =
    locale === "zh" ? "zh-Hans" : "en";
  updateSoundButton();
  loadProviders();
  const init = board.init();
  loadBoard(false);
  await listRooms();
  $("resume-session").hidden = !session.token;
  const join = new URLSearchParams(location.search).get("join");
  if (join) setup("join", join);
  else if (session.token) await enterTable();
  await init;
}
boot().catch((error) => {
  console.error(error);
  toast(
    "The table could not initialize. Refresh the page to try again.",
    "error",
  );
});
