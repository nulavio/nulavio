/* Password managers (flow B): the name and the real state of each one, said the same way in Settings
   and in the first run. `item` is one entry of browser.nulavioPasswords.state().providers. */

import { t } from "./i18n.js";

export function providerName(item) {
  return item.key === "builtin" ? t("passwordsBuiltin") : item.extension.name;
}

export function providerStatus(item) {
  if (item.key === "builtin") {
    return t("passwordsBuiltinNote");
  }
  const ext = item.extension;
  const parts = [
    ext.enabled
      ? t("passwordsInstalled", [ext.version])
      : ext.installed
        ? t("passwordsInstalledOff")
        : t("passwordsNotInstalled", [ext.pinned]),
  ];
  if (item.native && !item.native.found) {
    parts.push(t(item.native.required ? "passwordsNativeMissing" : "passwordsNativeOptional"));
  }
  return parts.join(" ");
}
