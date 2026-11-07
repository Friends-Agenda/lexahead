"""Offline unit tests: python -m unittest discover -s build"""
import datetime as dt
import unittest

import build
import lexifina
import se
import site_render

PATCH = """diff --git a/2008/567/kap-2/6.md b/2008/567/kap-2/6.md
index f2043db70..eea2f38bd 100644
--- a/2008/567/kap-2/6.md
+++ b/2008/567/kap-2/6.md
@@ -1,3 +1,3 @@
-6 § /Upphör att gälla U:2028-07-01/ Förbudet gäller förskoleklassen.
+6 § /Träder i kraft I:2028-07-01/ Förbudet gäller förskolan.

-Lag (2023:352).
+Lag (2025:736).
diff --git a/2026/1306/1.md b/2026/1306/1.md
new file mode 100644
--- /dev/null
+++ b/2026/1306/1.md
@@ -0,0 +1 @@
+1 § Ny text.
diff --git a/1998/641/2.md b/1998/641/2.md
deleted file mode 100644
--- a/1998/641/2.md
+++ /dev/null
@@ -1 +0,0 @@
-2 § Gammal text.
\\ No newline at end of file
"""


class Extract(unittest.TestCase):
    def test_parse_patch(self):
        f = lexifina.parse_patch(PATCH)
        self.assertEqual([x["op"] for x in f], ["modified", "added", "removed"])
        self.assertIn("förskoleklassen", f[0]["before"])
        self.assertIn("förskolan", f[0]["after"])
        self.assertEqual(f[1], {"path": "2026/1306/1.md", "op": "added", "before": "", "after": "1 § Ny text."})
        self.assertEqual(f[2]["before"], "2 § Gammal text.")

    def test_trailers(self):
        t = lexifina.trailers("Kind: amendment\x1eCandidate: SFS 1\x1eCandidate: SFS 2")
        self.assertEqual(t, {"Kind": ["amendment"], "Candidate": ["SFS 1", "SFS 2"]})


class Swedish(unittest.TestCase):
    def test_clean_markers(self):
        cases = {
            "6 § /Upphör att gälla U:2028-07-01/ Förbudet": "6 § Förbudet",
            "### Rubrik /Rubriken träder i kraft I:2027-01-01/": "### Rubrik",
            "x /Träder i kraft I:2027-01-01": "x",
            "a /Kapitlet upphör att gälla U:2031-06-01 genom lag (2025:300).": "a",
            "7 § /Upphör att gälla U:den dag som regeringen bestämmer/ Åklagare": "7 § Åklagare",
            "2 c § /Ny beteckning 2 d § U:2026-12-05/ Ett": "2 c § [får ny beteckning 2 d §] Ett",
            "direktiv (EU) 2023/2864 om /x/ y": "direktiv (EU) 2023/2864 om /x/ y",
        }
        for raw, want in cases.items():
            self.assertEqual(se.clean(raw), want)

    def test_unit_labels(self):
        self.assertEqual(se.unit("kap-2/6.md")[1], "2 kap. 6 §")
        self.assertEqual(se.unit("kap-2a/6b~2.md")[1], "2 a kap. 6 b §")
        self.assertEqual(se.unit("3a.md")[1], "3 a §")
        self.assertEqual(se.unit("overgang.md")[1], "Övergångsbestämmelser")
        self.assertEqual(se.unit("bilaga-2.md")[1], "Bilaga 2")
        keys = sorted(["kap-10/1.md", "kap-2/10.md", "kap-2/9.md", "ingress.md", "overgang.md"], key=lambda p: se.unit(p)[0])
        self.assertEqual(keys, ["ingress.md", "kap-2/9.md", "kap-2/10.md", "kap-10/1.md", "overgang.md"])

    def test_summary(self):
        u = [{"op": "modified"}] * 3 + [{"op": "added"}] + [{"op": "removed"}] * 2
        self.assertEqual(se.summary(u), "Ändrar 3 bestämmelser, inför 1 ny bestämmelse och tar bort 2 bestämmelser.")
        self.assertEqual(se.summary([{"op": "removed"}]), "Tar bort 1 bestämmelse.")
        # removed heading counted; a chapter heading that moves to another § file is not a change
        moved = [{"op": "removed", "before": "## 3 kap. X\n\n### R\n\n1 § a", "after": ""},
                 {"op": "modified", "before": "2 § b", "after": "## 3 kap. X\n\n2 § b"}]
        self.assertEqual(se.summary(moved), "Ändrar 1 bestämmelse och tar bort 1 bestämmelse och 1 rubrik.")

    def test_decided_by(self):
        self.assertEqual(se.decided_by("Lag (2025:736) om ändring"), "riksdagen")
        self.assertEqual(se.decided_by("Brottsbalk (1962:700)"), "riksdagen")
        self.assertEqual(se.decided_by("Förordning (2026:545) om"), "regeringen")
        self.assertIsNone(se.decided_by("Kungörelse (1950:1)"))

    def test_links(self):
        self.assertEqual(se.riksmote_code("2025/26"), "HD")
        self.assertEqual(se.riksmote_code("2024/25"), "HC")
        self.assertIsNone(se.riksmote_code("1999/00"))
        links = dict(se.prep_links("Prop. 2025/26:295, bet. 2025/26:JuU41, rskr. 2025/26:436, direktiv (EU) 2023/2864"))
        self.assertEqual(links["Prop. 2025/26:295"], "https://data.riksdagen.se/dokument/HD03295.html")
        self.assertEqual(links["bet. 2025/26:JuU41"], "https://data.riksdagen.se/dokument/HD01JuU41.html")
        self.assertIsNone(links["rskr. 2025/26:436"])
        self.assertEqual(links["direktiv (EU) 2023/2864"], "https://eur-lex.europa.eu/eli/dir/2023/2864/oj")
        eu = dict(se.prep_links("förordning (EG) nr 1907/2006, förordning (EU) 2016/679"))
        self.assertEqual(eu["förordning (EG) nr 1907/2006"], "https://eur-lex.europa.eu/eli/reg/2006/1907/oj")
        self.assertEqual(eu["förordning (EU) 2016/679"], "https://eur-lex.europa.eu/eli/reg/2016/679/oj")
        self.assertEqual(se.riksdagen_sfs_url("1962:700"), "https://data.riksdagen.se/dokument/sfs-1962-700.html")
        self.assertIsNone(se.riksdagen_sfs_url("1736:0123 1"))


