// The Finance view: draws the profit chart and redraws it when the desk's range brush or park
// switch changes, and shows "figure pending" when the choice holds no month rows. The chart takes
// its park colours from the desk's park order. With no month rows the desk sets no range and
// nothing is wired (R15).
import { $ } from "./dom.mjs";
import { desk, parkData, parkMonthData } from "./data.mjs";
import { onDeskChange, selectedMonths } from "./insights.mjs";
import { deskParks } from "./rows/insights.mjs";
import { redrawParkMonthChart } from "../park-month-chart.mjs";

export function init() {
  if (desk.range === null) return;
  const empty = $("[data-finance-empty]");
  const order = deskParks({ park_month: parkMonthData(), park: parkData() }).map((park) => park.park_id);
  const draw = () => {
    empty.hidden = redrawParkMonthChart(selectedMonths(), desk.park, order) > 0;
  };
  onDeskChange(draw);
  draw();
}
