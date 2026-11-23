// The section bar: it slides in once the hero coupons have scrolled under it, marks the current
// section, and an event dot rides its rule to the current link. Coupon and menu links jump to
// their section. The link lists themselves are rendered at build time.
import { $, $$ } from "./dom.mjs";
import { motion } from "./motion.mjs";

export function init() {
  const nav = $("#topbar");
  const button = $("#tb-btn");
  const dot = $("#tb-dot");
  const nowText = $("#tb-now-text");
  const inner = $(".topbar-in", nav);
  const coupons = $(".coupons");
  const links = $$("[data-spy-link]", nav);
  const ids = links.map((link) => link.dataset.spyLink);
  const sections = $$("section[data-spy]");
  const fallback = nowText.textContent;
  const wide = matchMedia("(min-width: 1100px)");
  let current = null;
  let ticking = false;

  function setOpen(open, returnFocus) {
    nav.dataset.open = String(open);
    button.setAttribute("aria-expanded", String(open));
    if (open) links[Math.max(0, ids.indexOf(current))].focus();
    else if (returnFocus) button.focus();
  }

  function update() {
    ticking = false;
    const shown = coupons.getBoundingClientRect().bottom <= nav.offsetHeight + 24;
    if (!shown && nav.dataset.open === "true") setOpen(false, false);
    nav.dataset.shown = String(shown);
    const probe = nav.offsetHeight + innerHeight * 0.3;
    let next = null;
    for (const section of sections) {
      if (section.getBoundingClientRect().top <= probe) next = section.dataset.spyAs || section.id;
    }
    if (next !== current) {
      current = next;
      for (const link of links) {
        if (link.dataset.spyLink === current) link.setAttribute("aria-current", "location");
        else link.removeAttribute("aria-current");
      }
      const link = links[ids.indexOf(current)];
      nowText.textContent = link ? link.dataset.title : fallback;
    }
    const link = links[ids.indexOf(current)];
    if (link && wide.matches) {
      const box = link.getBoundingClientRect();
      const home = inner.getBoundingClientRect();
      dot.style.transform = `translateX(${(box.left + box.width / 2 - home.left).toFixed(1)}px)`;
      dot.style.opacity = 1;
    } else dot.style.opacity = 0;
  }

  const queue = () => {
    if (!ticking) {
      ticking = true;
      requestAnimationFrame(update);
    }
  };
  addEventListener("scroll", queue, { passive: true });
  addEventListener("resize", queue);
  button.addEventListener("click", () => setOpen(nav.dataset.open !== "true", false));

  // Tab past the last link: close the sheet and carry on from the first control below the bar.
  const focusable = (node) =>
    (node.tagName === "A" && node.hasAttribute("href")) ||
    ((node.tagName === "BUTTON" || node.tagName === "INPUT") && !node.disabled) ||
    node.getAttribute("tabindex") === "0";
  const below = () => {
    const top = nav.offsetHeight;
    return $$("main *").find((node) => {
      if (!focusable(node)) return false;
      const box = node.getBoundingClientRect();
      return box.height > 0 && box.top >= top && box.top < innerHeight;
    });
  };
  nav.addEventListener("keydown", (event) => {
    if (nav.dataset.open !== "true") return;
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false, true);
      return;
    }
    const sheetLinks = $$("#tb-links a", nav);
    if (event.key === "Tab" && !event.shiftKey && document.activeElement === sheetLinks.at(-1)) {
      event.preventDefault();
      setOpen(false, false);
      const section = sections.find((candidate) => candidate.id === current);
      const next = below() || (section && section.querySelector("h2"));
      if (next) next.focus({ preventScroll: true });
    }
  });
  nav.addEventListener("focusout", (event) => {
    if (nav.dataset.open === "true" && event.relatedTarget && !nav.contains(event.relatedTarget)) {
      setOpen(false, false);
    }
  });
  document.addEventListener("click", (event) => {
    if (nav.dataset.open === "true" && !nav.contains(event.target)) setOpen(false, false);
  });

  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[data-jump]");
    if (!link) return;
    const section = sections.find((candidate) => candidate.id === link.dataset.jump);
    if (!section) return;
    event.preventDefault();
    if (link.classList.contains("coupon") && !motion.reduced) {
      link.classList.add("torn");
      setTimeout(() => link.classList.remove("torn"), 360);
    }
    setOpen(false, false);
    const heading = section.querySelector("h2");
    section.scrollIntoView({ behavior: motion.reduced ? "auto" : "smooth", block: "start" });
    if (heading) heading.focus({ preventScroll: true });
    history.replaceState(null, "", `#${link.dataset.jump}`);
  });

  update();
}
