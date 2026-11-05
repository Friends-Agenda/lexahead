# Refreshes

The record grows forward. The sources keep only today's consolidation of each statute, so every day this repository is
refreshed: the statutes Riksdagen re-published since the last refresh are fetched again (the dokumentstatus JSON and
the SFSR register page), the builder in tools/build rebuilds the whole corpus from the cache, and for each statute
whose text changed only the commits after its published state are appended to `main`, unchanged in author, date and
message: a new consolidated text dated by the in-force day of the latest amending act it includes (SFSR register), a
provision printed in two dated versions changing on its day, a repeal deleting the statute, a new statute as its first
commit. Published commits are never rewritten. Each appended version is read back from git and its letters and digits
compared with the raw source before it is pushed (tools/build/check_repo.py's readers).

A statute whose published text the fresh build does not pass through (for example when the publisher re-dates an
amendment) is not appended; it waits for a correction. data/refresh.csv lists every refresh.

The `future` branch is the one built on 2026-10-28; texts it holds reach `main` on their day through these refreshes.

Refreshes so far: 1; the last on 2026-11-05, appending 5 statutes in 5 commits.
