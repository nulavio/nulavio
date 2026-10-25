// Preview chrome theme (opt-out with `nulavio theme off`).
// Applied on every launch while the theme is enabled for the profile.

// @mode enforce
// @category theme
// @why Allow the profile's chrome/userChrome.css (Nulavio colours) to load. CSS cannot run code.
// @tradeoff Upstream calls this a legacy customisation; selectors may need updates on engine upgrades.
user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);
