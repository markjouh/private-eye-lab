import React from "react";
import { Audio } from "@remotion/media";
import { AbsoluteFill, Easing, Img, interpolate, spring, staticFile, useCurrentFrame } from "remotion";
import { FPS } from "./edit";

// "How we built Witness-2B": full-frame graphics over the voice memo (no talking head).
// Every `at` below is a time in seconds in the voice memo (public/raw/vo-built.m4a), taken
// from its word timings in transcripts/vo-built.json, so graphics land on the spoken word.
// Rule from the brief: no number on screen that isn't in the brief, and never "trained on Databricks".

export const BUILT = { from: 1.0, to: 58.0 }; // the part of the memo that plays
export const builtFrames = Math.round((BUILT.to - BUILT.from) * FPS);

const C = {
  black: "#000000",
  yellow: "#ffd600",
  text: "#f5f3ea",
  quiet: "#b3b1a6",
  panel: "#1a1a1a",
  red: "#ff5d5d",
  brick: "#ff3621",
};
const font = "'Helvetica Neue', Helvetica, Arial, sans-serif";
const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

const ramp = (t: number, at: number, dur = 0.28) =>
  interpolate(t, [at, at + dur], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
const pop = (t: number, at: number) =>
  t < at ? 0 : spring({ frame: (t - at) * FPS, fps: FPS, config: { damping: 12, stiffness: 210, mass: 0.6 } });

type T = { t: number };

// fade and rise in at a moment
const In: React.FC<T & { at: number; rise?: number; style?: React.CSSProperties; children: React.ReactNode }> = ({
  t,
  at,
  rise = 36,
  style,
  children,
}) => {
  const k = ramp(t, at);
  return <div style={{ opacity: k, transform: `translateY(${(1 - k) * rise}px)`, ...style }}>{children}</div>;
};

// spring in from small at a moment
const Pop: React.FC<T & { at: number; style?: React.CSSProperties; children: React.ReactNode }> = ({ t, at, style, children }) => {
  const k = pop(t, at);
  return <div style={{ opacity: t >= at ? 1 : 0, transform: `scale(${0.6 + 0.4 * k})`, ...style }}>{children}</div>;
};

const Page: React.FC<{ style?: React.CSSProperties; children: React.ReactNode }> = ({ style, children }) => (
  <AbsoluteFill style={{ backgroundColor: C.black, color: C.text, fontFamily: font, fontWeight: 700, padding: 128, justifyContent: "center", ...style }}>
    {children}
  </AbsoluteFill>
);

const Label: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({ children, style }) => (
  <div style={{ fontSize: 34, letterSpacing: 4, color: C.quiet, textTransform: "uppercase", ...style }}>{children}</div>
);

const Bricks: React.FC<{ size: number }> = ({ size }) => (
  <svg width={size} height={size} viewBox="0 0 24 24">
    <path
      fill={C.brick}
      d="M.95 14.184L12 20.403l9.919-5.55v2.21L12 22.662l-10.484-5.96-.565.308v.77L12 24l11.05-6.218v-4.317l-.515-.309L12 19.118l-9.867-5.653v-2.21L12 16.805l11.05-6.218V6.32l-.515-.308L12 11.974 2.647 6.681 12 1.388l7.76 4.368.668-.411v-.566L12 0 .95 6.27v.72L12 13.207l9.919-5.55v2.26L12 15.52 1.515 9.56l-.565.308Z"
    />
  </svg>
);

const photo = (id: string) => staticFile(`built/p-${id}.jpg`);

// ---------- Beat 1: hook ----------
const Hook: React.FC<T> = ({ t }) => {
  const wipe = interpolate(t, [4.28, 4.5], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
  return (
    <Page>
      <In t={t} at={1.7}>
        <div style={{ fontSize: 168, lineHeight: 0.95, letterSpacing: -6 }}>Reliable answers</div>
      </In>
      <In t={t} at={2.5}>
        <div style={{ fontSize: 88, color: C.quiet, marginTop: 36, letterSpacing: -2 }}>from a tiny on-device model</div>
      </In>
      {/* lands on "dig in" */}
      <AbsoluteFill style={{ backgroundColor: C.yellow, clipPath: `inset(${(1 - wipe) * 100}% 0 0 0)`, padding: 128, justifyContent: "center" }}>
        <div style={{ fontSize: 240, lineHeight: 0.95, letterSpacing: -9, color: C.black, transform: `translateY(${(1 - wipe) * 80}px)` }}>
          So we had
          <br />
          to dig in.
        </div>
        <div style={{ position: "absolute", left: 128, bottom: 64, display: "flex", alignItems: "center", gap: 14 }}>
          <svg width="30" height="32" viewBox="0 0 23 24">
            <circle cx="5.4" cy="5.4" r="5.4" fill="#000" />
            <circle cx="5.4" cy="18.6" r="5.4" fill="#000" />
            <circle cx="17" cy="12" r="5.4" fill="#000" />
          </svg>
          <div style={{ fontSize: 30, fontWeight: 500, color: C.black }}>Private Eye</div>
        </div>
      </AbsoluteFill>
    </Page>
  );
};

// ---------- Beat 2: the problem ----------
const FirstVersion: React.FC<T> = ({ t }) => (
  <Page>
    <div style={{ display: "flex", alignItems: "center", gap: 72 }}>
      <Pop t={t} at={5.4}>
        <Img src={staticFile("built/logo.png")} style={{ width: 300, height: 300, borderRadius: 66 }} />
      </Pop>
      <div>
        <In t={t} at={5.5}>
          <Label>First version</Label>
        </In>
        <In t={t} at={6.3}>
          <div style={{ fontSize: 132, lineHeight: 0.98, letterSpacing: -4, marginTop: 20 }}>
            Worked by the
            <br />
            first evening.
          </div>
        </In>
      </div>
    </div>
  </Page>
);

const LastTen: React.FC<T> = ({ t }) => (
  <Page>
    <In t={t} at={7.95}>
      <div style={{ fontSize: 216, lineHeight: 0.95, letterSpacing: -8, color: C.yellow }}>The last 10%</div>
    </In>
    <In t={t} at={8.6}>
      <div style={{ fontSize: 216, lineHeight: 0.95, letterSpacing: -8, color: C.yellow }}>is the hardest.</div>
    </In>
    <In t={t} at={9.9}>
      <div style={{ fontSize: 60, color: C.quiet, marginTop: 56, letterSpacing: -1 }}>Real photos from blind users</div>
    </In>
  </Page>
);

const BloodPressure: React.FC<T> = ({ t }) => {
  const answers = ["125/80", "120/80", "120/75", "120/80", "178/92"];
  const at = [11.55, 11.9, 12.25, 12.6, 12.95];
  return (
    <Page style={{ padding: 96 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 96 }}>
        <In t={t} at={11.3} rise={0}>
          <Img src={photo("00001201")} style={{ width: 660, height: 880, objectFit: "cover", borderRadius: 28 }} />
        </In>
        <div style={{ flex: 1 }}>
          <In t={t} at={11.3}>
            <Label>Asked</Label>
            <div style={{ fontSize: 78, lineHeight: 1.05, letterSpacing: -2, marginTop: 14 }}>What is my blood pressure reading?</div>
          </In>
          <In t={t} at={11.5} style={{ marginTop: 64 }}>
            <Label>2B models answered</Label>
          </In>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "12px 44px", marginTop: 14 }}>
            {answers.map((a, i) => (
              <Pop key={i} t={t} at={at[i]} style={{ transformOrigin: "left center" }}>
                <div style={{ fontSize: 92, letterSpacing: -2, color: C.red }}>{a}</div>
              </Pop>
            ))}
          </div>
        </div>
      </div>
    </Page>
  );
};

