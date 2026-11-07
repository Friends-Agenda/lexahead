"""Swedish adapter for lexifina/sweden-law: SFS numbers, paragraf labels, the SFSR register
(data/amendments.csv), and links to Riksdagen's open data and EUR-Lex."""
import csv
import io
import re
from collections import defaultdict

from lexifina import show

LANG = "sv"

# "/Upphör att gälla U:2028-07-01/", "/Rubriken träder i kraft I:2027-01-01/", "... genom lag (2024:562)./",
# sometimes without the closing slash; "/Ny beteckning 2 d § U:2026-12-05/" is a renumbering and kept as a note
WHEN = r"[UI]:(?:\d{4}-\d\d-\d\d|den dag som regeringen bestämmer)[^/\n]*(?:/|$)"
RENUMBER = re.compile(r"\s*/Ny beteckning ([^/\n]+?) " + WHEN, re.M)
MARKER = re.compile(r"\s*/[^/\n]{0,60}?" + WHEN, re.M)
NOTE = re.compile(r"^(?:Lag|Förordning|Kungörelse|Balk|Tillkännagivande|Instruktion|Reglemente|Stadga)\b.*\(\d{4}:[^)]+\)\.$")


def read_csv(repo, path):
    return list(csv.DictReader(io.StringIO(show(repo, "refs/heads/main", path))))


def load(repo):
    laws = {r["path"].rstrip("/"): r for r in read_csv(repo, "laws.csv")}
    amend = defaultdict(list)
    for r in read_csv(repo, "data/amendments.csv"):
        amend[(r["law"], r["amending_sfs"])].append(r)
    return {"laws": laws, "by_sfs": {r["sfs"]: r for r in laws.values()}, "amend": amend,
            "undated": read_csv(repo, "data/undated.csv")}


def clean(text):
    return MARKER.sub("", RENUMBER.sub(r" [får ny beteckning \1]", text))


def is_note(line):
    return bool(NOTE.match(line.strip()))


def short_title(title):
    """'Diskrimineringslag (2008:567)' -> 'Diskrimineringslag'."""
    return re.sub(r"\s*\(\d{4}:[^)]*\)", "", title).strip()


def department(raw):
    m = re.match(r"^(.*?departementet)\b", raw or "")
    return m.group(1) if m else (raw or "").strip()


def decided_by(title):
    """Who decides this kind of statute: lagar by the Riksdag, förordningar by the Government."""
    first = (title or "").split(" ", 1)[0].lower()
    if first == "lag" or first.endswith("balk"):
        return "riksdagen"
    if first == "förordning":
        return "regeringen"
    return None


def law_dir(path):
    return "/".join(path.split("/")[:2])


def unit(relpath):
    """('kap-2a/6b~2.md') -> (sort key, '2 a kap. 6 b §'). Unknown shapes keep their file name."""
    name = relpath.rsplit("/", 1)[-1].removesuffix(".md").split("~")[0]
    chap = re.match(r"kap-(\d+)([a-z]?)/", relpath)
    ckey = (int(chap.group(1)), chap.group(2)) if chap else (0, "")
    clabel = f"{chap.group(1)}{' ' + chap.group(2) if chap.group(2) else ''} kap. " if chap else ""
    if m := re.fullmatch(r"(\d+)([a-z]?)", name):
        return (ckey, 1, int(m.group(1)), m.group(2)), f"{clabel}{m.group(1)}{' ' + m.group(2) if m.group(2) else ''} §"
    if name == "ingress":
        return (ckey, 0, 0, ""), "Inledning"
    if name == "overgang":
        return ((9999, ""), 2, 0, ""), "Övergångsbestämmelser"
    if m := re.fullmatch(r"bilaga-?(\w*)", name):
        return ((9999, ""), 3, int(m.group(1)) if m.group(1).isdigit() else 0, m.group(1)), f"Bilaga {m.group(1)}".strip()
    return ((9999, ""), 4, 0, name), name


def changes(events, reg):
    """Split each commit per statute it touches and attach Swedish labels and register data."""
    out = []
    for e in events:
        t = e["trailers"]
        act = (t.get("Amending-act") or t.get("Repealed-by") or t.get("Law") or [""])[0].removeprefix("SFS ").strip()
        by_law = defaultdict(list)
        for f in e["files"]:
            if f["path"].endswith(".md"):
                by_law[law_dir(f["path"])].append(f)
        for d, files in by_law.items():
            law = reg["laws"].get(d, {})
            sfs = law.get("sfs") or d.replace("/", ":")
            units = []
            for f in files:
                key, label = unit(f["path"][len(d) + 1:])
                units.append({"key": key, "label": label, "op": f["op"],
                              "before": clean(f["before"]), "after": clean(f["after"])})
            units.sort(key=lambda u: u["key"])
            rows = reg["amend"].get((sfs, act), [])
            out.append({
                "id": f"{e['id']}-{d.replace('/', '-')}",
                "date": e["date"],
                "kind": e["kind"],
                "act": act or None,
                "act_title": e["author"] if act else None,
                "candidates": [c.removeprefix("SFS ") for c in t.get("Candidate", [])],
                "law": sfs,
                "law_title": law.get("title") or e["author"],
                "department": department(law.get("department")),
                "law_source": law.get("source"),
                "scope": "; ".join(r["scope"] for r in rows if r["scope"]),
                "prep": next((r["preparatory_works"] for r in rows if r["preparatory_works"]), ""),
                "units": units,
            })
    return out


