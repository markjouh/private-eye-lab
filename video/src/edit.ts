import cuts from "./cuts.json";
import sync from "./sync.json";

// The whole edit lives here. Times are seconds in a take's SCREEN recording,
// because its audio track (app audio + mic) is the one we keep.
// A segment may start before 0:00 (negative time): that stretch plays the outside
// camera's own audio, with the phone screen held on its first frame.

// "both": landscape camera full-frame with the phone over its right side (portrait camera: side by side)
// "split": camera and phone side by side, nothing covered (for when the action is on the right)
export type Layout = "both" | "split" | "outside" | "screen";

export type Segment = {
  take: TakeId;
  start: number; // seconds into that take's screen recording
  end: number;
  layout?: Layout; // default "both"; falls back to "screen" where the camera wasn't rolling
  audio?: "screen" | "outside"; // default "screen"; "outside" = the camera's own microphone
  gainDb?: number; // boost for camera-microphone sound, which is recorded ~20 dB quieter
  say?: string; // what is said, for reference only
  title?: string; // label shown top-left for as long as consecutive segments share it
  sub?: string; // smaller second line of the label
};

// Stamp one on-screen title onto a run of segments.
const scene = (title: string, sub: string, segments: Segment[]): Segment[] =>
  segments.map((s) => ({ ...s, title, sub }));

export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;

export type TakeId = keyof typeof sync;
export const takeIds = Object.keys(sync) as TakeId[];

// Per take: files in public/raw (made by `npm run ingest`), and where the outside
// camera is when the screen recording is at 0:00 (from `npm run sync`, audio-matched).
// To nudge a take's sync by hand, add to its number here, e.g. { t2: 0.05 }.
const nudge: Partial<Record<TakeId, number>> = {};

export const take = (id: TakeId) => ({
  screen: `raw/${id}-screen.mp4`,
  outside: `raw/${id}-outside.mp4`,
  poster: `raw/${id}-outside-poster.jpg`,
  offset: sync[id].offset + (nudge[id] ?? 0),
  // a take with no camera clip (the intro) has outside: null and always shows the screen alone
  outsideDur: sync[id].outside?.dur ?? 0,
  screenDur: sync[id].screen.dur,
  outsidePortrait: (sync[id].outside?.h ?? 0) > (sync[id].outside?.w ?? 0),
});

// First-pass cut of one take: the spoken parts, from `npm run cuts`.
export const autoCut = (id: TakeId): Segment[] =>
  // a take that `npm run cuts` hasn't seen yet simply has no first-pass cut
  ((cuts as Record<string, { start: number; end: number; say?: string }[]>)[id] ?? []).map((s) => ({
    take: id,
    ...s,
  }));

// Budget: the finished video must be under 3:00 (LIMIT_SEC), talking heads included.
export const LIMIT_SEC = 180;

// THE EDIT, in playing order. Loose on purpose: pauses up to ~3 s stay in, the wait between
// a prompt and the app's reply is never cut, and each scene keeps the talk leading into it.
export const demo: Segment[] = [
  // Intro (the longer second recording). Only the pauses between sentences and the dead tail are trimmed.
  ...scene("Private Eye", "Runs entirely on the phone, in airplane mode", [
    { take: "intro2", start: 0, end: 3.2, say: "This is Private Eye, a multimodal vision assistant for blind people." },
    { take: "intro2", start: 3.9, end: 9.8, say: "Everything is run completely on device. To demonstrate this, I'll turn on airplane mode for all our demos today." },
    { take: "intro2", start: 10.4, end: 18.9, say: "It's easy to use. Just open the app, tap, and you're ready to go. Laptop computer." },
  ]),

  // Whiteboard: a beat of pointing the phone, the question, the reply
  ...scene("Read text", "Reads what's written, out loud", [
    { take: "t5", start: 10.3, end: 15.9, say: "What does this say? Please clean up after yourself." },
  ]),

  // Water bottle, the search included
  ...scene("Find your things", "Guides you to things it remembers", [
    { take: "t6", start: 0, end: 14.7, layout: "split", say: "I need to find where my water bottle is. Find my water bottle. Looking for your water bottle. ... Your water bottle is two feet to your left." },
  ]),

  // Remember Elias. Opens on the camera's audio: the chat before the screen recording began.
  ...scene("Remember a face", "Say \u201cThis is Elias\u201d once", [
    { take: "t4", start: -3.0, end: 1.5, audio: "outside", gainDb: 19, say: "So, how's the hackathon going for you? It's been awesome, a ton of fun making Private Eye." },
    { take: "t4", start: 1.5, end: 12.6, say: "Great. Do you mind if I save your face to Private Eye? Sure, go ahead. This is Elias. Remember Elias. Awesome, thanks." },
  ]),

  // Look for Elias (the "what do you see" opener is dropped; the search wait stays)
  ...scene("Find a person", "Tells you where they are", [
    { take: "t2", start: 10.6, end: 22.6, say: "So, can you help me look for Elias? Looking for Elias. ... Elias, 11 feet, right. Yo, Elias." },
  ]),

  // Mascot (split layout so the phone doesn't cover the pillow)
  ...scene("Ask what something is", "It knows the Wisconsin Badgers", [
    { take: "t7", start: 4.75, end: 8.2, layout: "split", say: "What mascot is this? Wisconsin Badgers." },
  ]),

  // Donut scene, last, so the video ends on "let's dig in".
  // Opens before the screen recording began, on the camera's audio.
  ...scene("Ask where things are", "Distance and direction, spoken", [
    { take: "t3", start: -2.03, end: 3.6, gainDb: 24, say: "Do you see the table? How far away is this? Yes, just ahead, beside the nearest chair." },
  ]),
  ...scene("Describe the scene", "Nearest things first", [
    { take: "t3", start: 7.4, end: 14.4, say: "Okay, what do you see? Two plates of bagels and muffins, metal bottle, and people at tables." },
  ]),
  ...scene("Ask about food", "Check for allergens before you eat", [
    { take: "t3", start: 17.3, end: 33.6, say: "I'm allergic to poppy seeds. Does this bagel have any seeds? Yes, poppy seeds. Alright, off with that. What about this? What kind of bagel is this? Plain bagel. Great." },
    // starts after the stray "Hmm" and pause (34.9-38.2), trimmed to fit the 3:00 limit
    { take: "t3", start: 38.2, end: 48.6, say: "I'm also allergic to chocolate. Is this a chocolate donut hole? ... No eating that." },
    // dropped: 50.2-57.4 the first "what kind of donut hole is this? Glazed donut hole" (asked again below)
    // dropped: 59.7-68.3 "is this my water bottle? ... all right" (the water bottle has its own scene)
  ]),
];