const FiftyEight: React.FC<T> = ({ t }) => (
  <Page style={{ alignItems: "center" }}>
    <Pop t={t} at={13.42}>
      <div style={{ fontSize: 460, lineHeight: 0.9, letterSpacing: -18, color: C.red }}>58%</div>
    </Pop>
    <In t={t} at={13.8}>
      <div style={{ fontSize: 56, color: C.quiet, marginTop: 28, letterSpacing: -1 }}>hallucinated on unanswerable photos</div>
    </In>
  </Page>
);

// ---------- Beat 3: VizWiz ----------
const VizWizTitle: React.FC<T> = ({ t }) => (
  <Page>
    <In t={t} at={16.0}>
      <div style={{ fontSize: 300, lineHeight: 0.92, letterSpacing: -12, color: C.yellow }}>VizWiz</div>
    </In>
    <In t={t} at={17.0}>
      <div style={{ fontSize: 76, marginTop: 36, letterSpacing: -2 }}>20,000 photos taken by blind people</div>
    </In>
  </Page>
);

const shots: { id: string; at: number; q?: string; word?: string }[] = [
  { id: "00000719", at: 17.85, q: "What are the numbers on this product key?" },
  { id: "00002762", at: 18.5, q: "Cooking directions." },
  { id: "00002980", at: 19.15, q: "Could you tell me the sodium content of this tin?" },
  { id: "00003286", at: 19.8, q: "Can you tell me how much I weigh please?" },
  { id: "00001832", at: 20.45, q: "I know this is a medication, but what type?" },
  // the three words land over the blurriest, darkest and most off-centre photos
  { id: "00002903", at: 21.1, word: "Blurry" },
  { id: "00003047", at: 21.55, word: "Dark" },
  { id: "00004049", at: 21.95, word: "Off-centre" },
];
const SHOTS_END = 22.7;

