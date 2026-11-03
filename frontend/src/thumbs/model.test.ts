import { test } from "node:test";
import assert from "node:assert/strict";
import {
  addLayer, duplicateLayer, fitTextBox, hitTest, makeImage, makeShape, makeText, moveLayerOrder, removeLayer, updateLayer,
  type Design,
} from "./model";

const blank = (): Design => ({ id: "f".repeat(32), name: "T", width: 1280, height: 720, background: "#000000", layers: [],
  concept: null, generations: [], edit_revision: 0, timeline_fingerprint: "", timeline_coverage: [], created_at: "", updated_at: "" });
const ok = (r: any): Design => { assert.equal(r.error, undefined, r.error); return r.design; };

test("add / duplicate / reorder / remove layers", () => {
  let d = ok(addLayer(blank(), makeImage("a".repeat(32), "bg")));
  const t = makeText("HI");
  d = ok(addLayer(d, t));
  d = ok(duplicateLayer(d, t.id));
  assert.equal(d.layers.length, 3);
  assert.notEqual(d.layers[2].id, t.id);
  assert.equal(d.layers[2].x, t.x + 24);
  d = ok(moveLayerOrder(d, d.layers[2].id, -1));
  assert.equal(d.layers[1].name, "Text copy");
  d = ok(removeLayer(d, t.id));
  assert.equal(d.layers.length, 2);
});

test("locked layers can't be edited or removed, but can be unlocked", () => {
  const t = { ...makeText(), locked: true };
  const d = ok(addLayer(blank(), t));
  assert.ok(updateLayer(d, t.id, { x: 5 }).error);
  assert.ok(removeLayer(d, t.id).error);
  assert.equal(ok(updateLayer(d, t.id, { locked: false })).layers[0].locked, false);
});

test("hit testing picks the top visible layer and honours rotation", () => {
  const img = makeImage("a".repeat(32), "bg");
  const s = { ...makeShape("rect"), x: 100, y: 100, w: 200, h: 40, rotation: 90 };
  let d = ok(addLayer(ok(addLayer(blank(), img)), s));
  // rotated 90°: the 200x40 box now spans vertically around its centre (200,120)
  assert.equal(hitTest(d, 200, 200)?.id, s.id);
  assert.equal(hitTest(d, 290, 120)?.id, img.id);
  d = ok(updateLayer(d, s.id, { hidden: true }));
  assert.equal(hitTest(d, 200, 200)?.id, img.id);
  const scrim = { ...makeShape("rect"), role: "scrim" as const, x: 0, y: 0, w: 1280, h: 720 };
  assert.equal(hitTest(ok(addLayer(d, scrim)), 640, 360)?.id, img.id, "scrims are not clickable");
});

test("text boxes grow with content and stay positive", () => {
  const a = fitTextBox({ ...makeText("HI"), font_size: 100 });
  const b = fitTextBox({ ...makeText("A MUCH LONGER HEADLINE"), font_size: 100 });
  const c = fitTextBox({ ...makeText("TWO\nLINES"), font_size: 100 });
  assert.ok(b.w > a.w && c.h > a.h && a.w > 0);
  assert.ok(updateLayer(ok(addLayer(blank(), a)), a.id, { w: 0 }).error);
});

test("layer limit enforced", () => {
  let d = blank();
  for (let i = 0; i < 60; i++) d = ok(addLayer(d, makeShape("rect")));
  assert.ok(addLayer(d, makeShape("rect")).error);
});