// The last clip, played after "How we built Witness-2B": the re-check, "let's dig in", the bite.
export const finale: Segment[] = [
  { take: "t3", start: 73.5, end: 85.4, say: "Again, just make sure this isn't a chocolate donut hole, right? ... Glazed donut hole. Alright, well, let's dig in." },
];

// The ending: big words that pop in as they are spoken (times in that take's screen
// recording), the scene title steps aside for them, then picture and sound fade to black.
export const outro = {
  cues: [
    { word: "LET\u2019S", take: "t3" as TakeId, at: 82.4 },
    { word: "DIG", take: "t3" as TakeId, at: 82.78 },
    { word: "IN.", take: "t3" as TakeId, at: 82.98 },
  ],
  fadeSec: 0.9,
};

// What actually plays: each segment split wherever the camera or the screen recording
// starts or stops, so every piece has one layout and one audio source throughout.
export type Piece = {
  take: TakeId;
  start: number;
  end: number;
  layout: Layout;
  audio: "screen" | "outside";
  gainDb: number; // applied only while the camera microphone is the sound source
  title?: string;
  sub?: string;
  // hold this picture on its first frame (it hasn't started recording yet)
  freeze?: "screen" | "outside";
};

export const resolve = (segments: Segment[]): Piece[] =>
  segments.flatMap((s) => {
    const t = take(s.take);
    const hasCamera = t.outsideDur > 0;
    const covFrom = -t.offset; // screen time at which the outside clip begins
    const covTo = t.outsideDur - t.offset - 0.1;
    const wanted: Layout = hasCamera ? (s.layout ?? "both") : "screen";
    const marks = [s.start, 0, hasCamera ? covFrom : s.start, hasCamera ? covTo : s.start, s.end]
      .filter((m) => m >= s.start && m <= s.end)
      .sort((a, b) => a - b);
    const out: Piece[] = [];
    for (let i = 0; i < marks.length - 1; i++) {
      const [a, b] = [marks[i], marks[i + 1]];
      if (b - a < 1 / FPS) continue;
      const base = { take: s.take, start: a, end: b, gainDb: s.gainDb ?? 0, title: s.title, sub: s.sub };
      const screenOn = a >= -1e-6;
      const cameraOn = hasCamera && a >= covFrom - 1e-6 && b <= covTo + 1e-6;
      if (screenOn && cameraOn) {
        out.push({ ...base, layout: wanted, audio: s.audio ?? "screen" });
      } else if (screenOn) {
        // camera not rolling: if it starts within half a second, hold its first frame
        // rather than flashing to a different layout; otherwise show the screen alone
        const aboutToStart = hasCamera && wanted !== "screen" && Math.abs(b - covFrom) < 1e-6 && b - a < 0.5;
        out.push(
          aboutToStart
            ? { ...base, layout: wanted, audio: "screen", freeze: "outside" }
            : { ...base, layout: "screen", audio: "screen" },
        );
      } else if (cameraOn) {
        // Before the screen recording: camera sound. A landscape camera shows alone and the
        // phone screen appears when its recording starts; beside a portrait camera the phone
        // is held on its first frame instead, so the picture doesn't jump sideways.
        out.push(
          t.outsidePortrait && wanted === "both"
            ? { ...base, layout: "both", audio: "outside", freeze: "screen" }
            : { ...base, layout: "outside", audio: "outside" },
        );
      }
    }
    return out;
  });

export const segmentFrames = (s: { start: number; end: number }) =>
  Math.max(1, Math.round((s.end - s.start) * FPS));

export const totalFrames = (segments: Segment[]) =>
  Math.max(1, resolve(segments).reduce((n, s) => n + segmentFrames(s), 0));
