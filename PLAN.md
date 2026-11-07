# Plan: Kommande lagändringar – insyn för alla

## Context
Sveriges lagar finns som git-repo (`lexifina/sweden-law`). Branchen `future` innehåller beslutade ändringar som ännu inte trätt i kraft. Målet är att göra dem begripliga för vem som helst: **tillgängligt** (WCAG 2.2 AA), **vackert** och **förklarande**. Förklarande text (varför/vad betyder det) skjuts till senare; nu bygger vi det som visar *vad* som ändras, exakt och utan tolkning.

Tidigare upptäckt: git-historiken på `main` har bara en commit per lag (ingen texthistorik). Men `future` har riktiga före/efter-diffar och `data/amendments.csv` har metadata. Det är de två källorna.

## Datakällor (verifierade)
| Källa | Innehåll | Används till |
|---|---|---|
| `git log main..future` (484 commits) | 427 `amendment`, 37 `enacted` (nya lagar), 17 `repeal`, 4 `unexplained`. 418 ändringsförfattningar, 46 ikraftdatum (247 st 2027-01-01). Trailers: `In-force`, `Amending-act`, `Affecting` (sökvägar). Diffen = gammal text (`/Upphör att gälla U:…/`) mot ny (`/Träder i kraft I:…/`) | Själva ändringarna, datum |
| `data/amendments.csv` | `amending_sfs`, `title`, `scope` ("ändr. 1 §; ny 5 §"), `preparatory_works` (prop./bet.) | Rubrik, sammanfattning i klartext, länk till förarbeten |
| `laws.csv` | titel, departement, status | Lagnamn, ansvarigt departement |
| `data/undated.csv` (623 markörer) | "den dag regeringen bestämmer" | Egen sektion: "Beslutat, datum ej satt" |

Koppling: `Amending-act` (trailer) ↔ `amending_sfs` (CSV). Sökväg `2008/567/kap-2/6.md` ↔ lag `2008:567`, 2 kap. 6 §.

## Arkitektur: bygg till statiska HTML-sidor
Ett byggskript (Python, endast stdlib, `-I`) läser repot och skriver färdig HTML. Ingen server, inget ramverk. Det ger bäst tillgänglighet (fungerar utan JS, skärmläsare, snabbt) och minst underhåll.

1. `build/extract.py` → `data/upcoming.json`: per ändringsförfattning `{sfs, titel, ikraft[], departement, kind, förarbeten, ändringar:[{lag, lagtitel, kap, paragraf, före[], efter[], scope}]}`. Före/efter tas ur diffen mellan `main` och `future` per fil; markörer (`/Upphör…/`, `/Träder…/`) rensas ur texten.
2. Ord-för-ord-diff görs **vid bygget** (`difflib`) och skrivs som `<del>`/`<ins>`-segment. Inget JS-diffbibliotek.
3. `build/render.py` → `site/` med mallar (Python `string.Template`/f-strängar; ingen mallmotor).

### Sidor
- `/` – **Översikt**: nästa ändringar först; densitetsremsa per månad (lista i HTML, inte canvas), "X ändringar 1 januari 2027". Filter (datum, departement, lag) via formulär som fungerar utan JS.
- `/datum/2027-01-01/` – allt som sker den dagen, grupperat på lag.
- `/lag/2008-567/` – alla kommande ändringar av en lag, i ordning.
- `/forfattning/2025-736/` – en ändringsförfattning: rubrik, vad den ändrar i klartext (genererad deterministiskt ur `scope`: "Ändrar 2 kap. 6 §", "Ny 5 §", "Upphävs"), före/efter-diff, länk till förarbeten och till officiell text.
- `/ej-satt-datum/` – de 623 odaterade.
- `/om/` – vad sidan är, källor, att den **inte är officiell**, snapshot-datum, hur man läser en diff.

### Plats för förklaringar (senare)
Datamodellen får fältet `forklaring: null` per ändring och mallen en dold plats för det. Inget byggs nu. När det kommer ska maskingenererad text märkas tydligt som sådan.

## Tillgänglighet (krav, inte tillval)
- WCAG 2.2 AA, `lang="sv"`, semantisk struktur (en `h1`, logisk rubriknivå, landmarks, "hoppa till innehåll").
- **Diff utan enbart färg**: `<ins>` understruken, `<del>` genomstruken, plus dolda skärmläsartexter ("Borttaget:", "Nytt:"). Kontrast ≥ 4.5:1 i ljust och mörkt läge (`prefers-color-scheme`).
- Allt tangentbordsnåbart, tydlig fokusmarkering, mål ≥ 24 px, text kan zoomas till 200 % och radbryts utan sidledsscroll, `prefers-reduced-motion` respekteras.
- Diagram/tidslinje alltid med textmotsvarighet (lista/tabell med `caption`).
- Klarspråk i gränssnittet; lagtext visas oförändrad men med läsvänlig radlängd (~65 tecken).

