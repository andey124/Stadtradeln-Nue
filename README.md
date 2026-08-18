# 🚴 Dataciders Rennradeln — STADTRADELN 2026 Dashboard

Live-Dashboard zum Vergleich der Dataciders-Teams beim STADTRADELN 2026.
Nürnberg tritt an gegen die bereits abgeschlossenen Ergebnisse der anderen Standorte.

**👉 [Dashboard öffnen](https://andey124.github.io/Stadtradeln-Nue/)**

---

## Features

- 📊 **Kumulierter Kilometerverlauf** aller Dataciders-Teams in einem Chart
- 🏆 **Rennübersicht** mit Live-Rankings, Fortschrittsbalken und Überholungs-ETAs
- 📈 **Tages-km & 3-Intervall-Durchschnitt** für Nürnberg
- 👤 **km/Kopf-Vergleich** zwischen allen Teams
- 🎯 **"Nächstes Ziel"** — welches Team überholen wir als nächstes?
- ⏳ **Countdown** bis Event-Start / Event-Ende
- 🎉 **Meilenstein-Feed** — wann überholen wir wen?
- 📉 **Prognose-Endstand** basierend auf aktuellem Tempo

---

## Städte & Teams

| Stadt | Event-Zeitraum | Status |
|---|---|---|
| 🏠 Nürnberg | 15.06. – 05.07.2026 | **Live** |
| München | 15.06. – 05.07.2026 | **Live** |
| Berlin | 20.05. – 09.06.2026 | Abgeschlossen |
| Frankfurt/M | 01.05. – 21.05.2026 | Abgeschlossen |
| Dortmund | 03.05. – 23.05.2026 | Abgeschlossen |
| Stuttgart | 04.05. – 24.05.2026 | Abgeschlossen |
| Hennigsdorf | 09.05. – 29.05.2026 | Abgeschlossen |

---

## Setup

### 1. Repository forken / klonen

```bash
git clone https://github.com/YOUR-USERNAME/YOUR-REPO-NAME.git
cd YOUR-REPO-NAME
```

### 2. Team-Namen prüfen und anpassen

Falls die Teamnamen auf der STADTRADELN-Website leicht abweichen (z.B. "Dataciders Frankfurt am Main" statt "Dataciders Frankfurt"), anpassen in:

```
docs/data/teams.json
```

### 3. GitHub Pages aktivieren

In den Repo-Einstellungen unter **Settings → Pages**:
- Source: `Deploy from a branch`
- Branch: `main`, Verzeichnis: `/docs`

Das Dashboard ist dann erreichbar unter:
`https://YOUR-USERNAME.github.io/YOUR-REPO-NAME/`

### 4. GitHub Actions-Berechtigungen setzen

Unter **Settings → Actions → General → Workflow permissions**:
- "Read and write permissions" aktivieren ✅

Der Scraper läuft dann automatisch täglich um **08:00 und 18:00 Uhr CET**.

### 5. Manuellen ersten Scrape-Run auslösen

Unter **Actions → Scrape STADTRADELN Data → Run workflow**

---

## Lokale Entwicklung

```bash
# Dashboard lokal testen (Python-Server aus dem repo-root)
python -m http.server 8080
# Dann: http://localhost:8080/docs/
```

```bash
# Scraper lokal testen
pip install -r scripts/requirements.txt
playwright install chromium
python scripts/scrape.py
```

---

## Datenstruktur

```
docs/data/
├── teams.json        # Konfiguration aller Teams (Slug, Name, Zeitraum)
└── snapshots.json    # Zeitreihe aller Scrape-Ergebnisse
```

**`snapshots.json` Format:**
```json
{
  "snapshots": [
    {
      "timestamp": "2026-06-15T06:00:00Z",
      "team_id": "nuernberg",
      "sum_km": 1234.5,
      "rides": 42,
      "riders": 18,
      "km_per_head": 68.6
    }
  ],
  "last_updated": "2026-06-15T06:00:00Z"
}
```

---

## Architektur

```
.github/workflows/scrape.yml   ← GitHub Actions Cron (2× täglich)
scripts/scrape.py              ← Playwright-Scraper (headless Chrome)
scripts/requirements.txt       ← Python-Abhängigkeiten
docs/data/teams.json           ← Team-Konfiguration
docs/data/snapshots.json       ← Gesammelte Zeitreihendaten
docs/index.html                ← Statisches Dashboard (Chart.js)
```

Der Scraper navigiert auf jede Städte-Leaderboard-Seite (`stadtradeln.de/{city-slug}`),
sucht nach der entsprechenden Team-Zeile und speichert die Daten als JSON-Zeitreihe.
GitHub Pages serviert das statische Dashboard, das die JSON-Daten direkt lädt.

---

## Lizenz

Der eigene Quellcode und die Dokumentation stehen unter der
[Apache License 2.0](LICENSE).

Die Daten unter `docs/data/` sind davon ausdrücklich ausgenommen. Das gilt
auch für sämtliche historischen Versionen dieser Dateien in der Git-Historie.
Für diese Daten werden durch dieses Repository keine Nutzungsrechte eingeräumt.
Namen, Logos und Marken Dritter, insbesondere STADTRADELN und Dataciders, sind
ebenfalls nicht lizenziert. Details stehen im [DATA_NOTICE](DATA_NOTICE).

---

*Powered by [STADTRADELN](https://www.stadtradeln.de) · Built with ❤️ by Dataciders Nürnberg*
