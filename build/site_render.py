"""Render lexAhead's static pages, RSS feed and open data from extracted changes."""
import datetime as dt
import difflib
import json
import re
import shutil
from collections import defaultdict
from email.utils import format_datetime
from html import escape
from pathlib import Path

import se

MONTHS = ["januari", "februari", "mars", "april", "maj", "juni", "juli", "augusti", "september",
          "oktober", "november", "december"]
DAYS = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"]
KIND = {"amendment": "Ändring", "enacted": "Ny författning", "repeal": "Upphävs", "unexplained": "Ändring"}
BY = {"riksdagen": "Beslutad av riksdagen", "regeringen": "Beslutad av regeringen"}


def esc(s):
    return escape(str(s or ""), quote=True)


def d(iso):
    return dt.date.fromisoformat(iso)


def long_date(iso, weekday=False):
    x = d(iso)
    s = f"{x.day} {MONTHS[x.month - 1]} {x.year}"
    return f"{DAYS[x.weekday()]} {s}" if weekday else s


def relative(iso, today):
    n = (d(iso) - today).days
    if n == 0:
        return "i dag"
    if n == 1:
        return "i morgon"
    if n > 0:
        return f"om {n} dagar"
    return "i går" if n == -1 else f"för {-n} dagar sedan"


def slug(s):
    return re.sub(r"[^0-9a-z]+", "-", s.lower()).strip("-")


# --- model ---------------------------------------------------------------------------------

def build_model(data, today):
    acts, laws = {}, {}
    for c in data["changes"]:
        key = c["act"] or f"x-{c['id']}"
        a = acts.setdefault(key, {
            "key": key, "sfs": c["act"], "slug": slug(c["act"]) if c["act"] else None,
            "title": c["act_title"] or f"Ändring i {c['law_title']}",
            "by": se.decided_by(c["act_title"]) if c["act"] else None,
            "prep": c["prep"], "changes": []})
        a["changes"].append(c)
        a["prep"] = a["prep"] or c["prep"]
        a["decision"] = a.get("decision") or c.get("decision")
        law = laws.setdefault(c["law"], {"sfs": c["law"], "slug": slug(c["law"]), "title": c["law_title"],
                                         "department": c["department"], "source": c["law_source"], "changes": []})
        law["changes"].append(c)
    for a in acts.values():
        a["changes"].sort(key=lambda c: (c["date"], c["law"]))
        a["dates"] = sorted({c["date"] for c in a["changes"]})
        a["departments"] = sorted({c["department"] for c in a["changes"] if c["department"]})
    for law in laws.values():
        law["changes"].sort(key=lambda c: c["date"])
    # one "departure" per act and date: what the act does that day
    dates = defaultdict(list)
    for a in acts.values():
        for day in a["dates"]:
            dates[day].append({"act": a, "date": day, "changes": [c for c in a["changes"] if c["date"] == day]})
    for deps in dates.values():
        deps.sort(key=lambda x: heading(x).lower())
    upcoming = sorted(x for x in dates if d(x) >= today)
    past = sorted((x for x in dates if d(x) < today), reverse=True)
    return {"acts": acts, "laws": laws, "dates": dict(dates), "upcoming": upcoming, "past": past}


def heading(dep):
    a = dep["act"]
    if a["sfs"]:
        return se.short_title(a["title"])
    return f"Ändring i {se.short_title(dep['changes'][0]['law_title']).lower()}"


def change_summary(c):
    if c["kind"] == "enacted":
        n = sum(1 for u in c["units"] if u["label"].endswith("§"))
        return f"Ny författning med {se.plural(n, 'paragraf', 'paragrafer')}." if n else "Ny författning."
    if c["kind"] == "repeal":
        return "Hela författningen upphör att gälla."
    s = se.summary(c["units"])
    if c["kind"] == "unexplained":
        s += " Registret anger inte vilken författning som beslutat ändringen."
    return s


def act_href(a, c=None):
    return f"forfattning/{a['slug']}/" if a["slug"] else f"lag/{slug(c['law'])}/#{c['id']}"


# --- diff ----------------------------------------------------------------------------------

TOKEN = re.compile(r"\w+|\s+|[^\w\s]")


def blocks(text):
    return [l for l in text.split("\n") if l.strip()]


def word_diff(a, b):
    ta, tb = TOKEN.findall(a), TOKEN.findall(b)
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    if sm.ratio() < 0.35:  # mostly rewritten: show old then new instead of confetti
        return [("-", a), ("+", b)]
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            out.append(("=", "".join(ta[i1:i2])))
            continue
        if i2 > i1:
            out.append(("-", "".join(ta[i1:i2])))
        if j2 > j1:
            out.append(("+", "".join(tb[j1:j2])))
    return out


