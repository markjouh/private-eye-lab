import React from "react";
import { Audio, Video } from "@remotion/media";
import { AbsoluteFill, Freeze, Img, Sequence, Series, interpolate, spring, staticFile, useCurrentFrame } from "remotion";
import { Built, builtFrames } from "./Built";
import { FPS, Piece, Segment, demo, finale, outro, resolve, segmentFrames, take, totalFrames } from "./edit";

// Video and Audio come from @remotion/media, not <OffthreadVideo>/<video>: the studio keeps
// every segment's <video> element loaded at once, and with ~18 of them they starved each
// other for connections, which stalled playback and made the audio stutter and repeat.

const f = (sec: number) => Math.max(0, Math.round(sec * FPS));
const shadow = "0 12px 60px rgba(0,0,0,0.55)";
const phoneStyle: React.CSSProperties = { height: 1000, borderRadius: 40, boxShadow: shadow };

const Clip: React.FC<{ piece: Piece; fadeOut?: number }> = ({ piece, fadeOut = 0 }) => {
  const t = take(piece.take);
  const hasCamera = t.outsideDur > 0;
  const showCamera = piece.layout !== "screen";
  const showScreen = piece.layout !== "outside";
  const cameraFrom = f(piece.start + t.offset);
  const screenFrom = f(piece.start);

  // Pictures are always silent; the sound is one separate track, so it can come from either clip.
  const length = segmentFrames(piece);
  const level = piece.audio === "outside" ? 10 ** (piece.gainDb / 20) : 1;
  // fadeOut: the last frames of the video, where the sound fades with the picture
  const volume = (fr: number) =>
    level * (fadeOut ? interpolate(fr, [length - fadeOut, length], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) : 1);
  const sound =
    piece.audio === "outside" ? (
      <Audio src={staticFile(t.outside)} trimBefore={cameraFrom} volume={volume} />
    ) : (
      <Audio src={staticFile(t.screen)} trimBefore={screenFrom} volume={volume} />
    );

  const hold = (which: "screen" | "outside", el: React.ReactElement) =>
    piece.freeze === which ? <Freeze frame={0}>{el}</Freeze> : el;

  const screen = hold(
    "screen",
    <Video muted src={staticFile(t.screen)} trimBefore={piece.freeze === "screen" ? 0 : screenFrom} style={phoneStyle} />,
  );
  const camera = (style: React.CSSProperties, fit: "cover" | "contain") =>
    hold(
      "outside",
      <Video muted src={staticFile(t.outside)} trimBefore={piece.freeze === "outside" ? 0 : cameraFrom} style={style} objectFit={fit} />,
    );

  // Landscape camera fills the frame, phone screen floats on the right.
  if (showCamera && !t.outsidePortrait && piece.layout !== "split") {
    return (
      <AbsoluteFill style={{ backgroundColor: "black" }}>
        {camera({ width: "100%", height: "100%" }, "cover")}
        {showScreen && <div style={{ position: "absolute", right: 60, top: 40, display: "flex" }}>{screen}</div>}
        {sound}
      </AbsoluteFill>
    );
  }

  // Otherwise: camera and/or phone screen side by side, centred over a blurred still of the camera view.
  return (
    <AbsoluteFill style={{ backgroundColor: "#0b0b0d" }}>
      {hasCamera && (
        <Img
          src={staticFile(t.poster)}
          style={{ width: "100%", height: "100%", objectFit: "cover", filter: "blur(40px) brightness(0.45)", transform: "scale(1.15)" }}
        />
      )}
      {/* A portrait camera beside the phone sits to the right, leaving the left clear for the title. */}
      <AbsoluteFill
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 70,
          justifyContent: showCamera && showScreen && t.outsidePortrait ? "flex-end" : "center",
          paddingRight: showCamera && showScreen && t.outsidePortrait ? 100 : 0,
        }}
      >
        {showCamera &&
          camera(
            t.outsidePortrait
              ? { height: 1000, borderRadius: 28, boxShadow: shadow }
              : { width: showScreen ? 1290 : 1700, borderRadius: 28, boxShadow: shadow },
            "contain",
          )}
        {showScreen && screen}
      </AbsoluteFill>
      {sound}
    </AbsoluteFill>
  );
};

// Feature label, top-left, held for the whole scene. Fades and slides in, fades out.
const Label: React.FC<{ title: string; sub?: string; frames: number }> = ({ title, sub, frames }) => {
  const frame = useCurrentFrame();
  const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
  const appear = interpolate(frame, [0, 10], [0, 1], clamp);
  const leave = interpolate(frame, [frames - 8, frames], [1, 0], clamp);
  return (
    <div
      style={{
        position: "absolute",
        left: 56,
        top: 48,
        maxWidth: 640,
        opacity: appear * leave,
        transform: `translateY(${(1 - appear) * -14}px)`,
        display: "flex",
        alignItems: "stretch",
        gap: 20,
        padding: "18px 28px 18px 20px",
        borderRadius: 22,
        backgroundColor: "rgba(12,12,14,0.78)",
        boxShadow: "0 8px 30px rgba(0,0,0,0.35)",
        fontFamily: "-apple-system, 'SF Pro Display', 'Helvetica Neue', Arial, sans-serif",
        color: "white",
      }}
    >
      <div style={{ width: 8, borderRadius: 4, backgroundColor: "#FFD60A" }} />
      <div>
        <div style={{ fontSize: 46, fontWeight: 700, letterSpacing: -0.5, lineHeight: 1.1 }}>{title}</div>
        {sub && <div style={{ fontSize: 26, fontWeight: 500, opacity: 0.8, marginTop: 6 }}>{sub}</div>}
      </div>
    </div>
  );
};

