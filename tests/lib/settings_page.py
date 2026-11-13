"""The one settings page (about:preferences with Nulavio's groups, ADR 0008 and 0011), as tests drive it.

The page is the engine's: its controls are the engine's widgets, read here by their own properties (label,
description, value, pressed) and driven the way a person's action reaches them (a click, a changed value).
Everything runs in the privileged context against the selected tab, so a test opens the page in the session's
own tab: the engine's confirmation prompt is then the one the test driver can answer.
"""

from __future__ import annotations

import time
from pathlib import Path

import harness
from marionette import MarionetteError

DOC = "const d = gBrowser.selectedBrowser.contentDocument; const w = gBrowser.selectedBrowser.contentWindow;"
READY = DOC + 'return d?.documentURI.startsWith("about:") && d.readyState === "complete" && !!d.querySelector("setting-pane");'
# The driver switches tabs without focusing them: the tab it just loaded the page in becomes the selected one.
FRONT = """
const tab = gBrowser.selectedBrowser.currentURI.spec.startsWith("about:preferences")
  ? null : gBrowser.tabs.find(each => each.linkedBrowser.currentURI.spec.startsWith("about:preferences"));
if (tab) gBrowser.selectedTab = tab;
"""
SHOWN = 'const shown = el => !!el && !el.closest("setting-control")?.hidden && el.getBoundingClientRect().height > 0;'
CONTROL = (
    DOC
    + SHOWN
    + """
const el = d.getElementById(arguments[0]);
if (!el) return null;
return { shown: shown(el), label: el.label ?? null, description: el.description ?? null, message: el.message ?? null,
         value: el.value ?? null, pressed: el.pressed ?? null, disabled: Boolean(el.disabled) };
"""
)
ROWS = (
    DOC
    + SHOWN
    + """
const list = d.getElementById(arguments[0]);
if (!shown(list)) return null;
return [...list.querySelectorAll(arguments[1])].map(row => ({
  label: row.label ?? null, description: row.description ?? null, icon: row.iconSrc ?? null, classes: [...row.classList],
  data: { ...row.dataset },
  buttons: [...row.querySelectorAll("moz-button, moz-toggle")].map(b => ({
    action: b.dataset.action ?? null, label: b.label ?? null, named: b.ariaLabel ?? null, disabled: Boolean(b.disabled),
    pressed: b.pressed ?? null,
  })),
}));
"""
)
OPTIONS = (
    DOC
    + """
const el = d.getElementById(arguments[0]);
return el ? [...el.querySelectorAll("moz-option, moz-radio, moz-visual-picker-item")]
  .map(o => [o.value, o.label ?? o.ariaLabel ?? null, Boolean(o.disabled)]) : null;
"""
)
CHANGE = (
    DOC
    + """
const el = d.getElementById(arguments[0]);
if (!el) return false;
el.value = arguments[1];
el.dispatchEvent(new Event("change", { bubbles: true }));
return true;
"""
)
CLICK = DOC + "const el = d.querySelector(arguments[0]); if (!el) return false; el.click(); return true;"
CHOOSE = (
    DOC
    + """
const item = [...d.querySelectorAll(`#${arguments[0]} moz-radio, #${arguments[0]} moz-visual-picker-item`)]
  .find(each => each.value === arguments[1]);
if (!item) return false;
item.click();
return true;
"""
)
ROW_BUTTON = (
    DOC
    + """
const [list, rows, find, action] = arguments;
const row = [...d.querySelectorAll(`#${list} ${rows}`)]
  .find(each => each.label === find || Object.values(each.dataset).includes(find));
const button = row && [...row.querySelectorAll("moz-button, moz-toggle")].find(b => !action || b.dataset.action === action);
if (!button) return false;
button.click();
return true;
"""
)


def open_pane(m, pane: str = "", timeout: float = 20) -> None:
    """Open the settings page at `pane` in the session's own tab, bring that tab to the front and wait for the page's panes."""
    m.navigate(f"about:preferences#{pane}" if pane else "about:preferences")
    m.chrome(FRONT)
    if not harness.wait_until(lambda: m.chrome(READY), timeout):
        raise AssertionError(f"the settings page did not load at #{pane}")


