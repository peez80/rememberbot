# Spezifikation: RememberBot

## 1. Einleitung
Die Anwendung ist ein generischer, agentischer KI-Chat mit persistentem Gedächtnis. Ziel ist es, dem Benutzer eine einfache und intuitive Möglichkeit zu bieten, Informationen, Logs oder beliebige Daten zu erfassen und abzurufen. Die Erfassung erfolgt über ein Chat-Interface, das eine natürliche Interaktion ermöglicht. (Ursprünglich als Ernährungstagebuch gestartet, fungiert die App nun als vielseitiger KI-Agent).

## 2. Hauptfunktionen

### 2.1 Chat-Interface
- Die zentrale Benutzeroberfläche der Anwendung ist ein Chat.
- Der Benutzer kann hier wie in einer Messenger-App Eingaben tätigen und sieht den Verlauf.
- **Responsive Layout:** Die Chat-Oberfläche muss sowohl auf Desktop-Rechnern als auch auf mobilen Endgeräten (Smartphones, Tablets) optimal dargestellt werden und nutzbar sein.

### 2.2 Dateneingabe, Logging und Datei-Uploads
- **Texteingabe:** Der Benutzer kann in natürlicher Sprache beliebige Informationen eingeben, die der Agent verarbeiten und speichern soll.
- **Dateianhänge (Universal File Upload):** Über einen Büroklammer-Button (`[ 📎 ]`), Drag-and-Drop oder die Zwischenablage (Paste) können beliebige Dateien (PDFs, Text-/Code-Dateien, CSVs, Tabellen, Archive etc.) in den Kontext geladen werden. Der KI-Agent erhält die absoluten Dateipfade und kann den Dateiinhalt mit Tools inspizieren und auswerten.
- **Kamera-Integration (Smartphone):** Öffnet der Benutzer die Web-App auf dem Smartphone, kann er direkt über den Kamera-Button (`[ 📷 ]`) Fotos aufnehmen (z.B. von Dokumenten, Gegenständen oder Mahlzeiten).
- **Foto-Upload (Galerie):** Über den Galerie-Button (`[ 🖼️ ]`) können gezielt Fotos und Grafiken ausgewählt und hochgeladen werden.
- Bei Bildeingaben wird die KI genutzt, um die Fotos zu analysieren und strukturierte Daten automatisch zu extrahieren. Nicht-Bilddateien werden als herunterladbare Dateikarten im Chatverlauf angezeigt.

### 2.3 Datenkorrelation und Kontext
- Der Benutzer kann über den Chat komplexe Zusammenhänge erfassen und abfragen.
- Ziel ist es, dass der Agent diese Informationen persistent speichert und über verschiedene Chat-Sitzungen hinweg korrelieren kann (z.B. für Auswertungen oder Analysen).

### 2.4 KI-Backend (`antigravity-cli`)
- Die Verarbeitung der Eingaben (Textverständnis, Bilderkennung und Antwortgenerierung) erfolgt über das Kommandozeilen-Tool `antigravity-cli` (Kommando: `agy`).
- Die Python Web-App ruft das Tool lokal via asynchronem Subprozess auf (`asyncio.create_subprocess_exec`), übergibt den Kontext (Text oder Dateipfade zu Bildern) und verarbeitet die Ausgabe in Echtzeit.
- Die Textgenerierung erfolgt über Live-Token-Streaming (`agy --output-format stream-json`), wobei Chunks per Server-Sent Events (SSE) an das Frontend gestreamt und dort progressiv als Markdown gerendert werden.

## 3. Technische Anforderungen

### 3.1 Technologie-Stack
- **Backend:** FastAPI (Python) mit asynchronem I/O und Server-Sent Events (`StreamingResponse`).
- **Frontend:** Unkompliziertes Setup mit modernem Vanilla HTML/JS/CSS, Markdown-Rendering (`marked`) und DOM-Sanitizing (`DOMPurify`).
- **KI-Integration:** Ausführen von `agy` mit NDJSON-Streaming (`--output-format stream-json`) aus dem Backend heraus.

### 3.2 Infrastruktur & Deployment (Full-Docker Setup)
- Die gesamte Anwendung wird per Docker deployed.
- **Entwicklung & Administration:** Es handelt sich um ein Full-Docker Setup. Alle administrativen oder entwicklungsbezogenen lokalen Aktivitäten werden im Docker-Container ausgeführt. Auf dem Host-System (Entwickler-Laptop) muss kein spezielles Python installiert werden.