def diff_blocks(before, after):
    """Paragraph-level diff, word-level inside changed paragraphs: [(kind, [(op, text)])]."""
    a, b = blocks(before), blocks(after)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out += [(x, [("=", x)]) for x in a[i1:i2]]
        elif op == "replace":
            pairs = list(zip(a[i1:i2], b[j1:j2]))
            # the closing "Lag (2025:736)." note is replaced as a whole, not as digit confetti
            out += [(y, [("-", x), ("+", y)] if se.is_note(x) and se.is_note(y) else word_diff(x, y)) for x, y in pairs]
            out += [(x, [("-", x)]) for x in a[i1 + len(pairs):i2]]
            out += [(y, [("+", y)]) for y in b[j1 + len(pairs):j2]]
        else:
            out += [(x, [("-", x)]) for x in a[i1:i2]]
            out += [(y, [("+", y)]) for y in b[j1:j2]]
    return out


def segs_html(segs):
    out = []
    for op, text in segs:
        t = esc(text)
        if op == "-":
            out.append(f'<del><span class="vh">[Tas bort: </span>{t}<span class="vh">]</span></del>')
        elif op == "+":
            out.append(f'<ins><span class="vh">[Läggs till: </span>{t}<span class="vh">]</span></ins>')
        else:
            out.append(t)
    return "".join(out)


def block_html(raw, segs, whole=None):
    line = raw.strip()
    cls = "rubrik" if line.startswith("#") else "not" if se.is_note(line) else "stycke"
    if line.startswith("#"):
        segs = [(op, re.sub(r"^#+\s*", "", t)) for op, t in segs]
    if whole:  # an entirely new or removed paragraf: plain text, the unit label says what happens
        tag = "ins" if whole == "+" else "del"
        return f'<p class="{cls}"><{tag} class="whole">{esc("".join(t for _, t in segs))}</{tag}></p>'
    return f'<p class="{cls}">{segs_html(segs)}</p>'


def unit_html(u, level=3):
    if u["op"] == "added":
        badge, body = "Ny", "".join(block_html(x, [("=", x)], "+") for x in blocks(u["after"]))
    elif u["op"] == "removed":
        badge, body = "Tas bort", "".join(block_html(x, [("=", x)], "-") for x in blocks(u["before"]))
    else:
        badge = "Ändras"
        body = "".join(block_html(raw, segs) for raw, segs in diff_blocks(u["before"], u["after"]))
    return (f'<section class="unit unit--{u["op"]}"><h{level} class="unit__label">{esc(u["label"])} '
            f'<span class="badge badge--{u["op"]}">{badge}</span></h{level}>'
            f'<div class="lagtext">{body}</div></section>')


def change_body(c, level=3):
    units = c["units"]
    if c["kind"] in ("enacted", "repeal"):
        what = "Läs hela texten" if c["kind"] == "enacted" else "Visa texten som upphör"
        return (f'<details class="fulltext"><summary>{what} ({se.plural(len(units), "del", "delar")})</summary>'
                + "".join(unit_html(u, level) for u in units) + "</details>")
    return "".join(unit_html(u, level) for u in units)


LEGEND = ('<p class="legend"><span class="legend__item"><del>genomstruken</del> text tas bort</span> '
          '<span class="legend__item"><ins>understruken</ins> text läggs till</span></p>')


# --- page shell ----------------------------------------------------------------------------