def assistant_pane(m) -> str:
    """The pane that holds the assistant's group: the engine's own AI pane where it shows one, Nulavio's otherwise."""
    return m.chrome('return Services.prefs.getBoolPref("browser.preferences.aiControls", false) ? "ai" : "nulavioAssistant";')


def control(m, element_id: str) -> dict | None:
    """A control as the engine's widget drew it, or None when it is not in the page."""
    return m.chrome(CONTROL, [element_id])


def wait_control(m, element_id: str, wanted=lambda state: state["shown"], timeout: float = 15) -> dict:
    """The control once `wanted` is true of it; fails with what it was otherwise."""
    harness.wait_until(lambda: (state := control(m, element_id)) is not None and wanted(state), timeout)
    state = control(m, element_id)
    if state is None or not wanted(state):
        raise AssertionError(f"#{element_id}: {state}")
    return state


def rows(m, list_id: str, selector: str = "moz-box-item") -> list[dict] | None:
    """The rows of a list, each with its words, data and buttons; None while the list is not shown."""
    return m.chrome(ROWS, [list_id, selector])


def wait_rows(m, list_id: str, wanted, selector: str = "moz-box-item", timeout: float = 15) -> list[dict]:
    harness.wait_until(lambda: (found := rows(m, list_id, selector)) is not None and wanted(found), timeout)
    found = rows(m, list_id, selector)
    if found is None or not wanted(found):
        raise AssertionError(f"#{list_id}: {found}")
    return found


def options(m, element_id: str) -> list | None:
    """[value, words, disabled] of each choice of a select, a radio group or a picker."""
    return m.chrome(OPTIONS, [element_id])


def change(m, element_id: str, value) -> None:
    """What a person does to a field or a select: change its value."""
    if not m.chrome(CHANGE, [element_id, value]):
        raise AssertionError(f"#{element_id} is not in the page")


def choose(m, group_id: str, value: str) -> None:
    """Pick one choice of a radio group or a picker by its value."""
    if not m.chrome(CHOOSE, [group_id, value]):
        raise AssertionError(f"#{group_id} has no choice {value!r}")


def click(m, selector: str) -> None:
    if not m.chrome(CLICK, [selector]):
        raise AssertionError(f"{selector} is not in the page")


def click_row(m, list_id: str, find: str, action: str | None = None, selector: str = "moz-box-item") -> None:
    """Click a row's button: the row is found by its label or by a value of its data, the button by its action."""
    if not m.chrome(ROW_BUTTON, [list_id, selector, find, action]):
        raise AssertionError(f"#{list_id}: no row {find!r} with a button {action!r}")


def shoot(m, folder: Path, name: str) -> None:
    """The page as it is, in the light and the dark theme (the engine's page follows the system's)."""
    try:
        for scheme, dark in (("light", 0), ("dark", 1)):
            m.chrome("Services.prefs.setIntPref('ui.systemUsesDarkTheme', arguments[0]);", [dark])
            time.sleep(0.4)
            (folder / f"{name}-{scheme}.png").write_bytes(m.screenshot_png(full=True))
    finally:
        m.chrome("Services.prefs.clearUserPref('ui.systemUsesDarkTheme');")


def prompt_text(m) -> str | None:
    """The words of the engine's confirmation prompt, or None when none is open."""
    try:
        return m.send("WebDriver:GetAlertText")["value"]
    except MarionetteError:
        return None


def wait_prompt(m, timeout: float = 10) -> str:
    text = harness.wait_until(lambda: prompt_text(m), timeout)
    if not text:
        raise AssertionError("no confirmation was shown")
    return text


def answer_prompt(m, accept: bool) -> None:
    """Accept the prompt, or close it (which is "Cancelar")."""
    m.send("WebDriver:AcceptAlert" if accept else "WebDriver:DismissAlert")