# --- links -------------------------------------------------------------------------------

RM_DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def riksmote_code(rm):
    """'2025/26' -> 'HD'. Riksdagen's document ids use H0 = 2012/13 onwards."""
    m = re.fullmatch(r"(\d{4})/\d{2}", rm)
    if not m or not 0 <= int(m.group(1)) - 2012 < len(RM_DIGITS):
        return None
    return "H" + RM_DIGITS[int(m.group(1)) - 2012]


def riksdagen_sfs_url(sfs):
    m = re.fullmatch(r"(\d{4}):(\d+)", sfs or "")
    return f"https://data.riksdagen.se/dokument/sfs-{m.group(1)}-{m.group(2)}.html" if m else None


def prep_links(prep):
    """'Prop. 2025/26:295, bet. 2025/26:JuU41, rskr. 2025/26:436, direktiv (EU) 2023/2864'
    -> [(label, url or None)]: props and betänkanden on data.riksdagen.se, EU acts by ELI."""
    out = []
    for part in [p.strip() for p in prep.split(",") if p.strip()]:
        url = None
        if m := re.match(r"(?i)prop\.\s*(\d{4}/\d{2}):(\d+)", part):
            code = riksmote_code(m.group(1))
            url = code and f"https://data.riksdagen.se/dokument/{code}03{m.group(2)}.html"
        elif m := re.match(r"(?i)bet\.\s*(\d{4}/\d{2}):(\w+)", part):
            code = riksmote_code(m.group(1))
            url = code and f"https://data.riksdagen.se/dokument/{code}01{m.group(2)}.html"
        elif m := re.search(r"(direktiv|förordning)\s*\((?:EU|EG|EEG|Euratom)\)\s*(nr\s*)?(\d+)/(\d+)", part, re.I):
            kind = "dir" if m.group(1).lower() == "direktiv" else "reg"
            # "(EU) 2016/679" is year/number; the older "(EG) nr 1907/2006" is number/year
            year, num = (m.group(4), m.group(3)) if m.group(2) else (m.group(3), m.group(4))
            url = f"https://eur-lex.europa.eu/eli/{kind}/{year}/{int(num)}/oj" if len(year) == 4 else None
        out.append((part, url))
    return out


# --- plain-language summaries --------------------------------------------------------------

def plural(n, one, many):
    return f"{n} {one if n == 1 else many}"


def summary(units):
    """'Ändrar 3 paragrafer, inför 1 ny och upphäver 2.' from what the commit actually does."""
    ops = defaultdict(int)
    for u in units:
        ops[u["op"]] += 1
    parts = []
    if ops["modified"]:
        parts.append(f"ändrar {plural(ops['modified'], 'bestämmelse', 'bestämmelser')}")
    if ops["added"]:
        parts.append(f"inför {plural(ops['added'], 'ny bestämmelse', 'nya bestämmelser')}")
    if ops["removed"]:
        parts.append(f"tar bort {plural(ops['removed'], 'bestämmelse', 'bestämmelser')}")
    if not parts:
        return ""
    text = ", ".join(parts[:-1]) + (" och " if len(parts) > 1 else "") + parts[-1]
    return text[0].upper() + text[1:] + "."


def undated(reg):
    """data/undated.csv grouped per statute, with labels: changes decided but not yet dated."""
    by = defaultdict(lambda: defaultdict(set))
    for r in reg["undated"]:
        by[r["law"]][r["file"]].add(r["marker"])
    out = []
    for sfs, files in by.items():
        law = reg["by_sfs"].get(sfs, {})
        items = []
        for f, marks in files.items():
            key, label = unit(f)
            what = "ändras" if marks == {"U", "I"} else "upphör att gälla" if marks == {"U"} else "ny lydelse"
            items.append({"key": key, "label": label, "what": what})
        items.sort(key=lambda i: i["key"])
        out.append({"law": sfs, "law_title": law.get("title", sfs), "department": department(law.get("department")),
                    "law_source": law.get("source"), "units": items})
    out.sort(key=lambda x: short_title(x["law_title"]).lower())
    return out