const Photos: React.FC<T> = ({ t }) => {
  const i = shots.reduce((n, s, k) => (t >= s.at ? k : n), 0);
  const s = shots[i];
  const end = i + 1 < shots.length ? shots[i + 1].at : SHOTS_END;
  const zoom = interpolate(t, [s.at, end], [1.03, 1.1], clamp);
  return (
    <AbsoluteFill style={{ backgroundColor: C.black, fontFamily: font, fontWeight: 700 }}>
      <Img src={photo(s.id)} style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${zoom})` }} />
      {s.q && (
        <div
          style={{
            position: "absolute",
            left: 96,
            bottom: 96,
            maxWidth: 1560,
            padding: "26px 40px",
            borderRadius: 22,
            backgroundColor: "rgba(0,0,0,0.78)",
            color: C.text,
            fontSize: 66,
            lineHeight: 1.08,
            letterSpacing: -1.5,
          }}
        >
          “{s.q}”
        </div>
      )}
      {s.word && (
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", backgroundColor: "rgba(0,0,0,0.25)" }}>
          <Pop t={t} at={s.at}>
            <div style={{ fontSize: 300, letterSpacing: -10, color: C.yellow, textShadow: "0 8px 60px rgba(0,0,0,0.75)" }}>{s.word}</div>
          </Pop>
        </AbsoluteFill>
      )}
    </AbsoluteFill>
  );
};

const wall = ["00000719", "00001201", "00001750", "00001832", "00002762", "00002903", "00002980", "00003047", "00003286", "00003932", "00004049", "00004143"];

const PhotoWall: React.FC<T> = ({ t }) => {
  const zoom = interpolate(t, [22.7, 24.9], [1.0, 1.05], clamp);
  return (
    <AbsoluteFill style={{ backgroundColor: C.black, alignItems: "center", justifyContent: "center" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 320px)", transform: `scale(${zoom})` }}>
        {wall.map((id, i) => {
          const k = pop(t, 22.7 + i * 0.035);
          return (
            <Img
              key={id}
              src={photo(id)}
              style={{ width: 320, height: 427, objectFit: "cover", opacity: t >= 22.7 + i * 0.035 ? 1 : 0, transform: `scale(${0.7 + 0.3 * k})` }}
            />
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// ---------- Beat 4: Databricks ----------
const services = ["AI Gateway", "Unity Catalog", "Lakeflow Jobs", "MLflow", "AI/BI Dashboards", "Genie", "Databricks Apps"];
// db: a Databricks service, marked with their logo
const steps = [
  { at: 29.1, db: false, title: "Noisy crowd answers", sub: "10 per photo" },
  { at: 32.5, db: true, title: "AI Gateway", sub: "aggregate, fix errors" },
  { at: 35.5, db: false, title: "Classify and filter", sub: "" },
  { at: 39.2, db: true, title: "Unity Catalog", sub: "tables, volumes, model registry" },
  { at: 40.5, db: true, title: "LLM judge", sub: "a Lakeflow job" },
];
const BOX = 300;
const ARROW = 57;
const tags = [
  // the AI Gateway tags sit a little left of their box so they clear the next column's
  { at: 33.2, step: 1, row: 0, nudge: -100, text: "2 GPT models, 1 endpoint" },
  { at: 34.3, step: 1, row: 1, nudge: -100, text: "every call logged" },
  { at: 36.35, step: 2, row: 0, nudge: 30, text: "20,000 photos" },
  { at: 37.0, step: 2, row: 1, nudge: 30, text: "under an hour" },
];

const Databricks: React.FC<T> = ({ t }) => {
  const big = 1 - ramp(t, 27.2, 0.3);
  const corner = ramp(t, 27.4, 0.3);
  const active = steps.reduce((n, s, i) => (t >= s.at ? i : n), -1);
  return (
    <Page style={{ padding: 96, justifyContent: "flex-start" }}>
      {/* the logo, large, then parked in the corner for the whole beat */}
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", opacity: big, transform: `scale(${0.7 + 0.3 * big})` }}>
        <Pop t={t} at={25.2} style={{ display: "flex", alignItems: "center", gap: 56 }}>
          <Bricks size={280} />
          <div style={{ fontSize: 190, letterSpacing: -7 }}>Databricks</div>
        </Pop>
        {/* every Databricks service the project actually uses */}
        <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 20, maxWidth: 1560, marginTop: 64 }}>
          {services.map((name, i) => (
            <Pop key={name} t={t} at={25.75 + i * 0.16}>
              <div style={{ display: "flex", alignItems: "center", gap: 16, fontSize: 44, letterSpacing: -1, padding: "16px 30px", borderRadius: 18, backgroundColor: C.panel, border: `3px solid ${C.brick}` }}>
                <Bricks size={40} />
                {name}
              </div>
            </Pop>
          ))}
        </div>
      </AbsoluteFill>
      <div style={{ display: "flex", alignItems: "center", gap: 22, opacity: corner }}>
        <Bricks size={84} />
        <div style={{ fontSize: 60, letterSpacing: -2 }}>Databricks</div>
      </div>

      <In t={t} at={31.4} style={{ marginTop: 60 }}>
        <div style={{ fontSize: 104, letterSpacing: -4, color: C.yellow }}>Annotation pipeline</div>
      </In>

      <div style={{ display: "flex", alignItems: "stretch", marginTop: 76 }}>
        {steps.map((s, i) => (
          <React.Fragment key={i}>
            {i > 0 && (
              <div style={{ width: ARROW, alignSelf: "center", textAlign: "center", fontSize: 60, color: C.yellow, opacity: ramp(t, s.at - 0.1, 0.2) }}>
                →
              </div>
            )}
            <Pop t={t} at={s.at} style={{ display: "flex" }}>
              <div
                style={{
                  width: BOX,
                  minHeight: 270,
                  boxSizing: "border-box",
                  backgroundColor: C.panel,
                  borderRadius: 20,
                  border: `5px solid ${i === active ? C.yellow : "transparent"}`,
                  padding: "26px 26px",
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "center",
                  gap: 10,
                }}
              >
                {s.db && <Bricks size={46} />}
                <div style={{ fontSize: 48, lineHeight: 1.05, letterSpacing: -1.5 }}>{s.title}</div>
                {s.sub && <div style={{ fontSize: 32, lineHeight: 1.15, color: C.quiet }}>{s.sub}</div>}
              </div>
            </Pop>
          </React.Fragment>
        ))}
      </div>

      {/* tags that land with the words, each under the step it belongs to */}
      <div style={{ position: "relative", height: 220, marginTop: 52 }}>
        {tags.map((g, i) => (
          <div
            key={i}
            style={{ position: "absolute", left: g.step * (BOX + ARROW) + BOX / 2 + g.nudge, top: g.row * 104, transform: "translateX(-50%)" }}
          >
            <Pop t={t} at={g.at}>
              <div
                style={{
                  whiteSpace: "nowrap",
                  fontSize: 36,
                  padding: "16px 30px",
                  borderRadius: 999,
                  border: `4px solid ${C.yellow}`,
                  color: g.text === "under an hour" ? C.black : C.yellow,
                  backgroundColor: g.text === "under an hour" ? C.yellow : "transparent",
                }}
              >
                {g.text}
              </div>
            </Pop>
          </div>
        ))}
      </div>
    </Page>
  );
};

// ---------- Beat 5: two runs ----------
const RunOne: React.FC<T> = ({ t }) => {
  const swap = ramp(t, 45.05, 0.3); // 58% gives way to 9% (no in-between numbers are shown)
  const bar = interpolate(t, [45.05, 45.6], [58, 9], { ...clamp, easing: Easing.inOut(Easing.cubic) });
  return (
    <Page style={{ padding: 96 }}>
      <In t={t} at={42.6} style={{ position: "absolute", left: 96, top: 80 }}>
        <div style={{ fontSize: 120, letterSpacing: -4, color: C.yellow }}>Run 1</div>
      </In>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", opacity: ramp(t, 44.6, 0.2) }}>
        <div style={{ position: "relative", height: 400, width: 1200 }}>
          <div
            style={{
              position: "absolute",
              inset: 0,
              textAlign: "center",
              fontSize: 420,
              lineHeight: "400px",
              letterSpacing: -16,
              color: C.red,
              opacity: 1 - swap,
              transform: `translateY(${-swap * 120}px)`,
            }}
          >
            58%
          </div>
          <div
            style={{
              position: "absolute",
              inset: 0,
              textAlign: "center",
              fontSize: 420,
              lineHeight: "400px",
              letterSpacing: -16,
              color: C.red,
              opacity: swap,
              transform: `translateY(${(1 - swap) * 120}px)`,
            }}
          >
            9%
          </div>
        </div>
        <div style={{ width: 1200, height: 44, borderRadius: 8, backgroundColor: C.panel, marginTop: 36 }}>
          <div style={{ width: `${bar}%`, height: 44, borderRadius: 8, backgroundColor: C.red }} />
        </div>
        <div style={{ fontSize: 48, color: C.quiet, marginTop: 30, letterSpacing: -1 }}>hallucinated on unanswerable photos</div>
      </div>
    </Page>
  );
};

const LostPosition: React.FC<T> = ({ t }) => {
  const word = (text: string, at: number) => {
    const line = interpolate(t, [at, at + 0.22], [0, 100], { ...clamp, easing: Easing.out(Easing.cubic) });
    return (
      <div style={{ position: "relative", opacity: interpolate(t, [at + 0.2, at + 0.6], [1, 0.45], clamp) }}>
        <div style={{ fontSize: 280, letterSpacing: -10, lineHeight: 1 }}>{text}</div>
        <div style={{ position: "absolute", left: "-4%", top: "52%", width: `${line * 1.08}%`, height: 18, borderRadius: 9, backgroundColor: C.red }} />
      </div>
    );
  };
  return (
    <Page style={{ alignItems: "center" }}>
      <In t={t} at={46.3}>
        <Label style={{ fontSize: 44 }}>Sense of position</Label>
      </In>
      <In t={t} at={46.3} style={{ display: "flex", gap: 130, marginTop: 30 }}>
        {word("left", 46.85)}
        {word("right", 47.15)}
      </In>
    </Page>
  );
};

const Refined: React.FC<T> = ({ t }) => {
  const swap = ramp(t, 48.95, 0.3); // 20,000 gives way to 40,000
  const chips = [
    { text: "VizWiz", at: 48.75 },
    { text: "COCO", at: 49.1 },
    { text: "Our own phone frames", at: 49.45 },
  ];
  return (
    <Page style={{ padding: 96, alignItems: "center" }}>
      <div style={{ position: "absolute", right: 96, top: 80, display: "flex", alignItems: "center", gap: 16, opacity: ramp(t, 49.4, 0.25) }}>
        <Bricks size={52} />
        <div style={{ fontSize: 36, color: C.quiet }}>refined on Databricks</div>
      </div>
      <In t={t} at={48.1}>
        <Label style={{ fontSize: 40 }}>Training mix</Label>
      </In>
      <div style={{ position: "relative", height: 300, width: 1300, marginTop: 10, opacity: ramp(t, 48.2, 0.2) }}>
        <div style={{ position: "absolute", inset: 0, textAlign: "center", fontSize: 300, lineHeight: "300px", letterSpacing: -11, color: C.quiet, opacity: 1 - swap, transform: `scale(${1 - swap * 0.2})` }}>
          20,000
        </div>
        <div style={{ position: "absolute", inset: 0, textAlign: "center", fontSize: 300, lineHeight: "300px", letterSpacing: -11, color: C.yellow, opacity: swap, transform: `scale(${0.8 + swap * 0.2})` }}>
          40,000
        </div>
      </div>
      <div style={{ fontSize: 64, letterSpacing: -2, opacity: ramp(t, 48.2, 0.2) }}>examples</div>
      <div style={{ display: "flex", gap: 24, marginTop: 56 }}>
        {chips.map((c) => (
          <Pop key={c.text} t={t} at={c.at}>
            <div style={{ fontSize: 44, padding: "18px 36px", borderRadius: 18, backgroundColor: C.panel }}>{c.text}</div>
          </Pop>
        ))}
      </div>
    </Page>
  );
};

const RunTwo: React.FC<T> = ({ t }) => (
  <Page style={{ alignItems: "center" }}>
    <Pop t={t} at={50.3}>
      <div style={{ fontSize: 380, lineHeight: 0.95, letterSpacing: -14, color: C.yellow }}>Run 2</div>
    </Pop>
  </Page>
);

// ---------- Beat 6: result ----------
const WitnessName: React.FC<T> = ({ t }) => (
  <Page style={{ alignItems: "center" }}>
    <Pop t={t} at={52.4}>
      <div style={{ fontSize: 290, lineHeight: 0.95, letterSpacing: -11, color: C.yellow }}>Witness-2B</div>
    </Pop>
    <In t={t} at={52.7} style={{ display: "flex", alignItems: "center", gap: 18, marginTop: 44 }}>
      <Bricks size={52} />
      <div style={{ fontSize: 44, color: C.quiet, letterSpacing: -1 }}>Runs tracked in MLflow · model registered in Unity Catalog</div>
    </In>
  </Page>
);

const models: [string, number][] = [
  ["Witness-2B", 8],
  ["Qwen3.5-2B", 80],
  ["InternVL3.5-2B", 74],
  ["Qwen3-VL-2B", 70],
  ["LFM3-VL-2B (stock)", 58],
  ["SmolVLM2-2.2B", 57],
  ["Gemma 4 E2B", 57],
];

const Chart: React.FC<T> = ({ t }) => {
  const TRACK = 1160; // pixels for 100%
  return (
    <Page style={{ padding: "72px 96px", justifyContent: "flex-start" }}>
      <In t={t} at={53.45}>
        <div style={{ fontSize: 64, letterSpacing: -2, color: C.yellow }}>Hallucinations on 115 unanswerable photos</div>
      </In>
      <div style={{ display: "flex", flexDirection: "column", gap: 26, marginTop: 52 }}>
        {models.map(([name, pct], i) => {
          const at = 53.65 + i * 0.09;
          const grow = interpolate(t, [at, at + 0.6], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
          const ours = i === 0;
          return (
            <div key={name} style={{ display: "flex", alignItems: "center", gap: 28, opacity: ramp(t, at - 0.1, 0.2) }}>
              <div style={{ width: 430, fontSize: 40, letterSpacing: -1, color: ours ? C.yellow : C.text }}>{name}</div>
              <div style={{ width: (TRACK * pct * grow) / 100, height: 68, borderRadius: 8, backgroundColor: ours ? C.yellow : C.red }} />
              <div style={{ fontSize: 44, letterSpacing: -1, color: ours ? C.yellow : C.text, opacity: grow }}>{pct}%</div>
            </div>
          );
        })}
      </div>
      <div style={{ position: "absolute", left: 96, bottom: 44, fontSize: 28, fontWeight: 500, color: C.quiet }}>
        500 VizWiz photos, same question to every model, graded by gpt-6.1-sol.
      </div>
      {/* lands on "seven times less" */}
      <div style={{ position: "absolute", right: 80, top: 250 }}>
        <Pop t={t} at={55.55} style={{ transformOrigin: "right center" }}>
          <div
            style={{
              transform: "rotate(-3deg)",
              padding: "30px 50px",
              borderRadius: 28,
              backgroundColor: "rgba(0,0,0,0.9)",
              border: `6px solid ${C.yellow}`,
              color: C.yellow,
              fontSize: 138,
              lineHeight: 0.98,
              letterSpacing: -5,
              textAlign: "right",
            }}
          >
            7× fewer
            <br />
            hallucinations
          </div>
        </Pop>
      </div>
    </Page>
  );
};

// ---------- the sequence ----------
const scenes: { until: number; C: React.FC<T> }[] = [
  { until: 5.35, C: Hook },
  { until: 7.9, C: FirstVersion },
  { until: 11.3, C: LastTen },
  { until: 13.4, C: BloodPressure },
  { until: 15.7, C: FiftyEight },
  { until: 17.85, C: VizWizTitle },
  { until: SHOTS_END, C: Photos },
  { until: 24.9, C: PhotoWall },
  { until: 41.9, C: Databricks },
  { until: 46.25, C: RunOne },
  { until: 48.0, C: LostPosition },
  { until: 50.2, C: Refined },
  { until: 51.3, C: RunTwo },
  { until: 53.4, C: WitnessName },
  { until: Infinity, C: Chart },
];

export const Built: React.FC = () => {
  const frame = useCurrentFrame();
  const t = BUILT.from + frame / FPS;
  const Scene = scenes.find((s) => t < s.until)!.C;
  const out = interpolate(t, [BUILT.to - 0.45, BUILT.to - 0.05], [0, 1], clamp);
  return (
    <AbsoluteFill style={{ backgroundColor: C.black }}>
      <Scene t={t} />
      <AbsoluteFill style={{ backgroundColor: C.black, opacity: out }} />
      <Audio src={staticFile("raw/vo-built.m4a")} trimBefore={Math.round(BUILT.from * FPS)} />
    </AbsoluteFill>
  );
};
