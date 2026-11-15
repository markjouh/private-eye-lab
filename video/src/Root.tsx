import React from "react";
import { Composition, Folder } from "remotion";
import { Built, builtFrames } from "./Built";
import { Cut, Full, fullFrames } from "./Demo";
import { FPS, HEIGHT, Segment, WIDTH, autoCut, demo, take, takeIds, totalFrames } from "./edit";

const size = { fps: FPS, width: WIDTH, height: HEIGHT };

export const Root: React.FC = () => (
  <>
    {/* The assembled video */}
    <Composition id="Demo" component={Full} {...size} durationInFrames={fullFrames} />

    {/* The two halves on their own */}
    <Composition id="Scenes" component={Cut} {...size} durationInFrames={totalFrames(demo)} defaultProps={{ segments: demo }} />
    <Composition id="Built" component={Built} {...size} durationInFrames={builtFrames} />

    {/* Each take on its own: the first-pass cut, and the whole thing uncut for finding moments */}
    <Folder name="takes">
      {takeIds.map((id) => {
        const cut = autoCut(id);
        const full: Segment[] = [{ take: id, start: 0, end: take(id).screenDur }];
        return (
          <React.Fragment key={id}>
            <Composition id={`${id}-cut`} component={Cut} {...size} durationInFrames={totalFrames(cut)} defaultProps={{ segments: cut }} />
            <Composition id={`${id}-full`} component={Cut} {...size} durationInFrames={totalFrames(full)} defaultProps={{ segments: full }} />
          </React.Fragment>
        );
      })}
    </Folder>
  </>
);