class Decision(unittest.TestCase):
    def test_notis_is_sanitized(self):
        raw = '<p>Ja &amp; nej</p><script>x()</script><ul><li onclick="y">a<b>b</b></li></ul>'
        self.assertEqual(se.safe_notis(raw), "<p>Ja &amp; nej</p>x()<ul><li>ab</li></ul>")

    def test_vote_sides(self):
        t = {"table": {"tbody": {"tr": [{"th": "S", "td": ["105", "0", "0", "1"]}, {"th": "V", "td": ["0", "21", "0", "0"]},
                                        {"th": "-", "td": ["5", "4", "0", "0"]}]}}}
        self.assertEqual(se.vote_sides(t), {"Ja": ["S"], "Nej": ["V"]})


class Render(unittest.TestCase):
    def test_word_diff(self):
        out = site_render.diff_blocks("6 § gäller förskoleklassen.\n\nLag (2023:352).", "6 § gäller förskolan.\n\nLag (2025:736).")
        self.assertEqual(out[0][1], [("=", "6 § gäller "), ("-", "förskoleklassen"), ("+", "förskolan"), ("=", ".")])
        self.assertEqual(out[1][1], [("-", "Lag (2023:352)."), ("+", "Lag (2025:736).")])  # note swapped whole

    def test_diff_html_is_escaped_and_labelled(self):
        h = site_render.segs_html([("-", "<b>"), ("+", "ny")])
        self.assertIn("&lt;b&gt;", h)
        self.assertIn("[Tas bort: ", h)
        self.assertIn("[Läggs till: ", h)

    def test_dates(self):
        self.assertEqual(site_render.long_date("2027-01-01", weekday=True), "fredag 1 januari 2027")
        today = dt.date(2026, 11, 7)
        self.assertEqual(site_render.relative("2026-11-08", today), "i morgon")
        self.assertEqual(site_render.relative("2026-11-17", today), "om 10 dagar")
        self.assertEqual(site_render.relative("2026-11-01", today), "för 6 dagar sedan")


class Version(unittest.TestCase):
    def test_next_version(self):
        day = dt.date(2026, 11, 7)
        self.assertEqual(build.next_version(day, {}), "2026.11.07.1")
        self.assertEqual(build.next_version(day, {"version": "2026.11.07.3"}), "2026.11.07.4")
        self.assertEqual(build.next_version(day, {"version": "2026.11.06.9"}), "2026.11.07.1")


if __name__ == "__main__":
    unittest.main()
