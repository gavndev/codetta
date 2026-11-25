// ---- Album art, full size ------------------------------------------------------------------------------
//
// Tapping a cover (the album page's header, the tag editor's art) opens it at its full quality and
// own shape, as big as the screen allows. X, Escape, a tap outside it or Back closes it.

import { closeDialog, h, icon, openDialog } from "./dom.js";

let dialog = null;

function make() {
  dialog = h("dialog", { class: "cover-view", "aria-label": "Album art" });
  dialog.addEventListener("click", (e) => {
    if (e.target === dialog || e.target.closest("[data-close]") || e.target.classList.contains("cover-view-stage")) closeDialog(dialog);
  });
  dialog.addEventListener("cancel", (e) => { e.preventDefault(); closeDialog(dialog); });
  document.body.append(dialog);
}

/** Show ``src`` (the full-size image) with an optional line under it, such as "3400 × 3000". */
export function openCoverView(src, { caption = "", title = "" } = {}) {
  if (!src) return;
  if (!dialog) make();
  const img = h("img", { class: "cover-view-img", src, alt: title ? `Album art: ${title}` : "Album art", decoding: "async" });
  const wait = h("span", { class: "spinner cover-view-wait", "aria-hidden": "true" });
  img.addEventListener("load", () => { wait.remove(); img.classList.add("loaded"); }, { once: true });
  img.addEventListener("error", () => { wait.remove(); img.replaceWith(h("p", { class: "cover-view-error" }, "This cover couldn't be loaded.")); }, { once: true });
  dialog.replaceChildren(
    h("button", { class: "icon-btn cover-view-close", type: "button", "data-close": true, "aria-label": "Close" }, icon("close")),
    h("div", { class: "cover-view-stage" }, wait, img,
      caption || title ? h("p", { class: "cover-view-cap" },
        title ? h("span", { dir: "auto" }, title) : null, caption ? h("span", {}, caption) : null) : null));
  openDialog(dialog);
}
