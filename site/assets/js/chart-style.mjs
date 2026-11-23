// Token reader for Plot (R24): charts take their colours and type from the custom properties in
// tokens.css, read at draw time, never from a colour literal in a module.
export const token = (name) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// The base style object every Plot chart on the page starts from.
export const plotStyle = () => ({
  fontFamily: token("--font"),
  color: token("--ink"),
  background: "transparent",
});
