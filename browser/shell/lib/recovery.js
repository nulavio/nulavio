/* The recovery-code ceremony (UX4, audit SB-08), shared by vault/create.html and
   vault/methods.html. A recovery code is shown once: as 7 numbered groups (read group by group,
   letter by letter), with "Print" (only the code is printed), and the page asks before it is left
   while the code was not confirmed. Nulavio writes no copy anywhere: not to the clipboard (ADR
   0006) and not to a file (the guardrail against secrets in plain text on disk), so there is no
   "save to a file"; paper, or the person's own password manager, keeps it. */

import { t } from "./i18n.js";
import { h } from "./ui.js";

/** Fill `list` (an <ol>) with the code's groups; `list.dataset.code` keeps the code for typing back. */
export function showCode(list, code) {
  const groups = String(code).split("-");
  list.dataset.code = code;
  list.replaceChildren(
    ...groups.map((group, index) =>
      h(
        "li",
        { class: "code-grid__group" },
        h("span", { class: "code-grid__n", "aria-hidden": "true", text: String(index + 1) }),
        h("span", { class: "code-grid__value mono", "aria-hidden": "true", text: group }),
        h("span", { class: "visually-hidden", text: t("vaultCodeGroupSpoken", [String(index + 1), [...group].join(" ")]) })
      )
    )
  );
}

export function clearCode(list) {
  delete list.dataset.code;
  list.replaceChildren();
}

/** Print only the code (print.css hides everything else while body[data-printing]). */
export function printCode() {
  document.body.dataset.printing = "code";
  window.addEventListener("afterprint", () => delete document.body.dataset.printing, { once: true });
  window.print();
}

/** While `pending()` is true, leaving the page asks first (the code would be lost). */
export function guardLeaving(pending) {
  window.addEventListener("beforeunload", event => {
    if (pending()) {
      event.preventDefault();
    }
  });
}
