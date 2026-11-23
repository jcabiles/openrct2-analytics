// One pause control for every loop on the page (R23). No animation library is loaded, so every
// tween and fade takes the frozen copy's instant path: the end state applies at once.
import { $$ } from "./dom.mjs";

const reducedQuery = matchMedia("(prefers-reduced-motion: reduce)");
export const motion = { on: !reducedQuery.matches, reduced: reducedQuery.matches };
const listeners = [];

// A loop registers here and is called whenever motion starts or stops.
export const onMotionChange = (listener) => listeners.push(listener);

// The instant path for what the frozen copy tweens: attributes and styles apply at once.
export function setAttrs(element, attrs) {
  for (const name in attrs) element.setAttribute(name, attrs[name]);
}
export const setStyle = (element, style) => Object.assign(element.style, style);

function apply() {
  for (const button of $$("[data-motion-toggle]")) {
    button.hidden = motion.reduced;
    button.querySelector("use").setAttribute("href", motion.on ? "#i-pause" : "#i-play");
    button.querySelector("span").textContent = motion.on ? "Pause motion" : "Play motion";
  }
  for (const listener of listeners) listener();
}

export function init() {
  for (const button of $$("[data-motion-toggle]")) {
    button.addEventListener("click", () => {
      motion.on = !motion.on;
      apply();
    });
  }
  // The setting can change mid-visit: stop or restart the loops.
  reducedQuery.addEventListener("change", (event) => {
    motion.reduced = event.matches;
    motion.on = !event.matches;
    apply();
  });
  apply();
}
