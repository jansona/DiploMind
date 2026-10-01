import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { translate } from "../diplomind/static/i18n.js";

// Execute the actual app event handlers with a controlled SSE state/HTTP boundary.
// This avoids importing WebGL/boot and never talks to a provider or network.
const source = readFileSync(new URL("../diplomind/static/app.js", import.meta.url), "utf8");
const start = source.indexOf("function captureReadyInteraction(");
const end = source.indexOf("\nfunction openPrivate()", start);
assert.ok(start >= 0 && end > start);
const handlers = source.slice(start, end);
function harness() {
  const sent = [], notices = [];
  let request = 0;
  const ctx = vm.createContext({
    state: { turn_id: "round-1", your_turn: true, human_done: false },
    busy: new Set(), readyActivation: null, readyHeldKey: null,
    composerAvailable: () => Boolean(ctx.state?.your_turn),
    actionBody: (extra) => ({ turn_id: ctx.state.turn_id, request_id: `request-${++request}`, ...extra }),
    act: async (key, path, body) => { sent.push({ key, path, body }); return { ok: true }; },
    toast: (...args) => notices.push(args),
  });
  vm.runInContext(handlers, ctx);
  return { ctx, sent, notices, advance: () => { ctx.state = { turn_id: "round-2", your_turn: true, human_done: false }; } };
}
function pointer(ctx) { ctx.captureReadyInteraction({ type: "pointerdown", button: 0 }); }
function key(ctx, value, repeat = false) {
  const event = { type: "keydown", key: value, repeat, prevented: false, preventDefault() { this.prevented = true; } };
  ctx.captureReadyInteraction(event); return event;
}

test("pointer press started before third-message auto-ready cannot consume next round", async () => {
  const { ctx, sent, notices, advance } = harness();
  pointer(ctx);
  advance(); // third-message response or SSE advanced while the button was pressed
  await ctx.readyNegotiation({ detail: 1 });
  assert.equal(sent.length, 0);
  assert.match(notices[0][0], /round changed/);
});

test("double-click is one intent even when first Ready immediately advances", async () => {
  const { ctx, sent, advance } = harness();
  pointer(ctx); await ctx.readyNegotiation({ detail: 1 });
  advance();
  pointer(ctx); await ctx.readyNegotiation({ detail: 2 });
  assert.equal(sent.length, 1);
  assert.equal(sent[0].body.turn_id, "round-1");
});

test("deliberately waiting for new enabled button then fresh click may ready the next round", async () => {
  const { ctx, sent, advance } = harness();
  pointer(ctx); await ctx.readyNegotiation({ detail: 1 });
  advance();
  pointer(ctx); await ctx.readyNegotiation({ detail: 1 });
  assert.deepEqual(sent.map((r) => r.body.turn_id), ["round-1", "round-2"]);
  assert.notEqual(sent[0].body.request_id, sent[1].body.request_id);
});

test("Space captures its turn on keydown, through keyup and an intervening SSE", async () => {
  const { ctx, sent, advance } = harness();
  key(ctx, " "); advance();
  ctx.releaseReadyKey({ key: " " });
  await ctx.readyNegotiation({ detail: 0 });
  assert.equal(sent.length, 0);
});

test("held Enter/repeat cannot finish another round", async () => {
  const { ctx, sent, advance } = harness();
  key(ctx, "Enter"); await ctx.readyNegotiation({ detail: 0 });
  advance();
  assert.equal(key(ctx, "Enter", true).prevented, true);
  await ctx.readyNegotiation({ detail: 0 });
  assert.equal(sent.length, 1);
  ctx.releaseReadyKey({ key: "Enter" });
  key(ctx, "Enter"); await ctx.readyNegotiation({ detail: 0 });
  assert.equal(sent.length, 2);
});

test("press during pending send stays ineligible after acknowledgement re-enables Ready", async () => {
  const { ctx, sent, advance } = harness();
  ctx.busy.add("say"); pointer(ctx);
  advance(); ctx.busy.delete("say");
  await ctx.readyNegotiation({ detail: 1 });
  assert.equal(sent.length, 0);
});

