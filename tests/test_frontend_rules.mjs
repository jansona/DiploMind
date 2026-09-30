import test from "node:test";
import assert from "node:assert/strict";
import {
  groupLegal,
  reconcileDraft,
  orderKey,
  orderAction,
  humanOrder,
  phaseLabel,
  adjustmentQuota,
  actionTargets,
  escapeHTML,
} from "../diplomind/static/rules.js";

test("legal orders group one unit or coast-adjustment site, never one checkbox per order", () => {
  const groups = groupLegal([
    "A PAR H",
    "A PAR - BUR",
    "A PAR S A MAR - BUR",
    "F BRE H",
    "A STP B",
    "F STP/NC B",
    "F STP/SC B",
    "WAIVE",
  ]);
  assert.deepEqual(Object.keys(groups), ["PAR", "BRE", "STP"]);
  assert.equal(groups.PAR.length, 3);
  assert.equal(groups.STP.length, 3);
});
test("draft reconciliation discards stale and illegal choices, and only one order survives per province", () => {
  assert.deepEqual(
    reconcileDraft({ PAR: "A PAR - BUR", BRE: "F BRE - ENG", X: "A PAR H" }, [
      "A PAR H",
      "A PAR - BUR",
    ]),
    { PAR: "A PAR H" },
  );
  assert.deepEqual(
    reconcileDraft({ A: "F STP/NC B", B: "A STP B" }, [
      "F STP/NC B",
      "A STP B",
    ]),
    { STP: "A STP B" },
  );
});
test("all phase order types have usable identities and labels", () => {
  assert.equal(orderKey("F STP/NC R BAR"), "STP");
  assert.equal(orderAction("WAIVE"), "W");
  assert.equal(
    humanOrder("A PAR - BUR", { BUR: "Burgundy" }),
    "Move → Burgundy",
  );
  assert.equal(humanOrder("F STP/SC B"), "Build fleet · SC coast");
  assert.equal(
    humanOrder("A PAR S A MAR - BUR", { MAR: "Marseilles", BUR: "Burgundy" }),
    "Support Army · Marseilles → Burgundy",
  );
  assert.equal(humanOrder("F ENG C A LON - BEL"), "Convoy Army · LON → BEL");
  assert.equal(humanOrder("A MUN R BOH"), "Retreat → BOH");
  assert.equal(humanOrder("A PAR D"), "Disband army");
});
test("map clicks use legal targets rather than inventing adjacencies", () => {
  assert.deepEqual(actionTargets("A PAR - BUR"), ["BUR"]);
  assert.deepEqual(actionTargets("F ENG S F BRE - MAO"), ["BRE", "MAO"]);
  assert.deepEqual(actionTargets("F NWG R STP/NC"), ["STP"]);
  assert.deepEqual(actionTargets("A PAR H"), []);
});
test("adjustment quota counts owned centers against standing units", () => {
  const board = {
    centers: { FRANCE: ["PAR", "BRE", "MAR"] },
    units: [
      { power: "FRANCE" },
      { power: "FRANCE" },
      { power: "FRANCE", dislodged: true },
      { power: "ITALY" },
    ],
  };
  assert.equal(adjustmentQuota(board, "FRANCE"), 1);
  assert.equal(adjustmentQuota(null, "FRANCE"), 0);
});
test("phase labels cover all seasons and completed games", () => {
  assert.equal(phaseLabel("S1901M"), "Spring 1901");
  assert.equal(phaseLabel("F1902R"), "Autumn 1902");
  assert.equal(phaseLabel("W1903A"), "Winter 1903");
  assert.equal(phaseLabel("-"), "The table is gathering");
  assert.equal(phaseLabel("COMPLETED"), "History has been made");
});
test("player-controlled strings are escaped at HTML boundaries", () => {
  assert.equal(
    escapeHTML("<img onerror=\"x\"> & 'test'"),
    "&lt;img onerror=&quot;x&quot;&gt; &amp; &#39;test&#39;",
  );
});

const { translate } = await import("../diplomind/static/i18n.js");
test("Chinese shell translates core actions without changing order syntax", () => {
  assert.equal(translate("Submit 3 orders"), "提交 3 道命令");
  assert.equal(translate("Spring 1901"), "1901 年春季");
  assert.equal(translate("Offline demo AI"), "离线演示 AI");
  assert.equal(
    translate("Move → 勃艮第 · A PAR - BUR"),
    "移动 → 勃艮第 · A PAR - BUR",
  );
  assert.equal(translate("A PAR S A MAR - BUR"), "A PAR S A MAR - BUR");
});
