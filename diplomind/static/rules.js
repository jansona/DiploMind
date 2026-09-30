/** Pure UI rules. The server/engine remains the sole rules authority. */
export const POWERS = [
  "AUSTRIA",
  "ENGLAND",
  "FRANCE",
  "GERMANY",
  "ITALY",
  "RUSSIA",
  "TURKEY",
];
export const COLORS = {
  AUSTRIA: "#c45757",
  ENGLAND: "#7475a6",
  FRANCE: "#568dac",
  GERMANY: "#7c898c",
  ITALY: "#6b9c7c",
  RUSSIA: "#ad8eb1",
  TURKEY: "#c6a455",
};
export const titleCase = (value) =>
  String(value || "")
    .toLowerCase()
    .replace(/\b\w/g, (x) => x.toUpperCase());
export const escapeHTML = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
export const provinceKey = (location) =>
  String(location || "")
    .toUpperCase()
    .split("/")[0];
export function orderKey(order) {
  const parts = String(order).trim().split(/\s+/);
  return parts[0] === "WAIVE" ? "WAIVE" : provinceKey(parts[1]);
}
export function orderAction(order) {
  return order === "WAIVE" ? "W" : order.split(/\s+/)[2] || "H";
}
export const ACTIONS = {
  H: "Hold position",
  "-": "Move",
  S: "Support",
  C: "Convoy",
  R: "Retreat",
  B: "Build",
  D: "Disband",
  W: "Waive build",
};
export function groupLegal(legal = []) {
  const groups = {};
  for (const order of legal) {
    const key = orderKey(order);
    if (key === "WAIVE") continue;
    (groups[key] ||= []).push(order);
  }
  return groups;
}
export function reconcileDraft(draft = {}, legal = []) {
  const allowed = new Set(legal);
  return Object.fromEntries(
    Object.values(draft)
      .filter((o) => allowed.has(o))
      .map((o) => [orderKey(o), o]),
  );
}
export function humanOrder(order, names = {}) {
  if (!order) return "No order drafted";
  if (order === "WAIVE") return "Waive a build";
  const p = order.split(/\s+/),
    loc = (v) => names[provinceKey(v)] || v;
  const unit = (t, l) => `${t === "A" ? "Army" : "Fleet"} · ${loc(l)}`;
  if (p[2] === "H") return "Hold position";
  if (p[2] === "-")
    return `Move → ${loc(p[3])}${p[4] === "VIA" ? " (via convoy)" : ""}`;
  if (p[2] === "R") return `Retreat → ${loc(p[3])}`;
  if (p[2] === "D") return `Disband ${p[0] === "A" ? "army" : "fleet"}`;
  if (p[2] === "B")
    return `Build ${p[0] === "A" ? "army" : "fleet"}${p[1].includes("/") ? " · " + p[1].split("/")[1] + " coast" : ""}`;
  if (p[2] === "S")
    return `Support ${unit(p[3], p[4])}${p[5] === "-" ? " → " + loc(p[6]) : " hold"}`;
  if (p[2] === "C") return `Convoy ${unit(p[3], p[4])} → ${loc(p[6])}`;
  return order;
}
export function phaseLabel(phase) {
  if (!phase || phase === "-") return "The table is gathering";
  if (phase === "COMPLETED") return "History has been made";
  const season = { S: "Spring", F: "Autumn", W: "Winter" }[phase[0]] || "";
  const year = phase.match(/\d+/)?.[0] || "";
  return `${season} ${year}`.trim();
}
export function adjustmentQuota(board, power) {
  if (!board || !power) return 0;
  return (
    (board.centers?.[power]?.length || 0) -
    (board.units || []).filter((u) => u.power === power && !u.dislodged).length
  );
}
export function actionTargets(order) {
  const p = order.split(/\s+/);
  if (p[2] === "-" || p[2] === "R") return [provinceKey(p[3])];
  if (p[2] === "S" || p[2] === "C")
    return [provinceKey(p[4]), ...(p[6] ? [provinceKey(p[6])] : [])];
  return [];
}
