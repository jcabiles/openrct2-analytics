// Element lookups and builders shared by every module. Lookups take a string literal selector
// (the page check reads them); a module keeps a reference to an element it creates.
export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const SVG = "http://www.w3.org/2000/svg";

// Creates an SVG element with its attributes and, when given, appends it to `parent`.
export function svg(tag, attrs, parent) {
  const element = document.createElementNS(SVG, tag);
  for (const name in attrs) element.setAttribute(name, attrs[name]);
  if (parent) parent.appendChild(element);
  return element;
}

export function clear(element) {
  while (element.firstChild) element.removeChild(element.firstChild);
}

export function debounce(fn, wait) {
  let timer;
  return () => {
    clearTimeout(timer);
    timer = setTimeout(fn, wait);
  };
}