class Site:
    def __init__(self, data, out, base, site_url, today):
        self.data, self.out, self.base, self.today = data, out, base.rstrip("/") + "/", today
        self.site_url = site_url.rstrip("/")
        self.version = data["version"]

    def href(self, path=""):
        return self.base + path

    def abs(self, path=""):
        return self.site_url + self.href(path)

    def write(self, path, html):
        p = self.out / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html, encoding="utf-8")

    def page(self, path, title, body, active=None, description=""):
        nav = [("", "Kommande"), ("lag/", "Lagar"), ("ej-satt-datum/", "Datum ej satt"), ("om/", "Om")]
        cur = ' aria-current="page"'
        links = "".join(f'<li><a href="{self.href(p)}"{cur if p == active else ""}>{t}</a></li>' for p, t in nav)
        v = self.version
        corpus = self.data["corpus"]
        full_title = f"{title} – lexAhead" if title != "lexAhead" else "lexAhead – kommande lagändringar"
        desc = description or "Se vilka lagändringar som riksdagen och regeringen redan har beslutat, och när de börjar gälla."
        self.write(path + "index.html" if path.endswith("/") or not path else path, f"""<!doctype html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(full_title)}</title>
<meta name="description" content="{esc(desc)}">
<meta name="color-scheme" content="light dark">
<link rel="canonical" href="{esc(self.abs(path))}">
<link rel="alternate" type="application/rss+xml" title="lexAhead – kommande lagändringar" href="{self.href('feed.xml')}">
<link rel="preload" href="{self.href('assets/fonts/ibm-plex-sans-latin-400-normal.woff2')}" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{self.href('assets/style.css')}?v={esc(v['version'])}">
<link rel="icon" href="{self.href('assets/icon.svg')}" type="image/svg+xml">
<meta property="og:title" content="{esc(full_title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:locale" content="sv_SE">
<meta name="generator" content="lexAhead {esc(v['version'])}">
</head>
<body>
<a class="skip" href="#innehall">Hoppa till innehållet</a>
<header class="site-header">
  <div class="wrap site-header__inner">
    <a class="wordmark" href="{self.href()}" aria-label="lexAhead, startsida"><span aria-hidden="true">lex<b>Ahead</b><i class="wordmark__arrow">→</i></span></a>
    <nav aria-label="Huvudmeny"><ul class="nav">{links}</ul></nav>
  </div>
</header>
<main id="innehall" tabindex="-1">
{body}
</main>
<footer class="site-footer">
  <div class="wrap">
    <p><strong>Källa: Sveriges riksdag</strong> (<a href="https://data.riksdagen.se/">data.riksdagen.se</a>) och Regeringskansliets
    författningssamling och register (SFST, SFSR), sammanställt av
    <a href="{esc(corpus['repo'])}">lexifina/sweden-law</a>.</p>
    <p>lexAhead är inte en officiell tjänst och ges inte ut av riksdagen eller Regeringskansliet. Kontrollera alltid mot den officiella texten.</p>
    <p class="site-footer__meta">Version {esc(v['version'])} · Data kontrollerad {esc(long_date(corpus['checked_on']) if corpus.get('checked_on') else '–')}
    · <a href="{self.href('feed.xml')}">RSS</a> · <a href="{self.href('data/upcoming.json')}">Öppna data (JSON)</a> · <a href="{self.href('om/#tillganglighet')}">Tillgänglighet</a></p>
  </div>
</footer>
<script src="{self.href('assets/app.js')}?v={esc(v['version'])}" defer></script>
</body>
</html>
""")

    # --- shared fragments ---

    def tags(self, a, changes):
        kinds = {c["kind"] for c in changes}
        k = "repeal" if "repeal" in kinds else "enacted" if "enacted" in kinds else "amendment"
        out = f'<span class="tag tag--{k}">{KIND[k]}</span>'
        if a["by"]:
            out += f'<span class="tag tag--by">{BY[a["by"]]}</span>'
        return out

    def card(self, dep, level=3):
        a, cs = dep["act"], dep["changes"]
        text = " ".join([heading(dep), a["title"]] + [c["law_title"] for c in cs]).lower()
        depts = sorted({c["department"] for c in cs if c["department"]})
        if len(cs) == 1:
            body = f'<p class="card__summary">{esc(change_summary(cs[0]))}</p>'
        else:
            body = '<ul class="card__laws">' + "".join(
                f'<li><span class="card__law">{esc(se.short_title(c["law_title"]))}</span>: {esc(change_summary(c).lower()[:1] + change_summary(c)[1:])}</li>'
                for c in cs) + "</ul>"
        meta = " · ".join([esc(x) for x in depts] + ([f"SFS {esc(a['sfs'])}"] if a["sfs"] else []))
        return (f'<li class="card" data-text="{esc(text)}" data-dept="{esc("|".join(depts))}">'
                f'<div class="card__tags">{self.tags(a, cs)}</div>'
                f'<h{level} class="card__title"><a href="{self.href(act_href(a, cs[0]))}">{esc(heading(dep))}</a></h{level}>'
                f'{body}<p class="card__meta">{meta}</p></li>')

    def day_section(self, day, deps, heading_level=2):
        return (f'<section class="day" id="d-{day}" data-day="{day}" aria-labelledby="h-{day}">'
                f'<div class="day__head"><h{heading_level} id="h-{day}" class="day__date">'
                f'<a href="{self.href(f"datum/{day}/")}">{esc(long_date(day, weekday=True))}</a></h{heading_level}>'
                f'<p class="day__count">{esc(relative(day, self.today))} · {se.plural(len(deps), "författning", "författningar")}</p></div>'
                f'<ul class="cards">{"".join(self.card(x, heading_level + 1) for x in deps)}</ul></section>')

    # --- pages ---

    def index(self, m):
        up = m["upcoming"]
        dates = m["dates"]
        total = len({dep["act"]["key"] for x in up for dep in dates[x]})  # distinct acts, not act×date
        board_rows = "".join(
            f'<tr><th scope="row"><a href="#d-{x}"><span class="board__date">{esc(long_date(x))}</span></a>'
            f'<span class="board__rel">{esc(relative(x, self.today))}</span></th>'
            f'<td class="board__dest">{esc(", ".join(heading(dep) for dep in dates[x][:2]))}'
            f'{f" <span class=board__more>+ {len(dates[x]) - 2} till</span>" if len(dates[x]) > 2 else ""}</td>'
            f'<td class="board__n">{len(dates[x])}</td></tr>'
            for x in up[:6])
        board = (f'<div class="board" role="region" aria-labelledby="board-caption"><div class="wrap">'
                 f'<table class="board__table"><caption id="board-caption" class="board__caption">Kommande lagändringar</caption>'
                 f'<thead><tr><th scope="col">Träder i kraft</th><th scope="col">Vad</th><th scope="col"><abbr title="Antal författningar">Antal</abbr></th></tr></thead>'
                 f'<tbody>{board_rows}</tbody></table></div></div>') if up else ""

        # horizon: one bar per month with changes, height by number of acts
        months = defaultdict(int)
        for x in up:
            months[x[:7]] += len(dates[x])
        peak = max(months.values(), default=1)
        bars, last_year, prev_idx = [], None, None
        for ym, n in months.items():
            y, mo = ym.split("-")
            idx = int(y) * 12 + int(mo)
            if prev_idx and idx - prev_idx > 12:  # long quiet stretch: show the jump instead of faking adjacency
                bars.append('<li class="horizon__gap" aria-hidden="true"><span>⋯</span></li>')
            prev_idx = idx
            label = f"{MONTHS[int(mo) - 1]} {y}"
            year_mark = f'<span class="horizon__year" aria-hidden="true">{y}</span>' if y != last_year else ""
            last_year = y
            h = max(6, round(100 * (n / peak) ** 0.5))
            # not links: month bars are too narrow for a 24px target on phones; board and timeline navigate
            bars.append(f'<li class="horizon__m" style="--h:{h}%">'
                        f'<span class="horizon__bar" aria-hidden="true"></span>'
                        f'<span class="horizon__label" aria-hidden="true">{MONTHS[int(mo) - 1][:3]}</span>'
                        f'<span class="vh">{label}: {se.plural(n, "författning", "författningar")}</span>{year_mark}</li>')
        horizon = (f'<section class="horizon wrap" aria-labelledby="horizon-h"><h2 id="horizon-h" class="section-title">Horisonten</h2>'
                   f'<p class="section-lead">Varje stapel är en månad där beslutade ändringar börjar gälla. Ju högre stapel, desto fler författningar.</p>'
                   f'<ol class="horizon__strip">{"".join(bars)}</ol>'
                   + (f'<p class="horizon__range" aria-hidden="true"><span>{esc(MONTHS[int(up[0][5:7]) - 1])} {up[0][:4]}</span>'
                      f'<span>{esc(MONTHS[int(up[-1][5:7]) - 1])} {up[-1][:4]}</span></p>' if up else "")
                   + '</section>')

        all_depts = sorted({c["department"] for c in self.data["changes"] if c["department"]})
        options = "".join(f'<option value="{esc(x)}">{esc(x)}</option>' for x in all_depts)
        filters = (f'<form class="filter" role="search" hidden aria-label="Filtrera kommande ändringar">'
                   f'<div class="filter__field"><label for="q">Sök lag eller ämne</label>'
                   f'<input id="q" name="q" type="search" autocomplete="off" placeholder="t.ex. skatt, skola, brottsbalk"></div>'
                   f'<div class="filter__field"><label for="dept">Departement</label>'
                   f'<select id="dept" name="dept"><option value="">Alla departement</option>{options}</select></div>'
                   f'<p class="filter__status" role="status" aria-live="polite"></p></form>')

        timeline = "".join(self.day_section(x, dates[x]) for x in up)
        past = ""
        if m["past"]:
            items = "".join(f'<li><a href="{self.href(f"datum/{x}/")}">{esc(long_date(x))}</a> – '
                            f'{se.plural(len(dates[x]), "författning", "författningar")}</li>' for x in m["past"])
            past = (f'<section class="past wrap" aria-labelledby="past-h"><h2 id="past-h" class="section-title">Har nyss börjat gälla</h2>'
                    f'<p class="section-lead">Ändringar som hunnit träda i kraft sedan datan senast kontrollerades.</p><ul class="plain">{items}</ul></section>')
        n_undated = len(self.data["undated"])
        next_line = (f'Nästa gång lagen ändras är <strong>{esc(long_date(up[0]))}</strong>, {esc(relative(up[0], self.today))}.'
                     if up else "Just nu finns inga kommande ändringar med datum.")
        body = f"""
<div class="intro wrap">
  <h1 class="intro__title">Lagar som redan är beslutade, men ännu inte gäller.</h1>
  <p class="intro__lead">Riksdagen och regeringen beslutar ofta om ändringar långt innan de börjar gälla. Här ser du
  <strong>{se.plural(total, 'författning', 'författningar')}</strong> som kommer att ändra svensk lag, vad som ändras och när. {next_line}</p>
</div>
{board}
{horizon}
<section class="timeline wrap" aria-labelledby="timeline-h">
  <h2 id="timeline-h" class="section-title">Alla kommande ändringar</h2>
  {filters}
  {timeline}
  <p class="empty" hidden>Inga ändringar matchar din sökning.</p>
</section>
<aside class="aside wrap" aria-labelledby="undated-h">
  <h2 id="undated-h" class="section-title">Beslutat, men utan datum</h2>
  <p>{se.plural(n_undated, 'lag har', 'lagar har')} bestämmelser som ska börja gälla <em>den dag som regeringen bestämmer</em>.
  <a href="{self.href('ej-satt-datum/')}">Se vilka</a>.</p>
</aside>
{past}"""
        self.page("", "lexAhead", body, active="")

    def back(self, day):
        """Crumb to the day's place in the timeline; past days are only in the 'nyss börjat gälla' list."""
        anchor = f"#d-{day}" if d(day) >= self.today else "#past-h"
        return f'<p class="crumbs"><a href="{self.href()}{anchor}">Alla kommande ändringar</a></p>'

    def date_page(self, day, deps):
        tense = "Börjar gälla" if d(day) >= self.today else "Började gälla"
        body = (f'<div class="wrap page-head">{self.back(day)}'
                f'<h1>{esc(long_date(day, weekday=True))}</h1>'
                f'<p class="lead">{tense} {esc(relative(day, self.today))}: {se.plural(len(deps), "författning", "författningar")}.</p></div>'
                f'<div class="wrap"><ul class="cards cards--page">{"".join(self.card(x, 2) for x in deps)}</ul></div>')
        self.page(f"datum/{day}/", long_date(day), body,
                  description=f"Lagändringar som börjar gälla {long_date(day)}.")

    def commit_link(self, c):
        sha = c["id"].split("-", 1)[0]
        return (f'<p class="source-link"><a href="{esc(self.data["corpus"]["repo"])}/commit/{esc(sha)}">'
                f'Visa ändringen i källdatan (lexifina/sweden-law)</a></p>')

    def explanation(self, c):
        """Reserved for plain-language explanations (later phase); always labelled as such."""
        if not c.get("explanation"):
            return ""
        return (f'<aside class="explanation" aria-label="Förklaring"><p class="explanation__label">Förklaring – inte lagtext</p>'
                f'<p>{esc(c["explanation"])}</p></aside>')

    def decision(self, dec):
        """Riksdagen's own summary of the decision (not ours, not law text) plus how the parties voted."""
        if not dec:
            return ""
        won = ", <strong>som blev riksdagens beslut</strong>"
        def sides(v):
            labels = {"Ja": "Ja till utskottets förslag" + (won if v["yes_won"] else ""),
                      "Nej": "Nej, ville något annat" + ("" if v["yes_won"] else won), "Avstod": "Avstod"}
            return "".join(f'<li>{labels[k]}: {esc(", ".join(v["sides"][k]))}</li>' for k in labels if v["sides"].get(k))
        votes = "".join(f'<li><p class="votes__q">{esc(v["title"])}</p><ul>{sides(v)}</ul>'
                        f'<p class="small"><a href="{esc(v["url"])}">Hela omröstningen: {esc(v["title"])}</a></p></li>'
                        for v in dec["votes"])
        votes = (f'<h3>Så röstade partierna</h3>'
                 f'<p class="small">I riksdagen röstar man ja eller nej till utskottets förslag. Nej betyder att partiet '
                 f'ville något annat, oftast ett eget motförslag (en reservation). Partierna visas efter hur de flesta '
                 f'av deras ledamöter röstade.</p><ul class="votes">{votes}</ul>') if votes else ""
        return (f'<aside class="explanation decision" aria-labelledby="dec-h">'
                f'<p class="explanation__label">Riksdagens sammanfattning – inte lagtext</p>'
                f'<h2 id="dec-h">{esc(dec["headline"])}</h2>{dec["notis"]}{votes}'
                f'<p class="muted small">Källa: <a href="{esc(dec["url"])}">betänkande {esc(dec["bet"])}</a>, '
                f'Sveriges riksdag. Sammanfattningen gäller hela betänkandet, som kan omfatta fler lagar än den här.</p></aside>')

    def facts(self, rows):
        return '<dl class="facts">' + "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in rows if v) + "</dl>"

    def prep_html(self, prep):
        links = se.prep_links(prep)
        return ", ".join(f'<a href="{esc(u)}">{esc(t)}</a>' if u else esc(t) for t, u in links)

    def act_page(self, a):
        when = ", ".join(long_date(x) for x in a["dates"])
        future = d(a["dates"][-1]) >= self.today
        title = a["title"]
        # Riksdagen's open data has the statutes themselves, not amending acts: link the affected statutes
        sources = list(dict.fromkeys(
            f'<a href="{esc(c["law_source"])}">{esc(se.short_title(c["law_title"]))} hos riksdagen (öppna data)</a>'
            for c in a["changes"] if c["law_source"]))
        facts = self.facts([
            ("Träder i kraft" if future else "Trädde i kraft", esc(when) + f' <span class="muted">({esc(relative(a["dates"][0], self.today))})</span>'),
            ("Beslutas av", {"riksdagen": "Riksdagen (lag)", "regeringen": "Regeringen (förordning)"}.get(a["by"], "")),
            ("Departement", esc(", ".join(a["departments"]))),
            ("Förarbeten", self.prep_html(a["prep"]) if a["prep"] else ""),
            ("Källor", " · ".join(sources)),
        ])
        parts = []
        for c in a["changes"]:
            law_link = f'<a href="{self.href("lag/" + slug(c["law"]) + "/")}">{esc(se.short_title(c["law_title"]))}</a>'
            scope = (f'<p class="scope"><span class="muted">Enligt registret (SFSR):</span> {esc(c["scope"])}</p>'
                     if c["scope"] else "")
            date_note = f' <span class="muted">· {esc(long_date(c["date"]))}</span>' if len(a["dates"]) > 1 else ""
            parts.append(f'<section class="change" id="{esc(c["id"])}"><h2 class="change__title">{law_link}{date_note}</h2>'
                         f'<p class="change__summary">{esc(change_summary(c))}</p>{scope}{self.explanation(c)}'
                         f'{change_body(c, 3)}{self.commit_link(c)}</section>')
        legend = LEGEND if any(c["kind"] not in ("enacted", "repeal") for c in a["changes"]) else ""
        body = (f'<div class="wrap page-head">{self.back(a["dates"][-1])}'
                f'<div class="card__tags">{self.tags(a, a["changes"])}</div>'
                f'<h1>{esc(se.short_title(title))}</h1><p class="lead official">{esc(title)}</p>{facts}</div>'
                f'<div class="wrap wrap--text">{self.decision(a.get("decision"))}{legend}{"".join(parts)}</div>')
        self.page(f"forfattning/{a['slug']}/", se.short_title(title), body,
                  description=f"{se.short_title(title)}: vad som ändras och när ({when}).")

    def law_page(self, law):
        parts = []
        for c in law["changes"]:
            a_title = c["act_title"] or "Ändring utan angiven författning"
            act = (f'<a href="{self.href("forfattning/" + slug(c["act"]) + "/")}">{esc(a_title)}</a>' if c["act"] else esc(a_title))
            parts.append(f'<section class="change" id="{esc(c["id"])}"><h2 class="change__title">{esc(long_date(c["date"]))} '
                         f'<span class="muted">{esc(relative(c["date"], self.today))}</span></h2>'
                         f'<p class="change__act">{act}</p><p class="change__summary">{esc(change_summary(c))}</p>'
                         f'{self.explanation(c)}{change_body(c, 3)}{self.commit_link(c)}</section>')
        links = []
        if url := se.riksdagen_sfs_url(law["sfs"]):
            links.append(f'<a href="{esc(url)}">Gällande text hos riksdagen (öppna data)</a>')
        if law["source"] and law["source"] != url:
            links.append(f'<a href="{esc(law["source"])}">Officiell källa</a>')
        facts = self.facts([("SFS-nummer", esc(law["sfs"])), ("Departement", esc(law["department"])),
                            ("Källor", " · ".join(links))])
        body = (f'<div class="wrap page-head"><p class="crumbs"><a href="{self.href("lag/")}">Alla lagar som ändras</a></p>'
                f'<h1>{esc(se.short_title(law["title"]))}</h1><p class="lead official">{esc(law["title"])}</p>{facts}</div>'
                f'<div class="wrap wrap--text">{LEGEND}{"".join(parts)}</div>')
        self.page(f"lag/{law['slug']}/", se.short_title(law["title"]), body,
                  description=f"Kommande ändringar i {se.short_title(law['title'])}.")

    def laws_index(self, m):
        rows = sorted(m["laws"].values(), key=lambda l: se.short_title(l["title"]).lower())
        items = "".join(
            f'<li class="lawlist__item" data-text="{esc(l["title"].lower())}" data-dept="{esc(l["department"])}">'
            f'<a href="{self.href("lag/" + l["slug"] + "/")}">{esc(se.short_title(l["title"]))}</a> '
            f'<span class="muted">SFS {esc(l["sfs"])} · {se.plural(len(l["changes"]), "ändring", "ändringar")}, '
            f'första {esc(long_date(l["changes"][0]["date"]))}</span></li>' for l in rows)
        body = (f'<div class="wrap page-head"><h1>Lagar som ändras</h1>'
                f'<p class="lead">{se.plural(len(rows), "lag eller förordning", "lagar och förordningar")} har beslutade ändringar som ännu inte börjat gälla.</p></div>'
                f'<div class="wrap"><ul class="lawlist">{items}</ul></div>')
        self.page("lag/", "Lagar som ändras", body, active="lag/")

    def undated_page(self):
        sections = []
        for law in self.data["undated"]:
            items = "".join(f'<li><span class="unit-label">{esc(u["label"])}</span> {esc(u["what"])}</li>' for u in law["units"])
            link = f' <a class="muted" href="{esc(law["law_source"])}">Källa</a>' if law["law_source"] else ""
            sections.append(f'<section class="undated"><h2>{esc(se.short_title(law["law_title"]))}</h2>'
                            f'<p class="muted">SFS {esc(law["law"])} · {esc(law["department"])}{link}</p><ul class="plain">{items}</ul></section>')
        body = (f'<div class="wrap page-head"><h1>Beslutat, men utan datum</h1>'
                f'<p class="lead">De här bestämmelserna är beslutade men ska börja gälla <em>den dag som regeringen bestämmer</em>. '
                f'Regeringen har ännu inte bestämt dagen, så de finns inte med i tidslinjen.</p></div>'
                f'<div class="wrap wrap--text">{"".join(sections)}</div>')
        self.page("ej-satt-datum/", "Beslutat, men utan datum", body, active="ej-satt-datum/")

    def about_page(self):
        c, v = self.data["corpus"], self.version
        up = v["corpora"][c["id"]]["upstream"]
        body = f"""
<div class="wrap page-head"><h1>Om lexAhead</h1>
<p class="lead">lexAhead visar lagändringar som redan är beslutade men ännu inte har börjat gälla, så att alla kan se vad som är på väg.</p></div>
<div class="wrap wrap--text prose">
<h2>Varifrån kommer uppgifterna?</h2>
<p>Lagtexterna kommer från Regeringskansliets konsoliderade författningssamling (SFST) och dess register över ändringar (SFSR),
publicerade som öppna data av riksdagen på <a href="https://data.riksdagen.se/">data.riksdagen.se</a>. <strong>Källa: Sveriges riksdag.</strong></p>
<p>Texterna är sammanställda som ett git-arkiv av <a href="{esc(c['repo'])}">lexifina/sweden-law</a>. Där ligger kommande ändringar på grenen
<code>future</code>, daterade med den dag de börjar gälla. lexAhead läser den grenen och registret och gör om dem till de här sidorna.
Ingenting tolkas eller skrivs om: texten är exakt som den publicerats.</p>
<h2>Varför lagar i git?</h2>
<p>Git är ett verktyg som programmerare använder för att hålla reda på varje ändring i en text: vad som ändrades,
när och av vem. När lagarna läggs in på samma sätt blir det lättare att se hur de förändras.</p>
<ul>
<li><strong>Exakt vad som ändras.</strong> En ändringslag skrivs som instruktioner ("2 kap. 6 § ska ha följande lydelse")
och visar bara den nya texten. För att se skillnaden måste man jämföra med den gamla. Git gör jämförelsen åt dig, ord för ord.</li>
<li><strong>Varje ändring har ett datum och en avsändare.</strong> Varje ändring är en egen post som säger vilken dag den börjar
gälla och vilken författning som beslutade den. Det går att följa från lagtexten tillbaka till beslutet.</li>
<li><strong>Framtiden syns i förväg.</strong> Beslutade ändringar ligger på en egen gren, daterade framåt i tiden.
Det är den lexAhead visar.</li>
<li><strong>Kontrollerbart.</strong> Varje version har ett unikt fingeravtryck, så vem som helst kan kontrollera att texten
här är densamma som i källan. Länken "Visa ändringen i källdatan" under varje ändring går direkt dit.</li>
<li><strong>Öppet att bygga vidare på.</strong> Arkivet är fritt att ladda ner. lexAhead är ett exempel på vad man kan bygga;
journalister, forskare och organisationer kan bygga egna bevakningar på samma data.</li>
</ul>
<p>En begränsning: källan sparar bara den senaste versionen av varje lag, inte äldre versioner. Historiken bakåt
är därför ofullständig, medan de kommande ändringarna finns med i sin helhet.</p>
<h2>Hur läser jag en ändring?</h2>
{LEGEND}
<p>Varje paragraf visas som den ser ut efter ändringen. Text som tas bort är <del>genomstruken</del>, text som läggs till är <ins>understruken</ins>.
Sist i varje paragraf står vilken författning som senast gav den dess lydelse, till exempel <span class="not-inline">Lag (2025:736).</span></p>
<p>En <strong>lag</strong> beslutas av riksdagen. En <strong>förordning</strong> beslutas av regeringen. Under <em>Förarbeten</em> finns
regeringens proposition och riksdagsutskottets betänkande, där skälen till ändringen står.</p>
<h2>Det här är inte en officiell tjänst</h2>
<p>lexAhead ges inte ut av riksdagen eller Regeringskansliet. Uppgifterna kan vara ofullständiga eller försenade. Kontrollera alltid mot den
officiella texten i Svensk författningssamling innan du fattar beslut.</p>
<h2>Hur färsk är datan?</h2>
<p>Datan kontrollerades mot källan {esc(long_date(c['checked_on']) if c.get('checked_on') else '–')}. Sidan byggs om automatiskt när
lexifina/sweden-law uppdateras, och varje natt så att datum och "om X dagar" stämmer.</p>
{self.facts([("Version", esc(v['version'])), ("Byggd", esc(v['built_at'])),
              ("Källdata (main)", f'<code>{esc(up.get("main", "")[:12])}</code>'),
              ("Källdata (future)", f'<code>{esc(up.get("future", "")[:12])}</code>')])}
<h2>Öppna data</h2>
<p>Allt som visas här finns som <a href="{self.href('data/upcoming.json')}">JSON</a> och som
<a href="{self.href('feed.xml')}">RSS-flöde</a> som du kan prenumerera på.</p>
<h2 id="tillganglighet">Tillgänglighet</h2>
<p>lexAhead ska gå att använda för alla. Målet är att uppfylla WCAG 2.2 på nivå AA: sidan fungerar med tangentbord och skärmläsare,
utan JavaScript, med förstorad text och i mörkt läge. Ändringar markeras aldrig bara med färg. Om något inte fungerar för dig vill vi veta det.</p>
<h2>Vem står bakom?</h2>
<p>lexAhead är ett fristående projekt av Philip Lilius, senior rådgivare på <a href="https://www.friendsagenda.se">Friends Agenda</a>,
byggt för att göra kommande lagändringar lättare att följa för alla.
Mer om mig och andra projekt finns på <a href="https://philip.lilius.io">philip.lilius.io</a>.</p>
<h2>Typsnitt</h2>
<p>IBM Plex, under <a href="{self.href('assets/fonts/OFL.txt')}">SIL Open Font License</a>.</p>
</div>"""
        self.page("om/", "Om lexAhead", body, active="om/")

    def not_found(self):
        body = (f'<div class="wrap page-head"><h1>Sidan finns inte</h1><p class="lead">Ändringen kan ha börjat gälla eller tagits bort. '
                f'<a href="{self.href()}">Till alla kommande ändringar</a>.</p></div>')
        self.page("404.html", "Sidan finns inte", body)

    def feed(self, m):
        # shortcut: pubDate is the data snapshot day (we keep no "first seen" state); readers dedupe on guid
        snap = self.data["corpus"].get("built") or self.today.isoformat()
        pub = format_datetime(dt.datetime.fromisoformat(snap + "T12:00:00+01:00"))
        items = []
        for day in m["upcoming"]:
            for dep in m["dates"][day]:
                a, cs = dep["act"], dep["changes"]
                link = self.abs(act_href(a, cs[0]))
                desc = " ".join(f"{se.short_title(c['law_title'])}: {change_summary(c)}" for c in cs)
                items.append(f"<item><title>{esc(long_date(day))}: {esc(heading(dep))}</title><link>{esc(link)}</link>"
                             f"<guid isPermaLink=\"false\">{esc(a['key'])}@{day}</guid><pubDate>{pub}</pubDate>"
                             f"<description>{esc(desc)}</description>"
                             + "".join(f"<category>{esc(x)}</category>" for x in sorted({c['department'] for c in cs if c['department']}))
                             + "</item>")
        self.write("feed.xml", f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>
<title>lexAhead – kommande lagändringar</title><link>{esc(self.abs())}</link>
<atom:link href="{esc(self.abs('feed.xml'))}" rel="self" type="application/rss+xml"/>
<description>Beslutade ändringar i svensk lag som ännu inte börjat gälla. Källa: Sveriges riksdag.</description>
<language>sv</language><lastBuildDate>{format_datetime(dt.datetime.fromisoformat(self.version['built_at']))}</lastBuildDate>
<generator>lexAhead {esc(self.version['version'])}</generator>
{"".join(items)}
</channel></rss>
""")


def render(data, out: Path, base, site_url, today, static: Path):
    if out.exists():
        if any(out.iterdir()) and not (out / "version.json").exists():
            raise SystemExit(f"refusing to overwrite {out}: not a previous lexAhead build")
        shutil.rmtree(out)
    shutil.copytree(static, out / "assets")
    s = Site(data, out, base, site_url, today)
    m = build_model(data, today)
    s.index(m)
    for day, deps in m["dates"].items():
        s.date_page(day, deps)
    for a in m["acts"].values():
        if a["slug"]:
            s.act_page(a)
    for law in m["laws"].values():
        s.law_page(law)
    s.laws_index(m)
    s.undated_page()
    s.about_page()
    s.not_found()
    s.feed(m)
    (out / "data").mkdir(exist_ok=True)
    public = {**data, "changes": [{**c, "units": [{k: v for k, v in u.items() if k != "key"} for u in c["units"]],
                                   "explanation": None} for c in data["changes"]],
              "undated": [{**l, "units": [{k: v for k, v in u.items() if k != "key"} for u in l["units"]]}
                          for l in data["undated"]]}
    (out / "data/upcoming.json").write_text(json.dumps(public, ensure_ascii=False), encoding="utf-8")
    (out / "version.json").write_text(json.dumps(data["version"], ensure_ascii=False, indent=1), encoding="utf-8")
    (out / ".nojekyll").write_text("")