## Formgivning
Redaktionell, lugn och typografisk – inte "dashboard". Serif för lagtext, tydlig sans för gränssnitt, generös luft, tidslinje som huvudmotiv (framtiden som en horisont man scrollar mot). Vid bygget: ladda `impeccable` + `ui-ux-pro-max` + `unslop-ui` för att undvika generisk AI-estetik; prova två skisser innan vi låser.

## Steg
1. `extract.py` + test: antal commits/akter/datum stämmer mot siffrorna ovan (484/418/46).
2. Förhandsvisa `upcoming.json` för 5 handplockade fall (en ny lag, en upphävd, en `unexplained`, en med många paragrafer, en med tomt `scope`) – kontrollera mot källtexten.
3. `render.py` – sidmallar utan stil, validera HTML.
4. Stil + två designskisser → välj → färdigställ.
5. Tillgänglighetsgranskning (se nedan).
6. RSS-flöde (`/feed.xml`) ur samma `upcoming.json`.
7. Fork + GitHub Pages + Action (bygg, version, publicera), därefter schemalagd upstream-kontroll.

## Kända risker / kantfall
- **`unexplained` (4 st)**: ändring utan känd ändringsförfattning – visas med tydlig text, ingen gissad källa.
- **Nya lagar (`enacted`, 37) och upphävanden (`repeal`, 17)**: hel text respektive "upphör att gälla"; fungerar inte som vanlig diff.
- **Datum i dåtid**: snapshot är 2026-10-28; vissa ändringar (t.ex. 2026-11-01) har redan trätt i kraft. Sidan räknar "kommande" mot byggdatum.
- **CSV-luckor**: 25 % saknar `in_force` (mest gamla – irrelevant för framtida); `scope` är fri text, tolkningen får ett reservläge ("Ändrar bestämmelser") när mönstret inte känns igen.
- **Aktualitet**: datan är en ögonblicksbild. Automatisk ombyggnad vid ny commit i repot är ett senare steg.
- **Licens/ansvar**: kontrollera `LICENSE`/`SOURCES` i repot innan publicering; tydlig ansvarsfriskrivning på `/om/`.

## Verifiering
- Enhetstest för `extract.py` (antal, datum, par före/efter) och för tolkning av `scope`.
- Stickprov: 10 slumpade ändringar jämförs manuellt med `git diff main..future -- <fil>`.
- `axe-core`/`pa11y` över alla sidtyper, noll allvarliga fel.
- Manuellt: enbart tangentbord, VoiceOver (macOS), 200 % zoom, mobilbredd 320 px, mörkt läge, utan JS.
- Lighthouse tillgänglighet/prestanda ≥ 95.

## Beslut (från användaren)
- **Hosting: GitHub Pages**, via en **fork** av `lexifina/sweden-law`. Bygget körs som GitHub Action i forken och publicerar `site/` till Pages.
- **RSS ingår i v1**: `/feed.xml`, ett inlägg per ändringsförfattning och ikraftdatum (`guid` = `sfs@ikraft`), så nya kommande ändringar dyker upp som nya inlägg. (ICS-kalender kan komma efter.)
- **Automatisk ombyggnad när originalrepot uppdateras**, med datumbaserad versionering.

## Automatisk uppdatering och versionsnummer
Flöde: kolla om upstream `main`/`future` har nya commits → bygg om → publicera.
- **Rekommenderat första steg:** schemalagd GitHub Action i forken (`on: schedule`, t.ex. varje timme). Den kör `git ls-remote upstream main future`, jämför med SHA från förra bygget (sparad i `site/version.json`/cache) och bygger bara vid ändring. Ingen extra infrastruktur.
- **Worker (Cloudflare cron) bara om det behövs:** om Actions-schemat visar sig för trögt/opålitligt. Workern gör samma SHA-kontroll via GitHub API och triggar `workflow_dispatch` i forken. Notera: schemalagda Actions pausas efter ~60 dagars inaktivitet i ett repo, så bygget bör ändå skriva en commit/heartbeat, eller så tar Workern över.
- **Versionsnummer:** `ÅÅÅÅ.MM.DD` + löpnummer om flera bygg samma dag, plus upstream-SHA: t.ex. `2026.11.05.1+c4c432a`. Visas i sidfot, på `/om/`, i `version.json` och i RSS-flödets `<lastBuildDate>`/generator. Sidan visar även **datadatum** (senaste upstream-commit) separat från **byggdatum**, så att läsaren ser hur färsk informationen är.
- Upstream är stort (~115 000 filer): använd partiell klon/sparse checkout (`--filter=blob:none`) i Actionen, och hämta bara filer som `future` rör.

## Öppna frågor (påverkar inte planeringen nu)
- Sidans namn/domän.
- Licens: kontrollera `LICENSE`/`SOURCES` i upstream innan publicering (en fork är publik).
