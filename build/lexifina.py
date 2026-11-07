"""Read a corpus published in Lexifina's git format (corpus.json, `main` + `future`
branches, one commit per dated change with trailers) into plain, country-neutral events.

Nothing here knows about Sweden: a new country or the EU only needs a corpus entry in
corpora.json and an adapter for its labels and register (see se.py).
"""
import json
import re
import subprocess
from pathlib import Path

SEP_COMMIT, SEP_FIELD, SEP_TRAILER = "\x00", "\x1f", "\x1e"


def git(repo, *args):
    # commit-graph off: with a blobless clone, lazy blob fetches otherwise fail ("in the commit graph
    # file but not in the object database") once `future` was fetched after a single-branch clone
    return subprocess.run(["git", "-C", str(repo), "-c", "core.commitGraph=false", *args], check=True,
                          capture_output=True, text=True, encoding="utf-8").stdout


def sync(url, repo: Path, branches=("main", "future")):
    """Blobless clone (or fetch) of the branches we read. Returns their head SHAs."""
    if not (repo / "HEAD").exists() and not (repo / ".git").exists():
        repo.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", "--bare", "--filter=blob:none", "--single-branch",
                        "--branch", branches[0], "--no-tags", url, str(repo)], check=True)
    git(repo, "fetch", "--quiet", "--no-tags", "--force", "origin",
        *[f"+refs/heads/{b}:refs/heads/{b}" for b in branches])
    return {b: git(repo, "rev-parse", f"refs/heads/{b}").strip() for b in branches}


def show(repo, ref, path):
    return git(repo, "show", f"{ref}:{path}")


def corpus_info(repo, ref="main"):
    return json.loads(show(repo, ref, "corpus.json"))


def trailers(raw):
    out = {}
    for line in raw.split(SEP_TRAILER):
        k, _, v = line.partition(":")
        if v:
            out.setdefault(k.strip(), []).append(v.strip())
    return out


def parse_patch(patch):
    """Unified diff with full context -> [{path, op, before, after}]."""
    files = []
    for chunk in re.split(r"^diff --git ", patch, flags=re.M)[1:]:
        head, _, body = chunk.partition("\n@@")
        old = re.search(r"^--- (?:a/(.+)|/dev/null)$", head, re.M)
        new = re.search(r"^\+\+\+ (?:b/(.+)|/dev/null)$", head, re.M)
        if not old or not new:  # mode-only or binary change: nothing to show
            continue
        before, after = [], []
        for line in body.split("\n")[1:]:  # first line is the rest of the @@ header
            if line.startswith("@@") or line.startswith("\\"):
                continue
            tag, text = line[:1], line[1:]
            if tag in (" ", "-"):
                before.append(text)
            if tag in (" ", "+"):
                after.append(text)
        op = "added" if old.group(1) is None else "removed" if new.group(1) is None else "modified"
        files.append({"path": new.group(1) or old.group(1), "op": op,
                      "before": "\n".join(before).strip("\n") if op != "added" else "",
                      "after": "\n".join(after).strip("\n") if op != "removed" else ""})
    return files


def future_events(repo, base="main", future="future"):
    """Every commit on `future` not on `main`, oldest first, with full before/after text."""
    fmt = "%x00" + "%x1f".join(["%H", "%an", "%s", "%(trailers:separator=%x1e)"]) + "%x1f"  # git expands %xNN
    out = git(repo, "log", "--reverse", "-p", "-U100000", "--no-renames", "--no-color",
              f"--format={fmt}", f"refs/heads/{base}..refs/heads/{future}")
    events = []
    for rec in out.split(SEP_COMMIT)[1:]:
        sha, author, subject, trl, patch = rec.split(SEP_FIELD, 4)
        t = trailers(trl)
        events.append({
            "id": sha[:12],
            "date": t.get("In-force", [""])[0],
            "kind": t.get("Kind", ["unknown"])[0],
            "author": author,
            "subject": subject,
            "trailers": t,
            "files": parse_patch(patch),
        })
    return events
