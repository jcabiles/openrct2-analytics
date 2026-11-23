// "How it was built": the build crew's hover detail and the data stack's reading panel. Both read
// the text the page build already placed in the markup; this module only shows and hides it.
import { $, $$ } from "./dom.mjs";

const CLOSE_DELAY = 150;

// One popover at a time. Hover, focus or click opens; leaving, blur, a second click, an outside
// click or Escape closes.
function crewPopovers() {
  const buttons = $$("[data-pop]", $("#crew"));
  let openButton = null;
  let openBy = "";
  let timer = 0;
  const popOf = (button) =>
    $$(".cr-pop", button.parentNode).find((pop) => pop.id === button.getAttribute("aria-controls"));
  function hide() {
    clearTimeout(timer);
    if (!openButton) return;
    popOf(openButton).hidden = true;
    openButton.setAttribute("aria-expanded", "false");
    openButton = null;
    openBy = "";
  }
  function show(button, by) {
    clearTimeout(timer);
    if (openButton !== button) {
      hide();
      popOf(button).hidden = false;
      button.setAttribute("aria-expanded", "true");
      openButton = button;
    }
    openBy = by;
  }
  // A short delay lets the pointer cross the gap from a box into its popover.
  const hideSoon = () => {
    clearTimeout(timer);
    timer = setTimeout(hide, CLOSE_DELAY);
  };
  for (const button of buttons) {
    const pop = popOf(button);
    button.addEventListener("mouseenter", () => show(button, openButton === button ? openBy : "hover"));
    button.addEventListener("mouseleave", () => {
      if (openButton === button && openBy !== "focus") hideSoon();
    });
    pop.addEventListener("mouseenter", () => {
      if (openButton === button) clearTimeout(timer);
    });
    pop.addEventListener("mouseleave", () => {
      if (openButton === button && openBy !== "focus") hideSoon();
    });
    button.addEventListener("focus", () => show(button, "focus"));
    button.addEventListener("blur", () => {
      if (openButton === button) hide();
    });
    button.addEventListener("click", () => {
      if (openButton === button && openBy === "click") hide();
      else show(button, "click");
    });
  }
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && openButton) hide();
  });
  document.addEventListener("click", (event) => {
    if (openButton && !openButton.parentNode.contains(event.target)) hide();
  });
}

// The board lists the tools in bands; the chosen tool's detail shows in the panel and lights its
// band, and "The whole stack" lights every band.
function dataStack() {
  const wrap = $(".stack-wrap");
  const board = $("#board");
  const panel = $("#explain");
  const dock = matchMedia("(max-width:960px)");
  const buttons = $$("button", board);
  const bands = $$(".band", board);
  const details = $$(".tool", panel);
  const chosen = () => buttons.find((button) => button.getAttribute("aria-pressed") === "true");
  function showTool(button, live) {
    const whole = button.dataset.band === "";
    for (const detail of details) detail.hidden = detail.id !== button.getAttribute("aria-controls");
    panel.setAttribute("aria-live", live ? "polite" : "off");
    panel.dataset.whole = String(whole);
    board.dataset.whole = String(whole);
    for (const band of bands) band.classList.toggle("lit", whole || band.dataset.band === button.dataset.band);
  }
  // On narrow screens the panel sits under the chosen line instead of beside the board.
  function dockPanel() {
    if (dock.matches) chosen().parentNode.appendChild(panel);
    else if (panel.parentNode !== wrap) wrap.appendChild(panel);
  }
  function pick(button) {
    for (const other of buttons) other.setAttribute("aria-pressed", String(other === button));
    showTool(button, true);
    dockPanel();
  }
  for (const button of buttons) {
    // Hover previews the panel beside the board and leaves the chosen entry as it is; under a line
    // it would move the lines under the pointer.
    button.addEventListener("mouseenter", () => {
      if (!dock.matches) showTool(button, false);
    });
    button.addEventListener("focus", () => pick(button));
    button.addEventListener("click", () => pick(button));
  }
  board.addEventListener("mouseleave", () => {
    if (!dock.matches) showTool(chosen(), false);
  });
  dock.addEventListener("change", dockPanel);
  showTool(chosen(), false);
}

export function init() {
  crewPopovers();
  dataStack();
}