test("pending sends and already-ready snapshots reject direct activation too", async () => {
  const { ctx, sent } = harness();
  ctx.busy.add("say"); await ctx.readyNegotiation({ detail: 0 });
  ctx.busy.delete("say"); ctx.state.human_done = true;
  await ctx.readyNegotiation({ detail: 0 });
  assert.equal(sent.length, 0);
  assert.match(source, /\$\("ready-negotiation"\)\.disabled = !available \|\| sendBusy \|\| Boolean\(state\.human_done\)/);
});

test("accessibility/programmatic activation without physical press targets current enabled round", async () => {
  const { ctx, sent, advance } = harness();
  advance(); await ctx.readyNegotiation({ detail: 0 });
  assert.equal(sent.length, 1);
  assert.equal(sent[0].body.turn_id, "round-2");
});

test("cancelled pointer gesture cannot be revived by a stale pointer click", async () => {
  const { ctx, sent, advance } = harness();
  pointer(ctx); ctx.cancelReadyInteraction(); advance();
  await ctx.readyNegotiation({ detail: 1 });
  assert.equal(sent.length, 0);
});

test("actual binding captures pointer and keyboard interaction before click", () => {
  for (const [event, handler] of [["pointerdown", "captureReadyInteraction"], ["keydown", "captureReadyInteraction"], ["keyup", "releaseReadyKey"], ["pointercancel", "cancelReadyInteraction"]]) {
    assert.ok(source.includes(`$("ready-negotiation").addEventListener("${event}", ${handler})`));
  }
});

test("help and translations explain automatic readiness after third message", () => {
  assert.match(readFileSync(new URL("../README.md", import.meta.url), "utf8"), /third message automatically marks you ready/);
  assert.match(readFileSync(new URL("../README.zh-CN.md", import.meta.url), "utf8"), /第三条会自动就绪/);
  const html = readFileSync(new URL("../diplomind/ui.html", import.meta.url), "utf8").replace(/\s+/g, " ");
  const help = "Talk publicly or in a private channel. Stage up to three messages per round. The third message automatically readies you; press Ready earlier to finish with fewer messages. Everyone’s messages arrive together. Promises are never binding.";
  assert.ok(html.includes(help));
  assert.match(translate(help), /第三条会自动就绪/);
  assert.match(translate("Your third message was accepted. You’re automatically ready for that round."), /无需再点/);
});

test("third-message acknowledgement stays anchored to sent round after auto-advance", async () => {
  const sendStart = source.indexOf("async function sendMessage(");
  const sendEnd = source.indexOf("\nfunction captureReadyInteraction(", sendStart);
  const notices = [];
  const input = { value: "proposal" };
  const ctx = vm.createContext({
    state: { turn_id: "round-1", msgs_left: 1 }, busy: new Set(),
    composeIdentity: "same-seat", composeBoundChannel: "group",
    composeDrafts: { group: "proposal" }, composePending: {},
    composerAvailable: () => true, captureCompose: () => {},
    channelInfo: () => ({ public: true, recipients: [] }),
    crypto: { randomUUID: () => "request-1" },
    persistCompose: () => {}, setComposeStatus: () => {}, renderControls: () => {},
    $: () => input, toast: (message) => notices.push(message),
    act: async () => { ctx.state = { turn_id: "round-2", msgs_left: 3 }; return { ok: true }; },
  });
  vm.runInContext(source.slice(sendStart, sendEnd), ctx);
  await ctx.sendMessage({ preventDefault() {} });
  assert.deepEqual(notices, ["Your third message was accepted. You’re automatically ready for that round."]);
});

test("acknowledgement after immediate round advance does not say current round is ready", async () => {
  const { ctx, notices, advance } = harness();
  ctx.act = async () => { advance(); return { ok: true }; };
  pointer(ctx); await ctx.readyNegotiation({ detail: 1 });
  assert.match(notices[0][0], /previous round/);
});