### 3.3 Datenhaltung
- **Speicherort:** Der Docker-Container erhält ein Volume-Mount sowie eine zugehörige Environment-Variable (z. B. `DATA_DIR`), in der der Speicherpfad definiert ist.
- **Format & Struktur:** Pro Eintrag (jede Aktion, jedes Log) wird eine eigene JSON-Datei angelegt.
- **Ordnerstruktur:** Die JSON-Dateien werden nach Monat gruppiert in Unterverzeichnissen abgelegt (Format: `YYYY-MM`).
- **Dateinamen:** Zur sauberen Sortierung erhält jede JSON-Datei als Präfix einen ISO-Timestamp (z. B. `2026-07-05T21:20:45Z_record.json`).

## 4. Gelöste Architektur-Entscheidungen
- **Docker Setup:** Ein Multi-Stage Dockerfile trennt das schlanke `production`-Image (FastAPI, uvicorn, `agy`-CLI, reine Laufzeit-Dependencies) vom `test`-Image (Playwright, Chromium-Binaries, Pytest). Dadurch bleibt das im Deployment/CI ausgelieferte Image minimal groß, während alle Tests vollständig ausgeführt werden können.
- **JSON Schema:** Es wird ein generisches Schema verwendet (z.B. `{"type": "record", "timestamp": "...", "raw_input": "...", "data": {...}}`), anpassbar an den jeweiligen Kontext.
- **Chat Kontext & Streaming:** Das Backend pflegt die Chat-Historie und übergibt den vollständigen bisherigen Kontext in einer temporären Datei an `agy`. Antworten werden über `stream-json` als NDJSON gestreamt und per SSE an den Browser weitergeleitet.
- **Entkoppelte Hintergrund-Ausführung & Persistierung bei Disconnect:**
  - Die KI-Generierung (`stream_message`), Nachbearbeitung (Markdown-Link-Korrektur, `<thinking>`-Gedankengänge) und Speicherung (`save_session_message`) laufen in einem eigenständigen, entkoppelten `asyncio.Task` im Hintergrund (`_active_tasks`).
  - Der SSE-Endpoint konsumiert Tokens aus einer `asyncio.Queue`. Schließt der Benutzer den Browser/Tab, bricht nur die SSE-Verbindung ab – der Hintergrund-Task läuft zuverlässig bis zum Ende durch, speichert die vollständige KI-Antwort in `session.json` und hält den Status `is_processing: true` in `_active_chat_sessions` bis zur Fertigstellung aktiv.
  - Bei erneuter Sitzungsauswahl oder Reconnect erkennt das Frontend den Hintergrundstatus via Polling und lädt die Antwort nahtlos nach.
- **Datei- & Bildverarbeitung, Uploads & Thumbnail-Caching:**
  - Hochgeladene Dateien und Bilder werden persistent im Upload-Ordner der Session gespeichert (`/uploads/{session_id}/{unique_filename}`) mit kollisionssicherem UUID-Präfix und als strukturierte Dateipfade an `agy` übergeben. Mobile Kamera-Uploads ohne Dateiendung erhalten automatisch einen sicheren Bild-Fallback.
  - Über `/uploads/{session_id}/{filename}` können hochgeladene Dateien mit bereinigtem Originalnamen (`Content-Disposition: attachment; filename=...`) heruntergeladen werden.
  - Bild-Uploads und Thumbnails werden mit aggressiven HTTP-Cache-Headern (`Cache-Control: public, max-age=31536000, immutable`) ausgeliefert.
  - **On-Demand Thumbnails:** Über `/uploads/{session_id}/thumbnails/{filename}` werden dynamisch und idempotent optimierte Web-Thumbnails (max. 400px, JPEG Quality 80, EXIF-Transposition & Alpha-Kanal-Kompensierung) generiert und in einem separaten `thumbnails/`-Unterordner abgelegt. Thumbnails können jederzeit gefahrlos gelöscht und bei Bedarf neu erzeugt werden. Im Chat klickt der Nutzer auf das Thumbnail, um das Originalbild in einem neuen Tab (`_blank`) zu öffnen. Nicht-Bilddateien werden als übersichtliche Dateikarten mit Typ-Icon und Downloadlink dargestellt.
