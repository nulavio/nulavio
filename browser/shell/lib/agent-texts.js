/* Words for a window an agent drives (the bar NulavioAI.markWorkspace shows):
   who drives it, at which level and where (its Área de IA, or one of the
   user's own profiles), plus the raw-automation, stopped and failed states.
   From the Shell's locales only. */

import { t } from "./i18n.js";

/** `target`: { kind: "workspace" | "profile", profile } from nulavioAI.workspaceTarget(). */
export function workspaceBarTexts(name, autonomy, target) {
  const level = autonomy ? t(`aiLevel_${autonomy}`) : "?";
  return {
    text:
      target?.kind === "profile" ? t("aiWorkspaceBarProfile", [name, target.profile ?? "", level]) : t("aiWorkspaceBar", [name, level]),
    rawText: t("aiWorkspaceBarRaw"),
    pausedText: t("aiWorkspaceBarPaused", [name]),
    failedText: t("aiWorkspaceBarStopFailed", [name]),
    stopLabel: t("aiStopAgent"),
  };
}
