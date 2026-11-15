#!/usr/bin/env node
// First-pass dead-time cut for every take, written to src/cuts.json.
// Keeps the stretches where someone (person or app) is speaking, from the word
// timings in transcripts/<take>.json. Hand-tune the result in src/edit.ts.
//
//   npm run cuts                       (all takes)
//   npm run cuts -- t3 --gap 1.5       (one take, looser)
//
//   --gap   pauses shorter than this stay in, seconds        (default 1.2)
//   --lead  time kept before the first word of a part        (default 0.35)
//   --tail  time kept after the last word of a part          (default 0.45)
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2);
const opt = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? Number(args[i + 1]) : fallback;
};
const gap = opt("gap", 1.2);
const lead = opt("lead", 0.35);
const tail = opt("tail", 0.45);
const named = args.filter((a, i) => !a.startsWith("--") && !args[i - 1]?.startsWith("--"));
const takes = named.length
  ? named
  : readdirSync(`${root}/transcripts`).filter((f) => f.endsWith(".json")).map((f) => f.slice(0, -5)).sort();

const sync = JSON.parse(readFileSync(`${root}/src/sync.json`, "utf8"));
const cutsPath = `${root}/src/cuts.json`;
const cuts = existsSync(cutsPath) ? JSON.parse(readFileSync(cutsPath, "utf8")) : {};
const round = (n) => Math.round(n * 100) / 100;

for (const take of takes) {
  const dur = sync[take]?.screen?.dur ?? Infinity;
  const words = JSON.parse(readFileSync(`${root}/transcripts/${take}.json`, "utf8"))
    .flatMap((s) => s.words.map((w) => ({ ...w, line: s.text })))
    // Whisper sometimes stretches a word back over the silence before it
    .map((w) => (w.end - w.start > 1.2 ? { ...w, start: w.end - 0.5 } : w));

  const parts = [];
  for (const w of words) {
    const last = parts.at(-1);
    if (last && w.start - last.end <= gap) {
      last.end = w.end;
      last.text += " " + w.w;
    } else {
      parts.push({ start: w.start, end: w.end, text: w.w });
    }
  }
  const segments = parts.map((p) => ({
    start: round(Math.max(0, p.start - lead)),
    end: round(Math.min(dur, p.end + tail)),
    say: p.text,
  }));
  // padding can make neighbours overlap
  for (let i = segments.length - 1; i > 0; i--) {
    if (segments[i].start <= segments[i - 1].end) {
      segments[i - 1].end = segments[i].end;
      segments[i - 1].say += " " + segments[i].say;
      segments.splice(i, 1);
    }
  }
  cuts[take] = segments;
  const kept = segments.reduce((n, s) => n + s.end - s.start, 0);
  console.log(`${take}: ${segments.length} parts, ${kept.toFixed(1)} s kept of ${dur} s`);
}
writeFileSync(cutsPath, JSON.stringify(cuts, null, 1) + "\n");
