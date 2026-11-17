// Runs before first paint (loaded in <head>), so the saved theme never flashes.
// Apply the saved theme before first paint, so there's no flash.
try {
  // Carry over settings saved under Codetta's old name ("coda-…").
  for (const k of ["theme", "clipboard", "activity-open"]) {
    const old = localStorage.getItem("coda-" + k);
    if (old !== null && localStorage.getItem("codetta-" + k) === null) localStorage.setItem("codetta-" + k, old);
    localStorage.removeItem("coda-" + k);
  }
  const t = localStorage.getItem("codetta-theme");
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
} catch {}
