(() => {
  const CMD = "npx skills add https://github.com/Ivor-NCUT/genius-career-advisor-skill --skill '*' -g -a grok -a cursor -a codex -a claude-code -y";

  /* ---------- Copy ---------- */
  async function writeClipboard(text) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
  }
  async function copyCommand(btn) {
    await writeClipboard(CMD);
    const targets = [btn, ...document.querySelectorAll("[data-copy]")].filter(Boolean);
    targets.forEach((el) => {
      el.classList.add("is-copied");
      if (el.matches(".composer-btn")) {
        const label = el.querySelector(".composer-btn-label");
        if (label) label.textContent = "copied";
      } else if (el.matches(".nav-cta")) {
        el.textContent = "copied";
      }
    });
    clearTimeout(copyCommand._t);
    copyCommand._t = setTimeout(() => {
      targets.forEach((el) => {
        el.classList.remove("is-copied");
        if (el.matches(".composer-btn")) {
          const label = el.querySelector(".composer-btn-label");
          if (label) label.textContent = "Copy";
        } else if (el.matches(".nav-cta")) {
          el.textContent = "Copy";
        }
      });
    }, 1800);
  }
  document.querySelectorAll("[data-copy]").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.preventDefault();
      copyCommand(el);
    });
  });
  document.querySelectorAll("[data-copy-wechat]").forEach((el) => {
    el.addEventListener("click", async () => {
      await writeClipboard("FH01xy");
      const prev = el.textContent;
      el.textContent = "copied";
      clearTimeout(el._t);
      el._t = setTimeout(() => { el.textContent = prev; }, 1800);
    });
  });

  /* ---------- Install command typewriter ---------- */
  const DISPLAY_CMD = "npx skills add Ivor-NCUT/genius-career-advisor-skill ...";
  const typedEl = document.querySelector(".composer-typed");
  if (typedEl) {
    const text = DISPLAY_CMD.replace("\\n", "\n");
    let i = 0;
    const tick = () => {
      if (i <= text.length) {
        typedEl.textContent = text.slice(0, i);
        i += 1;
        const ch = text[i - 2];
        const delay = ch === "\n" ? 280 : ch === " " ? 36 : 28;
        setTimeout(tick, delay);
      }
    };
    setTimeout(tick, 400);
  }

  /* ---------- Sticky header ---------- */
  const nav = document.getElementById("nav-bar");
  const hero = document.getElementById("hero");
  const onScrollNav = () => {
    const threshold = 12;
    nav.toggleAttribute("data-scrolled", window.scrollY > threshold);
  };
  onScrollNav();
  window.addEventListener("scroll", onScrollNav, { passive: true });

  /* ---------- Composer docking ---------- */
  const composer = document.getElementById("composer");
  const heroSlot = document.getElementById("hero-slot");
  const finalSlot = document.getElementById("final-slot");
  let mode = "hero";

  function currentSlotRect() {
    if (mode === "final") return finalSlot.getBoundingClientRect();
    if (mode === "hero") return heroSlot.getBoundingClientRect();
    return composer.getBoundingClientRect();
  }

  function flipTo(next) {
    if (next === mode) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const first = composer.getBoundingClientRect();

    if (next === "hero") {
      heroSlot.appendChild(composer);
      composer.dataset.position = "hero";
    } else if (next === "final") {
      finalSlot.appendChild(composer);
      composer.dataset.position = "final";
    } else {
      document.body.appendChild(composer);
      composer.dataset.position = "dock";
    }
    mode = next;

    if (reduce) return;
    const last = composer.getBoundingClientRect();
    const dx = first.left - last.left;
    const dy = first.top - last.top;
    const sx = first.width / Math.max(last.width, 1);
    const sy = first.height / Math.max(last.height, 1);
    if (Math.abs(dx) < 1 && Math.abs(dy) < 1 && Math.abs(sx - 1) < 0.02) return;
    composer.animate(
      [
        { transform: `translate(${dx}px, ${dy}px) scale(${sx}, ${sy})` },
        { transform: "none" },
      ],
      { duration: 520, easing: "cubic-bezier(.16, 1, .3, 1)" }
    );
  }

  function placeComposer() {
    const heroRect = heroSlot.getBoundingClientRect();
    const finalRect = finalSlot.getBoundingClientRect();
    const vh = window.innerHeight;
    const navH = (nav && nav.offsetHeight) || 64;
    const dockY = vh - 20 - 70;

    // Stay in the hero while its slot is still below the header.
    // Pin to the bottom after the in-flow composer has scrolled up to the header.
    // Once the final slot has risen to the dock line, attach there and let it
    // leave the viewport with that section (do not re-dock over the footer).
    if (heroRect.top >= navH + 8) flipTo("hero");
    else if (finalRect.top <= dockY + 8) flipTo("final");
    else flipTo("dock");
  }
  window.addEventListener("scroll", placeComposer, { passive: true });
  window.addEventListener("resize", placeComposer);
  placeComposer();

  /* ---------- How-it-helps step loop ---------- */
  const how = document.getElementById("how");
  const steps = [...how.querySelectorAll(".step")];
  // 0–3.2s 01, 3.2–6.5s 02, 6.5–10.0s 03, 10.0–10.5s fade/reset
  const TIMING = [
    { at: 0, index: 0 },
    { at: 3200, index: 1 },
    { at: 6500, index: 2 },
    { at: 10000, index: -1 },
  ];
  const CYCLE = 10500;
  let started = 0;
  let raf = 0;
  let playing = false;

  function applyStep(index, fading) {
    steps.forEach((s, i) => s.dataset.active = i === index ? "true" : "false");
    how.dataset.fading = fading ? "true" : "false";
  }

  function tick(now) {
    if (!playing) return;
    const t = (now - started) % CYCLE;
    let index = 0;
    let fading = false;
    if (t >= 10000) {
      index = -1;
      fading = true;
    } else if (t >= 6500) index = 2;
    else if (t >= 3200) index = 1;
    else index = 0;
    applyStep(index, fading);
    raf = requestAnimationFrame(tick);
  }

  const howObs = new IntersectionObserver((entries) => {
    const vis = entries.some((e) => e.isIntersecting);
    if (vis && !playing) {
      playing = true;
      started = performance.now();
      raf = requestAnimationFrame(tick);
    } else if (!vis && playing) {
      playing = false;
      cancelAnimationFrame(raf);
    }
  }, { threshold: 0.35 });
  howObs.observe(how);

  /* ---------- Profile tabs ---------- */
  const personal = {
    title: "个人档案 · 示例",
    who: '求职者本人 <span>示例</span>',
    foot: "由对话逐步沉淀",
    body: `<dl>
      <div><dt>称呼</dt><dd>示例：小陈</dd></div>
      <div><dt>经历摘要</dt><dd>两段实习，做过产品调研与协助落地。具体项目和职责以本人确认后的表述为准。</dd></div>
      <div><dt>求职方向</dt><dd>面向 AI 行业岗位，按即将投出的 JD 准备材料。</dd></div>
      <div><dt>使用约定</dt><dd>没有本人点头，<mark>不会写进档案</mark>，也不会拿去投递。</dd></div>
    </dl>`,
  };
  const agent = {
    title: "Agent 档案 · 示例",
    who: '给 Agent 用的上下文 <span>示例</span>',
    foot: "随每次确认一起变完整",
    body: `<dl>
      <div><dt>已确认事实</dt><dd>只收录本人点头过的经历，避免把做过的事写成另一件事。</dd></div>
      <div><dt>岗位偏好</dt><dd>示例：优先 AI 应用、产品或增长相关岗位；具体意向以本人最新确认为准。</dd></div>
      <div><dt>改简历时要注意</dt><dd>改了什么要能看出来；<mark>没核实的不编进去</mark>。</dd></div>
      <div><dt>面试时怎么用</dt><dd>对着这份档案准备讲法，保证改完还认得、面试能讲圆。</dd></div>
    </dl>`,
  };

  const tabPersonal = document.getElementById("tab-personal");
  const tabAgent = document.getElementById("tab-agent");
  const dossierTitle = document.getElementById("dossier-title");
  const dossierWho = document.getElementById("dossier-who");
  const dossierBody = document.getElementById("dossier-body");
  const dossierFoot = document.getElementById("dossier-foot");

  function showProfile(which) {
    const data = which === "agent" ? agent : personal;
    tabPersonal.setAttribute("aria-pressed", which === "personal" ? "true" : "false");
    tabAgent.setAttribute("aria-pressed", which === "agent" ? "true" : "false");
    tabPersonal.setAttribute("aria-selected", which === "personal" ? "true" : "false");
    tabAgent.setAttribute("aria-selected", which === "agent" ? "true" : "false");
    dossierTitle.textContent = data.title;
    dossierWho.innerHTML = data.who;
    dossierFoot.textContent = data.foot;
    dossierBody.innerHTML = data.body;
    dossierBody.style.animation = "none";
    void dossierBody.offsetWidth;
    dossierBody.style.animation = "";
  }
  tabPersonal.addEventListener("click", () => showProfile("personal"));
  tabAgent.addEventListener("click", () => showProfile("agent"));

  /* ---------- Final icon arc ---------- */
  function layoutArc() {
    const arc = document.getElementById("final-arc");
    const items = [...arc.querySelectorAll(".channel")];
    const path = document.getElementById("arc-path");
    if (!items.length || !path) return;
    const w = Math.max(arc.clientWidth || 0, 320);
    const h = Math.max(arc.clientHeight || 0, 180);
    const padX = Math.max(36, w * 0.07);
    const yEnd = 52;
    const yCtrl = 168; // control point for a shallow smile
    const d = `M ${padX} ${yEnd} Q ${w / 2} ${yCtrl} ${w - padX} ${yEnd}`;
    path.setAttribute("d", d);
    path.closest("svg").setAttribute("viewBox", `0 0 ${w} ${h}`);

    items.forEach((el, i) => {
      const t = items.length === 1 ? 0.5 : i / (items.length - 1);
      const x = padX + t * (w - padX * 2);
      const y = (1 - t) * (1 - t) * yEnd + 2 * (1 - t) * t * yCtrl + t * t * yEnd;
      const r = (t - 0.5) * 20;
      el.style.setProperty("--x", `${x}px`);
      el.style.setProperty("--y", `${y}px`);
      el.style.setProperty("--r", `${r}deg`);
    });
  }
  layoutArc();
  window.addEventListener("resize", layoutArc);

  /* Kick channel pop-in shortly after load */
  requestAnimationFrame(() => {
    document.querySelectorAll(".channel-in").forEach((n) => {
      n.parentElement.parentElement.classList.add("channels-ready");
    });
    document.getElementById("hero-channels")?.classList.add("channels-ready");
    document.getElementById("final-arc")?.classList.add("channels-ready");
  });
})();
