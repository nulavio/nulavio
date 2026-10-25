/* Fill [data-i18n] text and [data-i18n-attr="attr:key"] attributes from
   _locales. Text is set with textContent, never innerHTML. */

export function t(key, substitutions) {
  return browser.i18n.getMessage(key, substitutions) || key;
}

export function localize(root = document) {
  document.documentElement.lang = browser.i18n.getUILanguage();
  for (const el of root.querySelectorAll("[data-i18n]")) {
    el.textContent = t(el.dataset.i18n);
  }
  for (const el of root.querySelectorAll("[data-i18n-attr]")) {
    for (const pair of el.dataset.i18nAttr.split(";")) {
      const [attr, key] = pair.split(":");
      el.setAttribute(attr.trim(), t(key.trim()));
    }
  }
}
