// Starts the page: motion, the section bar, the hero park, then each section's module in page
// order. It owns the one debounced resize, which redraws what depends on the window size.
import { debounce } from "./dom.mjs";
import { drawGuilloche, fit, init as heroScene } from "./hero-scene.mjs";
import { init as motion } from "./motion.mjs";
import { init as nav } from "./nav.mjs";
import { init as extractRoll } from "./extract-roll.mjs";
import { init as infraTrack } from "./infra-track.mjs";
import { init as crew } from "./crew.mjs";
import { init as story } from "./story.mjs";
import { init as insights } from "./insights.mjs";
import { init as finance } from "./finance.mjs";
import { init as ops } from "./ops.mjs";
import { init as attractions } from "./attractions.mjs";

drawGuilloche();
nav();
heroScene();
for (const init of [extractRoll, infraTrack, crew, story, insights, finance, ops, attractions]) init();
motion();

let lastWidth = innerWidth;
addEventListener(
  "resize",
  debounce(() => {
    if (Math.abs(innerWidth - lastWidth) < 2) return;
    lastWidth = innerWidth;
    drawGuilloche();
    fit();
  }, 200),
);
