# Claude Setup – Dateizugriff auf Originaldateien

## Was das hier ist
Diese Datei erklärt Claude (in zukünftigen Chats), wie er direkten Zugriff
auf alle Projektdateien bekommt – ohne ZIP-Upload, ohne Umwege.

---

## Voraussetzung: Claude in Chrome Extension

Der Dateizugriff funktioniert über das **Filesystem MCP** der
**Claude in Chrome** Browser-Extension.

- Extension muss installiert und aktiv sein
- Claude muss im Browser via claude.ai geöffnet sein
- Das Filesystem MCP muss in den Extension-Einstellungen aktiviert sein

---

## Projektpfad (Originaldateien)

```
C:\Users\phili\Documents\GitHub\copybot
```

Alle Lese- und Schreiboperationen laufen direkt auf diesem Pfad.

---

## Anweisung für Claude (am Chat-Anfang ausführen)

Wenn ein neuer Chat gestartet wird, führe folgende Schritte aus:

1. **Filesystem-Tool laden:**
   Rufe `tool_search` mit dem Query `"filesystem read write"` auf,
   um die Filesystem-Tools zu aktivieren.

2. **Projektstruktur einlesen:**
   ```
   filesystem:list_directory → C:\Users\phili\Documents\GitHub\copybot
   ```

3. **Snapshot laden:**
   ```
   filesystem:read_file → C:\Users\phili\Documents\GitHub\copybot\SNAPSHOT_2026-04-27.md
   ```
   *(Dateiname ggf. auf neuesten Snapshot anpassen)*

4. **Wichtige Kerndateien lesen:**
   ```
   C:\Users\phili\Documents\GitHub\copybot\bot\main.py
   C:\Users\phili\Documents\GitHub\copybot\bot\config\network.py
   C:\Users\phili\Documents\GitHub\copybot\bot\runners\wallet_analysis.py
   ```

---

## Berechtigungen

Claude hat über das Filesystem MCP folgende Rechte:

| Aktion        | Erlaubt |
|---------------|---------|
| Dateien lesen | ✅      |
| Dateien schreiben / bearbeiten | ✅ |
| Neue Dateien erstellen | ✅ |
| Verzeichnisse auflisten | ✅ |
| Dateien löschen | ❌ (nicht unterstützt) |

**Wichtig:** Änderungen wirken sofort auf die Originaldateien.
Vor größeren Edits immer kurz bestätigen lassen.

---

## Snapshot-Workflow

Nach jeder Session wird ein neuer Snapshot erstellt:

```
C:\Users\phili\Documents\GitHub\copybot\SNAPSHOT_YYYY-MM-DD.md
```

Den aktuellsten Snapshot immer zu Beginn eines neuen Chats laden –
er enthält den kompletten Projektstand, offene TODOs und Performance-Daten.

---

## Kurzversion für den Chat-Einstieg

Einfach diese Nachricht an Claude schicken:

> Lade den Snapshot `SNAPSHOT_YYYY-MM-DD.md` und richte dir den
> Dateizugriff auf `C:\Users\phili\Documents\GitHub\copybot` ein.
> Du hast alle Lese- und Schreibrechte über das Filesystem MCP.
