// The infrastructure section: the block-section track, the failure simulator and the reconciliation
// panel. The lines, the failure texts and the panels are rendered at build time; this module paints
// block states, shows one panel, and places the shaded box, the branch drop and the train. No
// animation library is loaded, so the train sits at its last stop and does not move (R23).
import { $, $$, debounce } from "./dom.mjs";
import { setStyle } from "./motion.mjs";

const STATUS = { clear: "clear", held: "held", fault: "fault", idle: "no new data" };
const TRAIN = { width: 58, height: 14, lift: 12 };

// Per failure: `at` is the block that catches it; `states` and `txt` override the default painting
// of a block's state and status word; `stop` is where the train halts when it is not the block
// before `at`; `branch` marks a failure on the line to this page.
const FAULTS = {
  listener: { at: "listener" },
  seq: { at: "seq", states: { raw: "clear", parquet: "held" }, txt: { parquet: "written, not checked" } },
  unknown: { at: "parquet", states: { raw: "held", seq: "idle" }, txt: { parquet: "nothing written" }, stop: "raw" },
  contract: { at: "contracts" },
  registry: {
    at: "contracts",
    states: { publish: "fault", audit: "idle", warehouse: "idle" },
    txt: { publish: "fails closed" },
  },
  books: { at: "tests", states: { publish: "fault" }, txt: { publish: "fails at dbt" } },
  publish: { at: "audit" },
  export: { at: "xcheck", branch: true },
};

let current = null;

const blocks = (list) => [...list.children].filter((li) => li.dataset.id);
const idsOf = (list) => blocks(list).map((li) => li.dataset.id);

function stateOf(ids, fault) {
  const index = fault ? ids.indexOf(fault.at) : -1;
  return ids.map((id, i) => {
    if (fault && fault.states && fault.states[id]) return fault.states[id];
    if (index < 0 || i < index - 1) return "clear";
    return i === index - 1 ? "held" : i === index ? "fault" : "idle";
  });
}

// The branch leaves after the dbt tests, so a main-line failure at or before them leaves it with no new data.
function branchStates(fault) {
  const branchIds = idsOf($("#branchline"));
  if (fault && fault.branch) return stateOf(branchIds, fault);
  const mainIds = idsOf($("#mainline"));
  const stopped = fault && mainIds.indexOf(fault.at) <= mainIds.indexOf("tests");
  return branchIds.map(() => (stopped ? "idle" : "clear"));
}

function paint(list, states) {
  blocks(list).forEach((li, i) => {
    const id = li.dataset.id;
    const state = states[i];
    const word = li.querySelector(".st");
    let text = STATUS[state];
    if ((id === "warehouse" || id === "page") && state === "idle") text = "unchanged";
    if (id === "game" && state === "held") text = "queueing";
    if (current && current.txt && current.txt[id]) text = current.txt[id];
    li.dataset.state = state;
    if (word) {
      word.textContent = text;
      word.className = `st st-${state}`;
    }
    li.setAttribute("aria-label", `${li.dataset.label}: ${text}`);
  });
}

