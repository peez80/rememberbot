# Spezifikation: RememberBot

## 1. Einleitung
Die Anwendung ist ein generischer, agentischer KI-Chat mit persistentem Gedächtnis. Ziel ist es, dem Benutzer eine einfache und intuitive Möglichkeit zu bieten, Informationen, Logs oder beliebige Daten zu erfassen und abzurufen. Die Erfassung erfolgt über ein Chat-Interface, das eine natürliche Interaktion ermöglicht. (Ursprünglich als Ernährungstagebuch gestartet, fungiert die App nun als vielseitiger KI-Agent).

## 2. Hauptfunktionen

### 2.1 Chat-Interface
- Die zentrale Benutzeroberfläche der Anwendung ist ein Chat.
- Der Benutzer kann hier wie in einer Messenger-App Eingaben tätigen und sieht den Verlauf.
- **Responsive Layout:** Die Chat-Oberfläche muss sowohl auf Desktop-Rechnern als auch auf mobilen Endgeräten (Smartphones, Tablets) optimal dargestellt werden und nutzbar sein.

### 2.2 Dateneingabe und Logging
- **Texteingabe:** Der Benutzer kann in natürlicher Sprache beliebige Informationen eingeben, die der Agent verarbeiten und speichern soll.
- **Kamera-Integration (Smartphone):** Öffnet der Benutzer die Web-App auf dem Smartphone, kann er direkt über die Kamerafunktion Fotos aufnehmen (z.B. von Dokumenten, Gegenständen oder Mahlzeiten).
- **Foto-Upload (Galerie/Dateisystem):** Zusätzlich können bereits vorhandene Fotos direkt in den Chat hochgeladen werden.
- Bei Bildeingaben wird die KI genutzt, um die Fotos zu analysieren und strukturierte Daten automatisch zu extrahieren.

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
- **Bildverarbeitung & Uploads:** Hochgeladene Bilder werden persistent im Upload-Ordner der Session gespeichert (`/uploads/{session_id}/{filename}`) und als Bildpfade an `agy` übergeben. Mobile Kamera-Uploads ohne Dateiendung erhalten automatisch einen sicheren `.jpg`-Fallback.
- **UI-Stabilität & Concurrency-Schutz:**
  - Sofortige Persistierung der Nutzernachricht (`save_session_message`) im Endpoint sichert Texte und hochgeladene Bilder dauerhaft, selbst wenn der Nutzer den Chat unmittelbar wechselt oder die Verbindung abbricht.
  - Hintergrund-Absicherung der KI-Verarbeitung und Persistierung via `asyncio.shield`.
  - Sofortige Registrierung aktiver Submits (`activeSubmittingSessionId`) und Request-Sequenzzähler (`selectSessionCounter`) schützen den Chat-Container vor DOM-Wipes durch parallele `visibilitychange`-Events oder verzögerte Hintergrund-Fetches.
  - Erhalt der Sidebar-DOM-Struktur zur Vermeidung von Flackern beim Session-Wechsel.
- **agy Parameter:** Es werden Standardparameter (`--prompt`, `--output-format stream-json`, `--dangerously-skip-permissions`) verwendet. Der Aufruf ist in der Klasse `AgyClient` gekapselt.


