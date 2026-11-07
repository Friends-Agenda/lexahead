"""lexAhead build: fetch each corpus, extract upcoming changes, render the static site.

    python build/build.py                      # build into ./site
    python build/build.py --check --previous URL   # print changed=true|false (CI gate)
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

import lexifina
import se
import site_render

ROOT = Path(__file__).resolve().parent.parent
ADAPTERS = {"se": se}
TZ = ZoneInfo("Europe/Stockholm")


def load_previous(src):
    if not src:
        return {}
    try:
        if src.startswith("http"):
            with urllib.request.urlopen(src, timeout=20) as r:
                return json.load(r)
        return json.loads(Path(src).read_text())
    except Exception as e:  # first deploy, or Pages down: build as if new
        print(f"no previous version ({e})", file=sys.stderr)
        return {}


def next_version(today, prev):
    """Date-based: 2026.11.07.1, then .2 for a second build the same day."""
    stem = today.strftime("%Y.%m.%d")
    p = prev.get("version", "")
    n = int(p.rsplit(".", 1)[1]) + 1 if p.startswith(stem + ".") else 1
    return f"{stem}.{n}"


def code_sha():
    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"]
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return "local"


def remote_heads(url):
    out = subprocess.run(["git", "ls-remote", url, "refs/heads/main", "refs/heads/future"],
                         capture_output=True, text=True, check=True).stdout
    return {ref.rsplit("/", 1)[1]: sha for sha, ref in (l.split("\t") for l in out.splitlines())}


def sanity(events, changes):
    """Refuse to publish data that looks broken: better a stale site than a wrong one."""
    problems = []
    if not events:
        problems.append("no commits on future (branch missing or merged?)")
    for c in changes:
        try:
            dt.date.fromisoformat(c["date"])
        except ValueError:
            problems.append(f"{c['id']}: no valid In-force date ({c['date']!r})")
        for u in c["units"]:
            if re.search(r"/[^/\n]{0,60}?[UI]:(\d{4}-\d\d-\d\d|den dag)", u["before"] + u["after"]):
                problems.append(f"{c['id']} {u['label']}: in-force marker left in text")
    if problems:
        raise SystemExit("sanity check failed:\n  " + "\n  ".join(problems[:20]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "site"))
    ap.add_argument("--cache", default=str(ROOT / ".cache"))
    ap.add_argument("--base", default=os.environ.get("BASE_PATH", "/"), help="URL path the site lives under")
    ap.add_argument("--site-url", default=os.environ.get("SITE_URL", "http://localhost:8000"))
    ap.add_argument("--previous", help="path or URL of the live version.json")
    ap.add_argument("--today", help="YYYY-MM-DD, defaults to today in Stockholm")
    ap.add_argument("--check", action="store_true", help="only report whether a rebuild is needed")
    a = ap.parse_args()

    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(TZ).date()
    corpora = [c for c in json.loads((ROOT / "build/corpora.json").read_text()) if c.get("publish")]
    # shortcut: the front end shows one corpus at the site root; add per-corpus paths when a second one is published
    assert len(corpora) == 1, "exactly one published corpus is supported for now"
    c = corpora[0]
    prev = load_previous(a.previous)

    if a.check:
        heads = remote_heads(c["repo"])
        p = prev.get("corpora", {}).get(c["id"], {}).get("upstream", {})
        changed = (heads != p or prev.get("code") != code_sha()
                   or prev.get("built_on") != today.isoformat())
        print(f"changed={'true' if changed else 'false'}")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write(f"changed={'true' if changed else 'false'}\n")
        return

    adapter = ADAPTERS[c["adapter"]]
    repo = Path(a.cache) / c["id"].replace("/", "-")
    print(f"syncing {c['repo']}", file=sys.stderr)
    heads = lexifina.sync(c["repo"], repo)
    info = lexifina.corpus_info(repo)
    reg = adapter.load(repo)
    print("reading future branch", file=sys.stderr)
    events = lexifina.future_events(repo)
    changes = [{"corpus": c["id"], **ch} for ch in adapter.changes(events, reg)]
    sanity(events, changes)
    if hasattr(adapter, "decision"):
        print("fetching decisions from riksdagen", file=sys.stderr)
        for ch in changes:
            ch["decision"] = adapter.decision(ch["prep"], Path(a.cache) / "riksdagen")

    version = {
        "version": next_version(today, prev),
        "built_on": today.isoformat(),
        "built_at": dt.datetime.now(TZ).isoformat(timespec="seconds"),
        "code": code_sha(),
        "corpora": {c["id"]: {"upstream": heads, "checked_on": info.get("checked_on"),
                              "built": info.get("built"), "repo": c["repo_web"]}},
    }
    data = {"corpus": {**info, "id": c["id"], "repo": c["repo_web"]}, "version": version,
            "changes": changes, "undated": adapter.undated(reg)}
    site_render.render(data, Path(a.out), base=a.base, site_url=a.site_url, today=today, static=ROOT / "static")
    print(f"built {version['version']}: {len(changes)} changes -> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
