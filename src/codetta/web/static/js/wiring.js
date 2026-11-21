// Wiring: connecting the page's buttons, keys and gestures to what they do.
// Part of Codetta's page; app.js is the entry point (see the note at its top).

import { $, closeDialog } from "./dom.js";
import { els, plural, state, toast } from "./state.js";
import { getTheme, setTheme, THEME_LABEL, THEMES } from "./theme.js";
import {
  addTagFilter, folderLinkPath, hashFor, isSearch, loadFolder, navigate, onHistoryChange, openTagFilter,
  prefetchFolder, renderFilterChips, renderSelectionBar, SEARCH, searchQuery, updateRowStates,
} from "./browse.js";
import { bang, BANGS, iconButton, renderBangSuggestions, setBang, syncRoll, takeBang } from "./search.js";
import {
  openActions, openReplace, openToolsMenu, renderFolders, renderTracks,
} from "./tools.js";
import {
  closeEditor, fieldLabel, isDirty, loadClipboard, openEditor, pollLog, renderToolbar, saveEditor,
  saveToFolder, setAdvanced, stopLogPolling, syncLogTile,
} from "./editor.js";
import { activity, renderActivity } from "./activity.js";
import { doApply, openApply, openManage, runPreview, syncApplyUi } from "./presets.js";
import { openEditionPrefs } from "./musicbrainz.js";
import { chooseCare, setHealthEnabled } from "./library.js";
import { placeAccount, setPasswordOpen, syncAccountTiles } from "./account.js";
import { openReport, openTrash, setupContextMenu, setupDropImport } from "./files.js";

// ---- Wiring -------------------------------------------------------------------------------------------------------

