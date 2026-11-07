# lexAhead

Kommande lagändringar, begripliga för alla. lexAhead visar ändringar i svensk lag som riksdagen eller regeringen
redan har beslutat men som ännu inte börjat gälla: vad som ändras, ord för ord, och när.

**Källa: Sveriges riksdag** ([data.riksdagen.se](https://data.riksdagen.se/)) och Regeringskansliets SFST/SFSR,
sammanställt som git-arkiv av [lexifina/sweden-law](https://github.com/lexifina/sweden-law). lexAhead läser
arkivets `future`-gren (ändringar daterade med ikraftträdandedagen), registret `data/amendments.csv`, `laws.csv`
och `data/undated.csv`. Ingen text skrivs om. lexAhead är inte en officiell tjänst.

## Köra lokalt

Kräver Python 3.10+ och git. Inga beroenden.

```sh
python3 build/build.py                         # hämtar källan till .cache/ och bygger site/
python3 -m http.server -d site 8000            # öppna http://localhost:8000
python3 -m unittest discover -s build          # tester
```

Första körningen gör en blobless klon av källarkivet (snabb). Bygget stoppas om datan ser trasig ut
(saknade datum eller kvarlämnade ikraftträdandemarkörer); hellre en gammal sida än en felaktig.

## Struktur

| Fil | Vad |
| --- | --- |
| `build/corpora.json` | Vilka källarkiv som läses. **Expansionspunkten** för fler länder eller EU. |
| `build/lexifina.py` | Landsneutral läsare av Lexifinas git-format (`corpus.json`, `main`/`future`, trailers). |
| `build/se.py` | Svensk adapter: paragrafetiketter, SFSR-registret, länkar till riksdagen och EUR-Lex, klarspråkssammanfattning. |
| `build/site_render.py` | HTML-sidor, diff, RSS (`feed.xml`), öppna data (`data/upcoming.json`), `version.json`. |
| `build/build.py` | Kör allt, sätter version, `--check` avgör om ombyggnad behövs. |
| `static/` | CSS, liten JS (sökfilter, progressiv förbättring), IBM Plex (OFL), ikon. |

### Fler länder eller EU senare

En ny källa i Lexifinas format behöver en rad i `build/corpora.json` och en adapter som `se.py`
(etiketter, register, länkar). `lexifina.py` och datamodellen bryr sig inte om land: varje ändring bär sin
corpus-id (t.ex. `se/national/acts`). Gränssnittet visar i dag bara ett publicerat corpus, i roten;
bygget säger ifrån om fler slås på, så att URL-strukturen (t.ex. `/eu/...`) beslutas medvetet då.

### Förklaringar senare

Varje ändring i `data/upcoming.json` har fältet `explanation: null`, och sidmallen har en plats för den
(`Site.explanation`), tydligt märkt "Förklaring – inte lagtext". Den visas bara när fältet har innehåll.

## Versioner

`ÅÅÅÅ.MM.DD.N`, till exempel `2026.11.07.1`, där N räknas upp vid flera byggen samma dag. `version.json`
anger också källarkivets commit för `main` och `future`, kodens commit och när datan senast kontrollerades.

## Publicering (GitHub Pages i en fork)

1. Forka `lexifina/sweden-law` och lägg den här koden på en egen **föräldralös** gren
   (`git checkout --orphan lexahead`) i forken. Annars checkar varje körning ut ~115 000 lagtextfiler.
2. Gör `lexahead` till förvald gren (Settings → Branches). Schemalagda körningar går bara på förvald gren.
3. Settings → Pages → Source: **GitHub Actions**.
4. Actions-fliken: aktivera arbetsflöden (de är avstängda som standard i forkar).
5. Kör arbetsflödet *lexAhead* en gång manuellt.

Arbetsflödet körs varje timme men bygger bara om källan, koden eller datumet ändrats. Det synkar också forkens
`main`/`future` med originalet och håller schemat vid liv (GitHub pausar annars schemat efter 60 dagar).

## Tillgänglighet

Mål: WCAG 2.2 AA. Kontrollerat med axe-core (ljust och mörkt läge), tangentbord, 320 px bredd och utan JavaScript.
Ändringar markeras med genomstrykning och understrykning, aldrig bara färg, och har dold text för skärmläsare.

## Licens

Lagtexter: fria enligt upphovsrättslagen 1 kap. 9 §; källa ska anges ("Källa: Sveriges riksdag").
Lexifinas bidrag: CC0. Typsnitt: IBM Plex, SIL Open Font License (`static/fonts/OFL.txt`).
