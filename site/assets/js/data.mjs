// The embedded-rows reader, the state the insights desk shares, the park colour rule and the dollar
// format. Only this module and park-month-chart.mjs read the page's JSON blocks (R15, R23).
export const parkMonthData = () => JSON.parse(document.getElementById("park-month-data").textContent);
export const parkData = () => JSON.parse(document.getElementById("park-data").textContent);

// The colour class of the park at a zero-based position in park order: the first two parks have
// their own colours and every later park shares the repeat colour. The legend, the opening list and
// the chart all read this one rule.
export const parkClass = (index) => (index === 0 ? "p1" : index === 1 ? "p2" : "rep");

// Shared desk state: the chosen month range, park and view; each view reads and sets it.
export const desk = { range: null, park: null, view: null };

// The browser formatter; site/figures.mjs `usd` is the build-time one (Node), and both exist
// because the page text is rendered at build time while the charts format in the browser.
export const usd = (value, digits = 2) =>
  value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