- **Performance & Progressives Chat-Laden:**
  - **O(1) Session-Validierung:** API-Routen und Polling-Ticks validieren Sessions über `check_session_exists` und `get_session_title` per direktem Dateipfad-Check in $O(1)$, anstatt alle vorhandenen Sessions und Chatverläufe mit $O(N \cdot M)$ wiederholt von der Festplatte zu parsen.
  - **Progressives Frontend-Rendering & Infinite Scroll:** Beim Öffnen langer Chats rendert das Frontend sofort die jüngsten 20 Nachrichten und lädt ältere Nachrichten nahtlos nach (Trigger bei `< 100px` vor dem oberen Rand), wodurch DOM-Größe, Layout-Berechnungszeiten und Speicherbedarf minimal bleiben.
- **UI-Stabilität & Concurrency-Schutz:**
  - Sofortige Persistierung der Nutzernachricht (`save_session_message`) im Endpoint sichert Texte und hochgeladene Bilder dauerhaft, selbst wenn der Nutzer den Chat unmittelbar wechselt oder die Verbindung abbricht.
  - Hintergrund-Absicherung der KI-Verarbeitung und Persistierung via `asyncio.shield`.
  - Sofortige Registrierung aktiver Submits (`activeSubmittingSessionId`) und Request-Sequenzzähler (`selectSessionCounter`) schützen den Chat-Container vor DOM-Wipes durch parallele `visibilitychange`-Events oder verzögerte Hintergrund-Fetches.
  - Erhalt der Sidebar-DOM-Struktur zur Vermeidung von Flackern beim Session-Wechsel.
- **Fehlerbehandlung & Observability:**
  - **Globale Exception-Handler:** Zentrales Abfangen unbehandelter 500-Fehler (`logger.error` mit vollem Stacktrace), Pydantic-Validierungsfehler (422 mit Feldinformationen) und HTTP-Exceptions (4xx/5xx).
  - **Keine lautlosen Fehler (Zero Silent Failures):** Vollständige Fehlerprotokollierung aller I/O- und JSON-Operationen im Storage-Layer (`storage.py`) sowie Stderr-Erfassung bei CLI-Stream-Abbrüchen (`agy_client.py`).
  - **CLI-Lifecycle-Logging:** Transparente Protokollierung von Start (PID, Modus/Versuch) und Ende (gemessene Ausführungszeit in Sekunden, Exit-Code) aller `agy`-CLI-Subprozesse auf `INFO`-Level.
  - **Hintergrund-Task-Überwachung:** Abfangen und Loggen von Ausnahmen in `fire_and_forget`-Tasks via Done-Callback.
- **Session Export & Import (ZIP-Archiv) & Portabilität:**
  - **Kompakte Archivierung:** Vollständiger Export einer Chat-Session als ZIP-Archiv inklusive `session.json`, `icon.svg` (falls vorhanden), aller hochgeladenen Dokumente/Bilder (`uploads/`) und KI-generierter Ergebnisdateien (`data/`). Wiederherstellbare Zwischendateien (`thumbnails/`) werden zur Einsparung von Archivgröße und Speicherplatz explizit ausgeschlossen.
  - **Sicherheit & ZipSlip-Schutz:** Strenges Abweisen bösartiger Pfade mit relativen Pfadkomponenten (`..`) oder absoluten Pfaden beim Entpacken.
  - **Universelles Remapping:** Vollständiges und automatisches Umschreiben aller Session-IDs, Benutzernamen, lokaler Dateipfade (`files[i].path`) und Markdown-Verlinkungen (`/uploads/...`, `/app/data/...`) im Nachrichtentext auf die Ziel-Session und den Ziel-Benutzer.
  - **Kontextsensitive UI-Steuerung:** Im Einstellungs-Modal (`Chat-Einstellungen`) ist der Export-Button immer verfügbar, der Import-Button wird zur Vermeidung versehentlichen Datenverlusts ausschließlich bei neuen Chats mit leerem Verlauf angezeigt.
- **agy Parameter:** Es werden Standardparameter (`--prompt`, `--output-format stream-json`, `--dangerously-skip-permissions`) verwendet. Der Aufruf ist in der Klasse `AgyClient` gekapselt.
- **Avatar-/Icon-Generierung:** SVG-Icon-Erstellung (`generate_chat_icon`) mit zentral konfigurierbarem Timeout von 180 Sekunden (`ICON_GENERATION_TIMEOUT_SECONDS`) und automatischem Fallback.


