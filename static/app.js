// Light/dark toggle: follows the system until the visitor picks; the choice is remembered on this device.
(() => {
  const btn = document.querySelector(".theme-toggle");
  if (!btn) return;
  const root = document.documentElement;
  const sys = matchMedia("(prefers-color-scheme: dark)");
  const sun = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
  const moon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>';
  const dark = () => (root.dataset.theme || (sys.matches ? "dark" : "light")) === "dark";
  const show = () => {
    // the icon shows what you switch to
    btn.innerHTML = dark() ? sun : moon;
    btn.setAttribute("aria-label", dark() ? "Byt till ljust tema" : "Byt till mörkt tema");
  };
  btn.addEventListener("click", () => {
    root.dataset.theme = dark() ? "light" : "dark";
    try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
    show();
  });
  sys.addEventListener("change", show);
  show();
  btn.hidden = false;
})();

// Progressive enhancement: the full list works without JS; this only adds search and department filter.
(() => {
  const form = document.querySelector(".filter");
  if (!form) return;
  form.hidden = false;
  const q = form.querySelector("#q");
  const dept = form.querySelector("#dept");
  const status = form.querySelector(".filter__status");
  const cards = [...document.querySelectorAll(".timeline .card")];
  const days = [...document.querySelectorAll(".timeline .day")];
  const empty = document.querySelector(".timeline .empty");

  const params = new URLSearchParams(location.search);
  q.value = params.get("q") || "";
  dept.value = params.get("dept") || "";

  function apply() {
    const words = q.value.toLowerCase().trim().split(/\s+/).filter(Boolean);
    const d = dept.value;
    let shown = 0;
    for (const c of cards) {
      const ok = words.every((w) => c.dataset.text.includes(w)) && (!d || c.dataset.dept.split("|").includes(d));
      c.hidden = !ok;
      if (ok) shown++;
    }
    for (const day of days) day.hidden = !day.querySelector(".card:not([hidden])");
    empty.hidden = shown > 0;
    status.textContent = words.length || d ? `Visar ${shown} av ${cards.length}.` : "";
    const url = new URL(location.href);
    words.length ? url.searchParams.set("q", q.value) : url.searchParams.delete("q");
    d ? url.searchParams.set("dept", d) : url.searchParams.delete("dept");
    history.replaceState(null, "", url);
  }

  let timer;
  form.addEventListener("submit", (e) => e.preventDefault());
  q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(apply, 200); });
  dept.addEventListener("change", apply);
  if (q.value || dept.value) apply();
})();
