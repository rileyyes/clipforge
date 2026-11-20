// Phase 22: panel layout, tool search, title gallery groups.
import { test } from "node:test";
import assert from "node:assert/strict";
import { columns, COLLAPSED, defaultLayout, fit, loadLayout, MAX_LEFT, MAX_RIGHT, MIN_LEFT, MIN_PREVIEW_H, MIN_PREVIEW_W, MIN_RIGHT, MIN_TL, NAV, saveLayout, TOP } from "./layout";
import { score, searchTools, TOOLS } from "./tools";
import { grouped } from "./gallery";
import { RETIRED_TEMPLATES, TITLE_TEMPLATES } from "./ops";

const mem = new Map<string, string>();
(globalThis as any).localStorage = { getItem: (k: string) => mem.get(k) ?? null, setItem: (k: string, v: string) => void mem.set(k, v), removeItem: (k: string) => void mem.delete(k) };

const previewW = (l: ReturnType<typeof fit>, w: number) => w - NAV - (l.mediaOpen ? l.left : COLLAPSED) - l.right;

test("layout: defaults match the old sizes", () => {
  assert.deepEqual(defaultLayout(1920, 1080), { left: 280, right: 290, timeline: 410, mediaOpen: true });
  assert.deepEqual(defaultLayout(1366, 768), { left: 220, right: 290, timeline: 292, mediaOpen: true });
  assert.deepEqual(defaultLayout(1280, 720), { left: 190, right: 280, timeline: 274, mediaOpen: true });
  assert.equal(columns(defaultLayout(1280, 720)), "190px minmax(0, 1fr) 280px");
  assert.equal(columns({ left: 300, right: 300, timeline: 200, mediaOpen: false }), `${COLLAPSED}px minmax(0, 1fr) 300px`);
});

test("layout: always fits the window, preview first", () => {
  for (const [w, h] of [[1280, 720], [1024, 640], [1920, 1080], [800, 500], [2560, 1440]]) {
    for (const want of [{ left: 9999, right: 9999, timeline: 9999 }, { left: -5, right: 0, timeline: -1 }, { left: NaN, right: NaN, timeline: NaN }]) {
      for (const mediaOpen of [true, false]) {
        const l = fit({ ...want, mediaOpen }, w, h);
        assert.ok(l.left >= MIN_LEFT && l.left <= MAX_LEFT && l.right >= MIN_RIGHT && l.right <= MAX_RIGHT, JSON.stringify(l));
        assert.ok(l.timeline >= MIN_TL);
        if (w - NAV - MIN_LEFT - MIN_RIGHT >= MIN_PREVIEW_W) assert.ok(previewW(l, w) >= MIN_PREVIEW_W - 1, `${w}: ${JSON.stringify(l)}`);
        if (h - TOP - 6 - MIN_TL >= MIN_PREVIEW_H) assert.ok(h - TOP - 6 - l.timeline >= MIN_PREVIEW_H - 1, `${h}: ${l.timeline}`);
      }
    }
  }
  // a big tool panel squeezes the media bin before itself
  const l = fit({ left: 400, right: 600, timeline: 300, mediaOpen: true }, 1280, 720);
  assert.equal(l.right, 600); assert.equal(l.left, 1280 - NAV - MIN_PREVIEW_W - 600);
});

test("layout: kept between sessions, and broken data is ignored", () => {
  mem.clear();
  assert.deepEqual(loadLayout(1920, 1080), defaultLayout(1920, 1080));
  saveLayout({ left: 333, right: 444, timeline: 300, mediaOpen: false });
  assert.deepEqual(loadLayout(1920, 1080), { left: 333, right: 444, timeline: 300, mediaOpen: false });
  mem.set("cf:layout", "{nope");
  assert.deepEqual(loadLayout(1920, 1080), defaultLayout(1920, 1080));
  mem.set("cf:layout", JSON.stringify({ left: "wide", right: 300, evil: 1 }));
  assert.deepEqual(loadLayout(1920, 1080), { ...defaultLayout(1920, 1080), right: 300 });
});

test("tool search finds tools by name and by other words", () => {
  const first = (q: string) => searchTools(q)[0]?.name;
  assert.equal(first("mixer"), "Sound mixer");
  assert.equal(first("blur"), "Blur / hide something");
  assert.equal(first("subtitles"), "Captions");
  assert.equal(first("multi cam"), "Multicam (switch cameras)");
  assert.equal(first("chart"), "Add a title, chart or shape");
  assert.equal(first("green screen"), "Green screen");
  assert.equal(first("white balance"), "Auto colour fix / match cameras");
  assert.equal(first("dark mode"), "Light / dark theme");
  assert.equal(first("exp"), "Export");
  assert.deepEqual(searchTools("zzzz"), []);
  assert.ok(searchTools("").length > 0);
  assert.equal(score(TOOLS[0], "   "), 0);
  // every word has to match something
  assert.ok(!searchTools("mixer zebra").length);
  // every tool says where it is and how to reach it
  for (const t of TOOLS) assert.ok(t.action || t.tab, t.name);
  assert.equal(new Set(TOOLS.map((t) => t.name)).size, TOOLS.length);
});

test("title gallery: every offered template is in exactly one group", () => {
  const offered = TITLE_TEMPLATES.filter(([t]) => !RETIRED_TEMPLATES.includes(t));
  const g = grouped();
  const all = g.flatMap(([, items]) => items);
  assert.equal(all.length, offered.length);
  assert.equal(new Set(all).size, all.length);
  assert.ok(!all.some(([t]) => RETIRED_TEMPLATES.includes(t)));
  assert.deepEqual(g.map(([n]) => n), ["Titles", "Arrows & shapes", "Motion graphics", "YouTube"]);    // nothing left in "More"
});
