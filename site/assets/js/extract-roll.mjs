// The extraction section: the serial roll with its audit verdict, and the tick gauges. No animation
// library is loaded, so the three buttons show their instant result (R23); the verdict texts are
// rendered at build time and this module only shows one of them.
import { $, $$, clear } from "./dom.mjs";

const COUNT = 8;
const PULLED = 5;
const REPEATED = 3;

const roll = { tickets: [], pulled: false, repeated: false };

function reset() {
  roll.tickets = Array.from({ length: COUNT }, (_, index) => ({ n: index + 1, kind: "ok" }));
  roll.pulled = false;
  roll.repeated = false;
}

function ticket({ n, kind }) {
  const element = document.createElement("div");
  const small = document.createElement("small");
  const number = document.createElement("b");
  element.className = kind === "ok" ? "tk" : `tk ${kind}`;
  element.setAttribute("role", "listitem");
  element.setAttribute("aria-label", `seq ${n}${kind === "gap" ? " missing" : kind === "dup" ? " repeated" : ""}`);
  small.textContent = kind === "gap" ? "missing" : kind === "dup" ? "again" : "seq";
  number.textContent = String(n);
  element.append(small, number);
  return element;
}

function draw() {
  const box = $("#serials");
  clear(box);
  for (const item of roll.tickets) box.appendChild(ticket(item));
  const key = roll.pulled && roll.repeated ? "both" : roll.pulled ? "gap" : roll.repeated ? "dup" : "pass";
  for (const block of $$("[data-verdict]")) block.hidden = block.dataset.verdict !== key;
  $("#verdict").className = key === "pass" ? "verdict" : "verdict fail";
  $("#pull").disabled = roll.pulled;
  $("#dup").disabled = roll.repeated;
  $("#reroll").disabled = !roll.pulled && !roll.repeated;
}

// A pressed button that just disabled itself hands focus to the next enabled control.
function passFocus(button) {
  if (!button.disabled) return;
  const next = [$("#pull"), $("#dup"), $("#reroll")].find((candidate) => !candidate.disabled);
  (next || $("#verdict")).focus();
}

function drawGauges() {
  for (const fill of $$(".meter-fill")) {
    fill.style.width = `${((Number(fill.dataset.meter) / Number(fill.dataset.max)) * 100).toFixed(2)}%`;
  }
}

export function init() {
  reset();
  draw();
  drawGauges();
  $("#pull").addEventListener("click", () => {
    const index = roll.tickets.findIndex((item) => item.n === PULLED && item.kind === "ok");
    roll.tickets[index] = { n: PULLED, kind: "gap" };
    roll.pulled = true;
    draw();
    passFocus($("#pull"));
  });
  $("#dup").addEventListener("click", () => {
    const index = roll.tickets.findIndex((item) => item.n === REPEATED);
    roll.tickets.splice(index + 1, 0, { n: REPEATED, kind: "dup" });
    roll.repeated = true;
    draw();
    passFocus($("#dup"));
  });
  $("#reroll").addEventListener("click", () => {
    reset();
    draw();
    $("#pull").focus();
  });
}