// The closing words: huge, stacked in the clear left side, each popping in as it is spoken.
const BigWords: React.FC<{ cues: { word: string; at: number }[] }> = ({ cues }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ justifyContent: "center", paddingLeft: 64 }}>
      <div
        style={{
          transform: "rotate(-5deg)",
          transformOrigin: "left center",
          fontFamily: "-apple-system, 'SF Pro Display', 'Helvetica Neue', Arial, sans-serif",
          fontWeight: 900,
          fontSize: 214,
          lineHeight: 0.92,
          letterSpacing: -6,
          color: "white",
          textShadow: "0 10px 50px rgba(0,0,0,0.6)",
        }}
      >
        {cues.map((c, i) => {
          const pop = spring({ frame: frame - c.at, fps: FPS, config: { damping: 9, stiffness: 190, mass: 0.6 } });
          return (
            <div
              key={i}
              style={{
                opacity: frame >= c.at ? 1 : 0,
                transform: `scale(${0.55 + 0.45 * pop})`,
                transformOrigin: "left center",
                color: i === cues.length - 1 ? "#FFD60A" : "white",
              }}
            >
              {c.word}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

export const Cut: React.FC<{ segments: Segment[]; ending?: boolean }> = ({ segments, ending = false }) => {
  const pieces = resolve(segments);
  const starts: number[] = [];
  let total = 0;
  for (const p of pieces) {
    starts.push(total);
    total += segmentFrames(p);
  }

  // where each closing word lands on the timeline
  const cues = !ending
    ? []
    : outro.cues.flatMap((c) => {
        const i = pieces.findIndex((p) => p.take === c.take && c.at >= p.start && c.at < p.end);
        return i < 0 ? [] : [{ word: c.word, at: starts[i] + Math.round((c.at - pieces[i].start) * FPS) }];
      });
  const wordsFrom = cues.length ? cues[0].at - 4 : total;
  const fade = ending ? Math.round(outro.fadeSec * FPS) : 0;

  // one label per run of consecutive pieces that share a title; the last gives way to the closing words
  const labels: { title: string; sub?: string; from: number; frames: number }[] = [];
  pieces.forEach((p, i) => {
    const n = segmentFrames(p);
    const last = labels.at(-1);
    if (p.title && last && last.title === p.title && last.sub === p.sub && last.from + last.frames === starts[i]) last.frames += n;
    else if (p.title) labels.push({ title: p.title, sub: p.sub, from: starts[i], frames: n });
  });
  for (const l of labels) l.frames = Math.max(1, Math.min(l.from + l.frames, wordsFrom) - l.from);

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      <Series>
        {pieces.map((p, i) => (
          <Series.Sequence key={i} durationInFrames={segmentFrames(p)} premountFor={FPS} name={`${p.take} ${p.start.toFixed(1)}–${p.end.toFixed(1)}`}>
            <Clip piece={p} fadeOut={i === pieces.length - 1 ? fade : 0} />
          </Series.Sequence>
        ))}
      </Series>
      {labels
        .filter((l) => l.from < wordsFrom)
        .map((l) => (
          <Sequence key={l.from} from={l.from} durationInFrames={l.frames} name={`title: ${l.title}`}>
            <Label title={l.title} sub={l.sub} frames={l.frames} />
          </Sequence>
        ))}
      {cues.length > 0 && (
        <Sequence from={wordsFrom} name="closing words">
          <BigWords cues={cues.map((c) => ({ ...c, at: c.at - wordsFrom }))} />
        </Sequence>
      )}
      {fade > 0 && (
        <Sequence from={total - fade} name="fade to black">
          <FadeToBlack frames={fade} />
        </Sequence>
      )}
    </AbsoluteFill>
  );
};

const FadeToBlack: React.FC<{ frames: number }> = ({ frames }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, frames - 3], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return <AbsoluteFill style={{ backgroundColor: "black", opacity }} />;
};

// The whole video: the demo scenes, "How we built Witness-2B", then the last bagel clip.
export const fullFrames = totalFrames(demo) + builtFrames + totalFrames(finale);
export const Full: React.FC = () => (
  <Series>
    <Series.Sequence durationInFrames={totalFrames(demo)} name="demo scenes">
      <Cut segments={demo} />
    </Series.Sequence>
    <Series.Sequence durationInFrames={builtFrames} name="how we built it">
      <Built />
    </Series.Sequence>
    <Series.Sequence durationInFrames={totalFrames(finale)} name="let's dig in">
      <Cut segments={finale} ending />
    </Series.Sequence>
  </Series>
);
