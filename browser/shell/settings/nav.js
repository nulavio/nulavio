/* Settings in two panes (UX4, audit SPA-04/05): the rail shows one section per address
   (#dns, #routing… keep working, as do addresses of a card inside a section), marks it with
   aria-current, and filters the cards of every section by what they say. Sections stay
   [hidden] while their feature is unavailable; the rail hides their entries too. */

import { t } from "../lib/i18n.js";

const main = document.getElementById("settings-main");
const sections = [...main.querySelectorAll(":scope > .section")];
const links = [...document.querySelectorAll(".settings-nav a[data-section]")];
const search = document.getElementById("settings-search");
const results = document.getElementById("settings-results");
let active = null;

/** Lower case without accents, so "resolvedor" finds "Resolvedor" and "seguranca" finds "segurança". */
export function fold(text) {
  return String(text).normalize("NFD").replace(/\p{M}/gu, "").toLocaleLowerCase();
}

function sectionFor(id) {
  const target = id ? document.getElementById(id) : null;
  return target && main.contains(target) ? target.closest(".section") : null;
}

function firstAvailable() {
  for (const link of links) {
    const section = document.getElementById(link.dataset.section);
    if (section && !section.hidden) {
      return section;
    }
  }
  return null;
}

const rail = document.querySelector(".settings-nav");

/* In a narrow window the rail is one scrolling row (QA R2-1): bring the open section's entry
   into it, and mark the sides where more entries are hidden (pages.css draws a fade there). */
function revealInRail(link) {
  if (link && rail.scrollWidth > rail.clientWidth) {
    const box = rail.getBoundingClientRect();
    const item = link.getBoundingClientRect();
    if (item.left < box.left || item.right > box.right) {
      rail.scrollLeft += item.left - box.left - (box.width - item.width) / 2;
    }
  }
  markRailEdges();
}

function markRailEdges() {
  const scrollable = rail.scrollWidth > rail.clientWidth + 1;
  rail.toggleAttribute("data-more-start", scrollable && rail.scrollLeft > 1);
  rail.toggleAttribute("data-more-end", scrollable && rail.scrollLeft + rail.clientWidth < rail.scrollWidth - 1);
}

function syncLinks() {
  for (const link of links) {
    link.parentElement.hidden = Boolean(document.getElementById(link.dataset.section)?.hidden);
  }
}

/** Show the section that holds `id` (or the first one); `focus` moves the keyboard to its heading. */
function show(id, { focus = false } = {}) {
  const wanted = sectionFor(id);
  const section = wanted && !wanted.hidden ? wanted : firstAvailable();
  active = section;
  main.dataset.view = "section";
  for (const each of sections) {
    each.toggleAttribute("data-active", each === section);
  }
  for (const link of links) {
    if (section && link.dataset.section === section.id) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  }
  if (!section) {
    return;
  }
  revealInRail(links.find(link => link.dataset.section === section.id));
  const target = document.getElementById(id);
  if (target && target !== section && section.contains(target)) {
    target.scrollIntoView({ block: "start" });
  } else {
    window.scrollTo(0, 0);
  }
  if (focus) {
    const heading = section.querySelector(".section__title");
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
  }
}

function filter() {
  const query = search.value.trim();
  if (!query) {
    results.hidden = true;
    results.textContent = "";
    for (const item of main.querySelectorAll("[data-miss]")) {
      item.removeAttribute("data-miss");
    }
    show(location.hash.slice(1));
    return;
  }
  const words = fold(query).split(/\s+/);
  const matches = text => words.every(word => text.includes(word));
  let found = 0;
  main.dataset.view = "search";
  for (const link of links) {
    link.removeAttribute("aria-current"); // the results span sections; none is "the" open one
  }
  for (const section of sections) {
    let any = false;
    if (!section.hidden) {
      const title = fold(section.querySelector(".section__title").textContent);
      for (const item of section.querySelectorAll(":scope > :not(.section__head)")) {
        const hit = !item.hidden && (matches(title) || matches(fold(`${title} ${item.textContent}`)));
        item.toggleAttribute("data-miss", !hit);
        any ||= hit;
        found += hit ? 1 : 0;
      }
    }
    section.toggleAttribute("data-match", any);
  }
  results.hidden = false;
  results.textContent = found ? t("settingsSearchFound", [String(found)]) : t("settingsSearchNone", [query]);
}

export function setUpNav() {
  syncLinks();
  show(location.hash.slice(1));
  // A section becomes available after its feature answers: offer it, and show it if it was asked for.
  const sectionsChanged = new MutationObserver(() => {
    syncLinks();
    const wanted = sectionFor(location.hash.slice(1));
    const next = wanted && !wanted.hidden ? wanted : firstAvailable();
    if (main.dataset.view !== "search" && next !== active) {
      show(location.hash.slice(1));
    }
  });
  for (const section of sections) {
    sectionsChanged.observe(section, { attributes: true, attributeFilter: ["hidden"] });
  }
  // While searching, rows that arrive later (a slow check, a re-render) are filtered too.
  // (The result count, the status line and the inline confirmations are not content.)
  let late = null;
  const notContent = node => node.nodeType !== Node.ELEMENT_NODE || node.matches(".inline-status");
  const content = record =>
    !record.target.closest?.("#settings-results, #status") &&
    !(record.type === "childList" && [...record.addedNodes, ...record.removedNodes].every(notContent));
  new MutationObserver(records => {
    if (main.dataset.view === "search" && records.some(content)) {
      clearTimeout(late);
      late = setTimeout(filter, 150);
    }
  }).observe(main, { subtree: true, childList: true, attributes: true, attributeFilter: ["hidden"] });
  window.addEventListener("hashchange", () => {
    search.value = "";
    filter();
    show(location.hash.slice(1), { focus: true });
  });
  // The same address again (the link of the open section) still brings its heading to the keyboard.
  for (const link of links) {
    link.addEventListener("click", () => {
      if (link.getAttribute("href") === location.hash && main.dataset.view === "section") {
        show(link.dataset.section, { focus: true });
      } else if (search.value) {
        search.value = "";
        filter();
      }
    });
  }
  rail.addEventListener("scroll", markRailEdges, { passive: true });
  window.addEventListener("resize", () => revealInRail(links.find(link => link.hasAttribute("aria-current"))));
  let timer = null;
  search.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(filter, 120);
  });
  search.addEventListener("keydown", event => {
    if (event.key === "Escape" && search.value) {
      event.preventDefault();
      search.value = "";
      filter();
    }
  });
}
