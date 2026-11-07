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