export function bindEvents() {
  window.addEventListener("popstate", onHistoryChange);
  window.addEventListener("hashchange", onHistoryChange); // hand-typed URLs
  document.addEventListener("click", (e) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const path = folderLinkPath(e);
    if (path == null) return;
    e.preventDefault();
    navigate(path);
  });
  document.addEventListener("pointerdown", (e) => prefetchFolder(folderLinkPath(e)), { passive: true });
  document.addEventListener("pointerover", (e) => { if (e.pointerType === "mouse") prefetchFolder(folderLinkPath(e)); }, { passive: true });
  window.addEventListener("beforeunload", (e) => { if (isDirty()) { e.preventDefault(); e.returnValue = ""; } });

  $("#theme-btn").addEventListener("click", () => {
    const next = THEMES[(THEMES.indexOf(getTheme()) + 1) % THEMES.length];
    setTheme(next);
    toast(THEME_LABEL[next]);
  });

  let filterTimer = null;
  els.filter.addEventListener("input", () => {
    clearTimeout(filterTimer); // redraw once typing pauses, not on every keystroke
    if (bang.kind && /^\s/.test(els.filter.value)) els.filter.value = els.filter.value.trimStart(); // the space after "!mb"
    syncRoll();
    renderBangSuggestions();
    if (takeBang() || bang.kind || els.filter.value.startsWith("!")) return; // a bang search, not a filter
    if (isSearch()) {
      // While searching, the box *is* the search: re-run it as you type.
      filterTimer = setTimeout(() => {
        const q = els.filter.value.trim();
        if (!q || q === searchQuery()) return;
        history.replaceState({ path: SEARCH + q }, "", hashFor(SEARCH + q));
        loadFolder(SEARCH + q);
      }, 350);
      return;
    }
    filterTimer = setTimeout(() => {
      state.filter = els.filter.value.trim();
      renderFolders();
      renderTracks();
      renderFilterChips();
    }, 120);
  });
  els.filter.addEventListener("keydown", (e) => {
    if (bang.kind) {
      if (e.key === "Enter") { e.preventDefault(); BANGS[bang.kind].run(els.filter.value); }
      else if (e.key === "Backspace" && !els.filter.value) { e.preventDefault(); setBang(false); }
      else if (e.key === "Escape") { els.filter.value = ""; setBang(false); }
      return;
    }
    if (e.key !== "Enter") return;
    const q = els.filter.value.trim();
    if (q && !isSearch()) { e.preventDefault(); clearTimeout(filterTimer); navigate(SEARCH + q); }
  });
  els.filter.addEventListener("search", () => { // the ✕ in the search box
    if (bang.kind && !els.filter.value) { setBang(false); return; }
    if (isSearch() && !els.filter.value) navigate("");
  });

  $("#editor-close").addEventListener("click", () => closeEditor());
  $("#activity-toggle").addEventListener("click", () => {
    activity.open = !activity.open;
    try { localStorage.setItem("codetta-activity-open", activity.open ? "1" : "0"); } catch { /* ignore */ }
    renderActivity();
  });
  els.editorSave.addEventListener("click", () => saveEditor());
  els.editorSaveFolder.addEventListener("click", saveToFolder);
  $("#tagfilter-btn").addEventListener("click", openTagFilter);
  $("#filter-add").addEventListener("click", addTagFilter);
  $("#filter-search").addEventListener("click", () => {
    const key = $("#filter-key").value, value = $("#filter-value").value;
    if (!key || !value) { toast("Pick a value to search for"); return; }
    closeDialog(els.filterDialog);
    navigate(`${SEARCH}${fieldLabel(key)}: ${value}`);
  });
  els.editorForm.addEventListener("submit", (e) => { e.preventDefault(); saveEditor(); });
  // Keep "Copy tags" / "Paste" in sync when tags are copied in another tab.
  window.addEventListener("storage", (e) => {
    if (e.key === "codetta-clipboard") { state.clipboard = loadClipboard(); if (state.editor) renderToolbar(); }
  });

  setupContextMenu();
  setupDropImport();
  $("#editions-toggle").addEventListener("click", () => { closeDialog($("#account-dialog")); setTimeout(openEditionPrefs, 250); });
  $("#report-toggle").addEventListener("click", () => { closeDialog($("#account-dialog")); setTimeout(openReport, 250); });
  $("#trash-toggle").addEventListener("click", () => { closeDialog($("#account-dialog")); setTimeout(openTrash, 250); });
  $("#care-toggle").addEventListener("click", () => { closeDialog($("#account-dialog")); setTimeout(chooseCare, 250); });
  $("#log-tile").addEventListener("toggle", () => { if ($("#log-tile").open) pollLog(); else stopLogPolling(); });
  $("#account-dialog").addEventListener("close", stopLogPolling);
  syncLogTile();
  $("#sel-clear").addEventListener("click", () => { state.selected.clear(); updateRowStates(); renderSelectionBar(); });
  $("#sel-edit").addEventListener("click", () => openEditor([...state.selected]));
  $("#sel-preset").addEventListener("click", () => openApply("selection"));
  $("#sel-actions").addEventListener("click", () => openActions({ paths: [...state.selected] }, `${plural(state.selected.size, "selected track")}`));
  $("#sel-replace").addEventListener("click", () => openReplace({ paths: [...state.selected] }, `${plural(state.selected.size, "selected track")}`));
  // Phones: the bar can't fit five buttons, so Preset, Replace and Actions share a "…" menu.
  const selMore = iconButton("more", "More", () => openToolsMenu(selMore, [
    { icon: "preset", label: "Apply preset", run: () => $("#sel-preset").click() },
    { icon: "replace", label: "Find & replace", run: () => $("#sel-replace").click() },
    { icon: "wand", label: "Actions", run: () => $("#sel-actions").click() },
  ]), { cls: "sel-more phone-only" });
  selMore.id = "sel-more";
  $("#sel-edit").before(selMore);
  $("#manage-btn").addEventListener("click", openManage);
  $("#cc-theme").addEventListener("click", () => { $("#theme-btn").click(); syncAccountTiles(); });
  $("#pw-toggle").addEventListener("click", () => setPasswordOpen($("#password-form").hidden));
  window.addEventListener("resize", () => { if ($("#account-dialog").open) placeAccount(); });
  const healthToggle = $("#health-toggle");
  healthToggle.addEventListener("change", async () => {
    healthToggle.disabled = true;
    try {
      await setHealthEnabled(healthToggle.checked);
      toast(healthToggle.checked ? "Library health on" : "Library health off");
    } catch (err) { healthToggle.checked = !healthToggle.checked; toast(err.message, "error"); }
    finally { healthToggle.disabled = false; }
  });
  const adv = $("#advanced-toggle");
  adv.checked = state.advanced;
  adv.addEventListener("change", () => { setAdvanced(adv.checked); toast(adv.checked ? "Advanced mode on" : "Advanced mode off"); });

  // Apply dialog
  const d = els.applyDialog;
  d.addEventListener("change", () => { syncApplyUi(); runPreview(); });
  $("#apply-go").addEventListener("click", doApply);

  // All dialogs: close buttons and backdrop clicks.
  for (const dialog of [els.applyDialog, els.manageDialog, els.filterDialog, $("#mb-dialog"), $("#organize-dialog"), $("#inbox-dialog"), $("#soulseek-dialog"), $("#health-dialog"), $("#player-dialog"), $("#replace-dialog"), $("#actions-dialog"), $("#news-dialog")]) {
    dialog.addEventListener("click", (e) => {
      if (e.target.closest("[data-close]") || e.target === dialog) closeDialog(dialog);
    });
    // Escape: animate out instead of vanishing.
    dialog.addEventListener("cancel", (e) => { e.preventDefault(); closeDialog(dialog); });
  }

  document.addEventListener("keydown", (e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === "s" && state.editor) {
      e.preventDefault();
      saveEditor();
    } else if (e.key === "Escape" && state.editor && !document.querySelector("dialog[open]")) {
      closeEditor();
    } else if (e.key === "/" && !e.target.closest("input, textarea, select, [contenteditable]") && !document.querySelector("dialog[open]")) {
      e.preventDefault();
      els.filter.focus();
    }
  });
}
