// Codetta's website: the install panel, and the scenes. Every scene runs on one shared clock
// (a beat of 600 ms), so steps land together instead of each effect keeping its own time.
(() => {
  "use strict";
  document.documentElement.classList.add("js");
  // Reduced motion (or ?still, for screenshots): every scene shows its finished state at once.
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches || /[?&]still\b/.test(location.search);
  const BEAT = 600;
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const wait = (beats) => new Promise((r) => setTimeout(r, calm ? 0 : beats * BEAT));

  // ---- Install: tabs and copy ------------------------------------------------------------
  const INSTALL = {
    docker: {
      cmd: 'docker run -d --name codetta -p 8111:8111 -v <mark>/path/to/music</mark>:/music -v codetta-config:/config ghcr.io/gavndev/codetta:latest',
      hint: 'Swap in your music folder, then open <b>http://your-server:8111</b>. Prefer Compose? See the <a href="https://github.com/gavndev/codetta/blob/main/docs/install.md">install guide</a>.',
    },
    pipx: {
      cmd: "pipx install codetta && codetta",
      hint: 'On your own computer (Python 3.14). It opens Codetta in your browser. <a href="https://github.com/gavndev/codetta/blob/main/docs/install.md#on-your-own-computer">More</a>',
    },
    snap: {
      cmd: "sudo snap install codetta",
      hint: 'Ubuntu and other Linux. Snaps update themselves. <a href="https://snapcraft.io/codetta">Snap Store</a>',
    },
  };
  for (const box of $$("[data-install]")) {
    const code = $("[data-cmd]", box), hint = $("[data-hint]", box), copy = $("[data-copy]", box);
    const tabs = $$('[role="tab"]', box);
    const show = (key) => {
      code.innerHTML = INSTALL[key].cmd;
      hint.innerHTML = INSTALL[key].hint;
      for (const t of tabs) {
        const on = t.dataset.tab === key;
        t.setAttribute("aria-selected", String(on));
        t.tabIndex = on ? 0 : -1;
      }
    };
    tabs.forEach((t, i) => {
      t.addEventListener("click", () => show(t.dataset.tab));
      t.addEventListener("keydown", (e) => {
        if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
        const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
        next.focus(); show(next.dataset.tab);
      });
    });
    copy.addEventListener("click", async () => {
      const text = code.textContent;
      try { await navigator.clipboard.writeText(text); }
      catch { // older browsers, or a page not served over https
        const r = document.createRange(); r.selectNodeContents(code);
        const s = getSelection(); s.removeAllRanges(); s.addRange(r);
        try { document.execCommand("copy"); } catch { /* the text is selected for the visitor to copy */ }
      }
      copy.textContent = "Copied"; copy.classList.add("done");
      clearTimeout(copy.t);
      copy.t = setTimeout(() => { copy.textContent = "Copy"; copy.classList.remove("done"); }, 1800);
    });
    show("docker");
  }

  // ---- The hero: one download's journey ------------------------------------------------------
  const ALBUMS = [
    ["glass-garden", "Glass Garden", "Marisol Vega · 2025"], ["northern-signal", "Northern Signal", "Kōsei Mori · 2021"],
    ["coastline", "Coastline", "Mira Sol · 2023"], ["low-tide", "Low Tide", "Harbor Lights · 2020"],
    ["midnight-tapes", "Midnight Tapes", "Nightfall Collective · 2024"], ["low-orbit", "Low Orbit", "Maren Holt · 2019"],
    ["fieldwork", "Fieldwork", "Ines Calder · 2018"], ["slow-bloom", "Slow Bloom", "The Quiet Hours · 2022"],
    ["paper-satellites", "Paper Satellites", "Aurora Lane · 2023"], ["sunday-static", "Sunday Static", "Juno Park · 2024"],
    ["afterhours", "Afterhours", "Theo Lindqvist · 2022"], ["ferry-lights", "Ferry Lights", "Oda Saar · 2017"],
  ];
  const stage = $(".stage");
  const wall = $("[data-wall]", stage);
  for (let c = 0; c < 3; c++) {
    const col = document.createElement("div"); col.className = "col";
    for (let r = 0; r < 4; r++) {
      const [slug, title, by] = ALBUMS[c * 4 + r];
      const f = document.createElement("figure");
      if (slug === "low-orbit") f.className = "new";
      const img = document.createElement("img");
      img.src = `covers/${slug}.webp`; img.alt = ""; img.width = 320; img.height = 320; img.loading = "lazy"; img.decoding = "async";
      const cap = document.createElement("figcaption");
      const b = document.createElement("b"); b.textContent = title;
      cap.append(b, by);
      f.append(img, cap); col.append(f);
    }
    wall.append(col);
  }
  // The covers settle in one after another, across the columns, on the clock.
  $$("figure", wall).forEach((f, i) => { f.style.transitionDelay = `${((i % 4) * 3 + Math.floor(i / 4)) * 70}ms`; });

  const steps = $$(".steps li", stage);
  const step = (n) => steps.forEach((li) => li.classList.toggle("on", Number(li.dataset.step) <= n));
  const replay = $("[data-replay]", stage);
  const cover = $(".cover", stage);
  const slot = $(".wall .new", stage);
  let run = 0;

  const reset = () => {
    stage.classList.remove("walled", "handoff", "matched");
    slot.classList.remove("waiting");
    cover.style.visibility = "";
    $$(".in, .fixed", stage).forEach((el) => el.classList.remove("in", "fixed"));
    $("[data-finding] .bar", stage).style.setProperty("--p", "0");
    step(0);
  };
  const showJourneyDone = () => {
    step(3); stage.classList.add("matched");
    $$("[data-file], [data-finding], [data-spread], [data-filed], [data-credits] > div, .cover", stage).forEach((el) => el.classList.add("in"));
    $$("[data-credits] > div", stage).forEach((el) => el.classList.add("fixed"));
    $("[data-finding] .bar", stage).style.setProperty("--p", "1");
  };

  // "Filed": the credits step aside and the cover flies into its own slot in the wall.
  const flyIntoWall = (alive) => new Promise((resolve) => {
    slot.classList.add("waiting");
    stage.classList.add("handoff");
    setTimeout(() => {
      if (!alive()) return resolve();
      const from = cover.getBoundingClientRect();
      stage.classList.add("walled");
      const target = $("img", slot);
      const to = target.getBoundingClientRect();
      const fly = cover.cloneNode();
      fly.className = "flying"; fly.removeAttribute("data-cover");
      Object.assign(fly.style, { left: `${from.left}px`, top: `${from.top}px`, width: `${from.width}px`, height: `${from.height}px` });
      document.body.append(fly);
      cover.style.visibility = "hidden";
      const dx = to.left + to.width / 2 - (from.left + from.width / 2);
      const dy = to.top + to.height / 2 - (from.top + from.height / 2);
      const scale = target.offsetWidth / from.width;
      const anim = fly.animate(
        [{ transform: "none" }, { transform: `translate(${dx}px, ${dy}px) rotate(-6deg) scale(${scale})` }],
        { duration: 1100, easing: "cubic-bezier(0.16, 1, 0.3, 1)", fill: "forwards" });
      anim.onfinish = anim.oncancel = () => { slot.classList.remove("waiting"); fly.remove(); resolve(); };
    }, 420);
  });

  async function journey() {
    const me = ++run;
    const alive = () => me === run;
    reset();
    replay.hidden = true;
    await wait(0.6); if (!alive()) return;
    step(1); $("[data-file]", stage).classList.add("in");
    await wait(1.4); if (!alive()) return;
    $("[data-finding]", stage).classList.add("in");
    await wait(0.4); if (!alive()) return;
    $("[data-finding] .bar", stage).style.setProperty("--p", "1");
    await wait(2); if (!alive()) return;
    // Matched: the cover arrives and lends the stage its colour, as albums do in the app.
    step(2); stage.classList.add("matched");
    $("[data-spread]", stage).classList.add("in"); cover.classList.add("in");
    for (const row of $$("[data-credits] > div", stage)) {
      await wait(0.7); if (!alive()) return;
      row.classList.add("in");
      setTimeout(() => alive() && row.classList.add("fixed"), BEAT * 0.6);
    }
    await wait(1.6); if (!alive()) return;
    step(3); $("[data-filed]", stage).classList.add("in");
    await wait(5); if (!alive()) return;
    await flyIntoWall(alive); if (!alive()) return;
    await wait(1.2); if (!alive()) return;
    replay.textContent = "Play again"; replay.hidden = false;
  }

  if (calm) {
    // Without motion the hero opens settled on the library, the album just filed; the steps are a tap away.
    showJourneyDone(); stage.classList.add("walled");
    replay.hidden = false; replay.textContent = "Show the steps";
    replay.addEventListener("click", () => {
      const walled = stage.classList.toggle("walled");
      replay.textContent = walled ? "Show the steps" : "Show the library";
    });
  } else {
    replay.addEventListener("click", () => journey());
    // Start when the stage is really in view (on phones it sits below the install panel).
    const heroIo = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.intersectionRatio >= 0.4)) { heroIo.disconnect(); journey(); }
    }, { threshold: [0, 0.4] });
    heroIo.observe(stage);
  }

  // ---- Chapters: one pinned stage on wide screens, each scene under its text on phones -------------
  const scenes = {
    async tidy(el, alive) {
      const count = $("[data-count]", el), fixed = $("[data-fixed]", el), bar = $("[data-progress]", el);
      const moves = $$(".moves li", el);
      moves.forEach((li) => li.classList.remove("done"));
      bar.style.setProperty("--w", "0%"); count.textContent = "0 of 48 albums"; fixed.textContent = "0";
      await wait(0.4); if (!alive()) return;
      bar.style.setProperty("--w", "100%");
      const start = performance.now(), dur = calm ? 0 : BEAT * 4;
      const tick = (now) => {
        if (!alive()) return;
        const p = dur ? Math.min(1, (now - start) / dur) : 1;
        const e = 1 - Math.pow(1 - p, 3);
        count.textContent = `${Math.round(48 * e)} of 48 albums`;
        fixed.textContent = String(Math.round(15 * e));
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
      for (const li of moves) { await wait(0.8); if (!alive()) return; li.classList.add("done"); }
    },
    async search(el, alive) {
      const typed = $("[data-typed]", el), bang = $("[data-bang]", el), rows = $$(".results li", el);
      rows.forEach((li) => li.classList.remove("in"));
      bang.hidden = true; typed.textContent = "";
      const type = async (text) => {
        for (const ch of text) { if (!alive()) return false; typed.textContent += ch; await new Promise((r) => setTimeout(r, calm ? 0 : 70)); }
        return true;
      };
      await wait(0.5);
      if (!(await type("!dz"))) return;
      await wait(0.4); if (!alive()) return;
      typed.textContent = ""; bang.hidden = false;
      await wait(0.4);
      if (!(await type("quiet hours"))) return;
      await wait(0.6); if (!alive()) return;
      for (const li of rows) { li.classList.add("in"); await wait(0.3); if (!alive()) return; }
    },
    async undo(el, alive) {
      const entry = $("[data-entry]", el), btn = $("[data-undo]", el);
      entry.classList.remove("undone"); btn.textContent = "Undo"; btn.classList.remove("press");
      await wait(1.6); if (!alive()) return;
      btn.classList.add("press");
      await wait(0.5); if (!alive()) return;
      btn.classList.remove("press"); entry.classList.add("undone"); btn.textContent = "Redo";
    },
    async phone(el, alive) {
      const sheet = $("[data-sheet]", el), genre = $("[data-genre]", el), chip = $(".phone-album em", el);
      sheet.classList.remove("up"); genre.textContent = "Synth-pop"; chip.textContent = "Synth-pop";
      await wait(0.8); if (!alive()) return;
      sheet.classList.add("up");
      await wait(1); if (!alive()) return;
      genre.textContent = "";
      for (const ch of "Dream Pop") { if (!alive()) return; genre.textContent += ch; await new Promise((r) => setTimeout(r, calm ? 0 : 80)); }
      await wait(0.8); if (!alive()) return;
      sheet.classList.remove("up"); chip.textContent = "Dream Pop";
    },
  };

  const chapters = $$(".chapter");
  const pinned = $(".chapter-stage");
  const sceneOf = new Map(chapters.map((ch) => [ch, $(".scene", ch)]));
  const wide = window.matchMedia("(min-width: 1101px)");
  let playing = null; // { scene, token }
  const play = (scene) => {
    if (playing && playing.scene === scene) return;
    const token = Symbol("scene");
    playing = { scene, token };
    const name = [...sceneOf].find(([, sc]) => sc === scene)[0].dataset.scene;
    scenes[name](scene, () => calm || (playing && playing.token === token));
  };
  const activate = (ch) => {
    const scene = sceneOf.get(ch);
    for (const sc of sceneOf.values()) sc.classList.toggle("active", sc === scene);
    play(scene);
  };
  // Wide screens: the chapter crossing the middle of the screen owns the pinned stage.
  const middle = new IntersectionObserver((entries) => {
    if (!wide.matches) return;
    for (const e of entries) if (e.isIntersecting) activate(e.target);
  }, { rootMargin: "-48% 0px -48% 0px" });
  // Phones: each scene plays when it's mostly in view, and again next time.
  const inView = new IntersectionObserver((entries) => {
    if (wide.matches) return;
    for (const e of entries) {
      if (e.intersectionRatio >= 0.5) play(e.target);
      else if (e.intersectionRatio === 0 && playing && playing.scene === e.target) playing = null;
    }
  }, { threshold: [0, 0.5] });
  const place = () => {
    playing = null;
    for (const [ch, sc] of sceneOf) (wide.matches ? pinned : ch).append(sc);
    if (calm) for (const sc of sceneOf.values()) play(sc), playing = null;
  };
  place();
  wide.addEventListener("change", place);
  chapters.forEach((ch) => middle.observe(ch));
  sceneOf.forEach((sc) => inView.observe(sc));
})();