// The shaded DuckDB box and the branch drop follow the laid-out lines.
// Below this width the line runs down the page: the blocks stack as full-width cards, the
// reconciliation panel moves into the slot after the dbt tests check, and the train is hidden.
const NARROW_TRACK = 680;
let vertical = false;
const reconSlot = document.createElement("li");
reconSlot.className = "note";
function layout() {
  const areaEl = $("#track-area");
  const areaBox = areaEl.getBoundingClientRect();
  vertical = areaBox.width - 48 < NARROW_TRACK;
  areaEl.classList.toggle("v", vertical);
  const recon = $("#recon");
  if (vertical) {
    if (recon.parentElement !== reconSlot) reconSlot.appendChild(recon);
  } else if (recon.parentElement !== $("#spur")) $("#spur").insertBefore(recon, $("#branchline"));
  $("#trk-train").hidden = vertical;
  const area = areaEl.getBoundingClientRect();
  const main = $("#mainline");
  const mainBox = main.getBoundingClientRect();
  const first = main.querySelector('[data-id="dbt"]').getBoundingClientRect();
  const last = main.querySelector('[data-id="warehouse"]').getBoundingClientRect();
  const box = $("#encl").style;
  if (vertical) {
    box.left = `${mainBox.left - area.left - 6}px`;
    box.width = `${area.right - mainBox.left - 18}px`;
    box.top = `${first.top - area.top - 40}px`;
    box.height = `${last.bottom - first.top + 48}px`;
    $("#spur").style.removeProperty("--spur-cols");
    return;
  }
  box.left = `${first.left - area.left - 4}px`;
  box.width = `${last.right - first.left + 12}px`;
  box.top = `${mainBox.top - area.top - 22}px`;
  box.height = `${last.bottom - mainBox.top + 32}px`;
  const spur = $("#spur");
  const tests = main.querySelector('[data-id="tests"] .lamp').getBoundingClientRect();
  const dropX = Math.round(tests.left + tests.width / 2 - spur.getBoundingClientRect().left);
  spur.style.setProperty("--spur-cols", `${dropX - 2}px minmax(0,1fr)`);
  const spurBox = spur.getBoundingClientRect();
  const branch = $("#branchline .lamp").getBoundingClientRect();
  const lineY = mainBox.top + 58 - spurBox.top;
  const endY = branch.top + branch.height / 2 - spurBox.top;
  const drop = $("#spur-drop").style;
  drop.left = `${dropX - 2}px`;
  drop.top = `${lineY + 18}px`;
  drop.height = `${Math.max(0, endY + 2 - (lineY + 18))}px`;
}

// The train sits at the last block the batch reaches: the one before the failure, or the last one.
function placeTrain() {
  if (vertical) return;
  const area = $("#track-area").getBoundingClientRect();
  const main = $("#mainline");
  const lamps = blocks(main).map((li) => li.querySelector(".lamp").getBoundingClientRect());
  const ids = idsOf(main);
  const caught = current && !current.branch ? ids.indexOf(current.at) : -1;
  const stopped = current && current.stop ? ids.indexOf(current.stop) : -1;
  const stop = stopped >= 0 ? stopped : caught >= 0 ? Math.max(0, caught - 1) : lamps.length - 1;
  const x = lamps[stop].left + lamps[stop].width / 2 - area.left - TRAIN.width / 2;
  const y = lamps[0].top + lamps[0].height / 2 - area.top - TRAIN.height - TRAIN.lift;
  setStyle($("#trk-train"), { transform: `translate(${x}px, ${y}px)` });
}

function applyFault(id) {
  current = FAULTS[id] || null;
  const shown = current ? id : "clear";
  paint($("#mainline"), stateOf(idsOf($("#mainline")), current && !current.branch ? current : null));
  paint($("#branchline"), branchStates(current));
  for (const panel of $$("[data-panel]")) panel.hidden = panel.dataset.panel !== shown;
  for (const result of $$("[data-res]")) result.hidden = result.dataset.res !== shown;
  $("#fault-res .lamp").dataset.state = current ? "fault" : "clear";
  $("#callout").dataset.state = current ? "fault" : "clear";
  $("#fault-clear").disabled = !current;
  placeTrain();
}

export function init() {
  $('#mainline [data-id="tests"]').after(reconSlot);
  const more = $(".recon-more");
  more.addEventListener("click", () => {
    const open = more.getAttribute("aria-expanded") !== "true";
    more.setAttribute("aria-expanded", String(open));
    $("#recon-full").hidden = !open;
    for (const word of $$("[data-more]")) word.hidden = word.dataset.more !== (open ? "hide" : "show");
    layout();
    placeTrain();
  });
  $("#fault-list").addEventListener("change", (event) => {
    if (event.target.name === "fault") applyFault(event.target.value);
  });
  $("#fault-clear").addEventListener("click", () => {
    for (const input of $$("#fault-list input")) input.checked = false;
    applyFault(null);
    $("#fault-list input").focus();
  });
  addEventListener(
    "resize",
    debounce(() => {
      layout();
      placeTrain();
    }, 200),
  );
  layout();
  applyFault(null);
}
