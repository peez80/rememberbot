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

### 2.5 Modell- & Thinking-Effort-Konfiguration
- **Katalogunterstützung:** Der Benutzer kann für jede Chat-Sitzung flexibel das KI-Modell und die Thinking-Tiefe (Reasoning Effort) festlegen.
- **Unterstützte Modelle:** Google Gemini (`gemini-3.8-flash`, `gemini-3.7-flash`, `gemini-3.1-pro`), Anthropic Claude (`claude-sonnet-4-6`, `claude-opus-4-6-thinking`) und Open-Source-Modelle (`gpt-oss-120b-medium`).
- **Thinking Effort:** Für Modelle mit nativer Thinking-Unterstützung (`supports_thinking: true`) können Stufen wie `low`, `medium` oder `high` gewählt werden (Gemini 3.1 Pro: `low`/`high`; Flash: `low`/`medium`/`high`). Modelle ohne Thinking-Effort-Support lassen das Flag automatisch aus.
- **Header-Badge & Einstellungen:** Das aktive Modell und die Denkstufe werden als Badge im Chat-Header angezeigt und können über das Einstellungs-Zahnrad (`[ ⚙️ ]`) angepasst werden.

### 2.6 Multi-User-Authentifizierung & Sicherheit
- **Benutzerverwaltung:** Das System unterstützt isolierte Multi-User-Instanzen über eine serverseitige Konfigurationsdatei (`data/config/users.json`).
- **Session-Cookies:** Sichere Authentifizierung über `HttpOnly`- und `SameSite=Lax`-Cookies mit Rate-Limiting gegen Brute-Force-Angriffe.
- **Isolierte Datenräume:** Jeder Benutzer greift ausschließlich auf seine eigenen Sitzungen, Dateien und Konversationen zu (`data/{username}/sessions/`).

## 3. Technische Anforderungen

### 3.1 Technologie-Stack
- **Backend:** FastAPI (Python) mit asynchronem I/O und Server-Sent Events (`StreamingResponse`).
- **Frontend:** Unkompliziertes Setup mit modernem Vanilla HTML/JS/CSS, Markdown-Rendering (`marked`) und DOM-Sanitizing (`DOMPurify`).
- **KI-Integration:** Ausführen von `agy` mit NDJSON-Streaming (`--output-format stream-json`) aus dem Backend heraus.

### 3.2 Infrastruktur & Deployment (Full-Docker Setup)
- Die gesamte Anwendung wird per Docker deployed.
- **Entwicklung & Administration:** Es handelt sich um ein Full-Docker Setup. Alle administrativen oder entwicklungsbezogenen lokalen Aktivitäten werden im Docker-Container ausgeführt. Auf dem Host-System (Entwickler-Laptop) muss kein spezielles Python installiert werden.

### 3.3 Datenhaltung
- **Speicherort:** Der Docker-Container erhält ein Volume-Mount sowie eine zugehörige Environment-Variable (z. B. `DATA_DIR`), in der der Basis-Speicherpfad definiert ist (Standard: `/app/data`, gemountet von `./_rememberbot_data`).
- **Multi-User-Verzeichnisstruktur:** Alle Daten werden strikt pro Benutzer und Chat-Sitzung isoliert:
  ```text
  /app/data/
  ├── config/
  │   └── users.json                  # Benutzerdatenbank für Authentifizierung
  └── {username}/
      └── sessions/
          └── {session_id}/
              ├── session.json        # Vollständige Session-Daten & Nachrichtenverlauf
              ├── icon.svg            # Generierter Session-Avatar
              ├── uploads/            # Hochgeladene Benutzer-Dateien & Bilder
              ├── thumbnails/         # On-Demand generierte Web-Thumbnails (JPEG)
              └── data/               # Vom KI-Agenten erstellte Workspace-Dateien
  ```
- **Atomare Persistierung:** Schreibzugriffe auf `session.json` und Konfigurationsdateien erfolgen atomar über temporäre Zwischendateien (`.tmp.<uuid>`) und `os.replace` mit synchronisierter Verzeichnisspülung (`os.sync`), um Beschädigungen bei Stromausfällen oder Container-Neustarts auszuschließen.
- **Zentralisierte Concurrency-Locks:** Alle Lese- und Schreiboperationen auf Session-Ebene werden durch `storage_service.session_locks[session_id]` serialisiert.

## 4. Gelöste Architektur-Entscheidungen
- **Docker Setup:** Ein Multi-Stage Dockerfile trennt das schlanke `production`-Image (FastAPI, uvicorn, `agy`-CLI, reine Laufzeit-Dependencies) vom `test`-Image (Playwright, Chromium-Binaries, Pytest). Dadurch bleibt das im Deployment/CI ausgelieferte Image minimal groß, während alle Tests vollständig ausgeführt werden können.
- **JSON Schema:** Das Datenmodell (`SessionData`) bildet die Chat-Sitzung, Metadaten und Konversationseinstellungen vollständig ab:
  ```json
  {
    "id": "c1f7a2...",
    "title": "Projektplanung",
    "created_at": "2026-09-28T12:00:00Z",
    "system_prompt": "Optionaler benutzerspezifischer System-Prompt",
    "include_gps": false,
    "model": "gemini-3.8-flash",
    "thinking_effort": "medium",
    "agy_conversation_id": "conv-987...",
    "history": [
      {
        "text": "User-Nachricht",
        "is_user": true,
        "images": [{"url": "/uploads/...", "width": 800, "height": 600}],
        "files": [{"url": "/uploads/...", "name": "daten.csv", "size": 1024, "is_image": false}],
        "timestamp": "2026-09-28T12:00:05Z"
      },
      {
        "text": "KI-Antwort mit [Generierter Datei](ergebnis.csv)",
        "is_user": false,
        "images": [],
        "timestamp": "2026-09-28T12:00:15Z"
      }
    ]
  }
  ```
- **Chat Kontext & Streaming:** Um Latenz und Token-Overhead zu minimieren, nutzt das Backend die native Session-Fortführung von `antigravity-cli` via `--conversation <conversation_id>`. Neue Sessions starten nativ ohne Datei-Overhead; die von `agy` im `init`-Event gemeldete `conversation_id` wird in `session.json` (`agy_conversation_id`) persistiert. Bestehende oder importierte Sessions werden beim ersten Turn einmalig über eine temporäre Datei (`chat_context_*.txt`) mit der vollständigen Historie geseedet, um CLI-Längenbeschränkungen (`ARG_MAX`) zu vermeiden, und laufen ab Turn 2 nativ. Bei fehlender lokaler agy-Konversation erfolgt ein automatischer Fallback mit Re-Seeding. Antworten werden über `stream-json` als NDJSON gestreamt und per SSE an den Browser weitergeleitet.
- **Entkoppelte Hintergrund-Ausführung & Persistierung bei Disconnect:**
  - Die KI-Generierung (`stream_message`), Nachbearbeitung (Markdown-Link-Korrektur, `<thinking>`-Gedankengänge mit interaktions-stabiler `<details class="ai-reasoning">`-Aufklappverwaltung) und Speicherung (`save_session_message`) laufen in einem eigenständigen, entkoppelten `asyncio.Task` im Hintergrund (`_active_tasks`).
  - Der SSE-Endpoint konsumiert Tokens aus einer `asyncio.Queue`. Schließt der Benutzer den Browser/Tab, bricht nur die SSE-Verbindung ab – der Hintergrund-Task läuft zuverlässig bis zum Ende durch, speichert die vollständige KI-Antwort in `session.json` und hält den Status `is_processing: true` in `_active_chat_sessions` bis zur Fertigstellung aktiv.
  - Bei erneuter Sitzungsauswahl oder Reconnect erkennt das Frontend den Hintergrundstatus via Polling und lädt die Antwort nahtlos nach.
- **Datei- & Bildverarbeitung, Uploads & Thumbnail-Caching:**
  - Hochgeladene Dateien und Bilder werden persistent im Upload-Ordner der Session gespeichert (`/uploads/{session_id}/{unique_filename}`) mit kollisionssicherem UUID-Präfix und als strukturierte Dateipfade an `agy` übergeben. Mobile Kamera-Uploads ohne Dateiendung erhalten automatisch einen sicheren Bild-Fallback.
  - Über `/uploads/{session_id}/{filename}` können hochgeladene Dateien mit bereinigtem Originalnamen (`Content-Disposition: attachment; filename=...`) heruntergeladen werden.
  - Bild-Uploads und Thumbnails werden mit aggressiven HTTP-Cache-Headern (`Cache-Control: public, max-age=31536000, immutable`) ausgeliefert.
  - **On-Demand Thumbnails:** Über `/uploads/{session_id}/thumbnails/{filename}` werden dynamisch und idempotent optimierte Web-Thumbnails (max. 400px, JPEG Quality 80, EXIF-Transposition & Alpha-Kanal-Kompensierung) generiert und in einem separaten `thumbnails/`-Unterordner abgelegt. Thumbnails können jederzeit gefahrlos gelöscht und bei Bedarf neu erzeugt werden. Im Chat klickt der Nutzer auf das Thumbnail, um das Originalbild in einem neuen Tab (`_blank`) zu öffnen. Nicht-Bilddateien werden als übersichtliche Dateikarten mit Typ-Icon und Downloadlink dargestellt.
  - **KI-generierte Workspace-Dateien & Download-Buttons:**
    - Generierte Dateien werden im persistenten Arbeitsverzeichnis der Session (`/app/data/{username}/sessions/{session_id}/data`) abgelegt.
    - Der System-Prompt (`technical_prompt`) instruiert `agy`, generierte Dateien verbindlich dort zu speichern, im Fließtext als `[datei.ext](datei.ext)` zu verlinken, keine Leerzeichen zwischen den Klammern zu setzen und niemals Platzhalter oder Formatbeispiele an den Nutzer auszugeben.
    - [`format_local_links`](file:///apps/app/core/formatters.py) normalisiert eventuelle Whitespaces zwischen Klammern (`[text] (url)` zu `[text](url)`), ignoriert typische Platzhalter-Dateinamen (`dateiname.*`, `filename.*`, `beispiel.*`), schreibt relative Dateinamen, Rohpfade (`/app/data/{username}/sessions/{session_id}/data/...`) und Erwähnungen existierender Workspace-Dateien in sichere API-Download-Pfade (`/app/data/{username}/{session_id}/data/{file}`) um.
    - Das Frontend ([`formatThoughtBlocks`](file:///apps/app/static/js/utils/formatters.js)) normalisiert Link-Syntax auch bei historischen Chatverläufen vor dem Markdown-Parsing, stattet gerenderte Links mobilfreundlich mit `target="_blank"` und `download`-Attributen aus ([`enhanceMarkdownLinksAndImages`](file:///apps/app/static/js/utils/formatters.js)) und erzeugt für alle im Text vorkommenden Download-Pfade (unter Ausschluss von Platzhaltern wie `Dateiname.pdf`) automatisch interaktive `.download-btn`-Buttons unter der Nachrichtenblase ([`attachDownloadButtons`](file:///apps/app/static/js/utils/formatters.js)).
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
  - **Sicherheit, ZipSlip- & Zip-Bomb-Schutz:** Strenges Abweisen bösartiger Pfade mit relativen Pfadkomponenten (`..`) oder absoluten Pfaden beim Entpacken. Schutz vor Denial-of-Service durch speicherschonendes Chunk-Streaming beim Upload (max. 50 MB) und Limitierung des unkomprimierten Gesamtvolumens auf maximal 150 MB.
  - **Universelles Remapping & URL-Sanitization:** Vollständiges und automatisches Umschreiben aller Session-IDs, Benutzernamen, lokaler Dateipfade (`files[i].path`) und Markdown-Verlinkungen (`/uploads/...`, `/app/data/...`) im Nachrichtentext auf die Ziel-Session und den Ziel-Benutzer. Striktes Verwerfen unsicherer URL-Schemata (`javascript:`, `data:`) in Historien-Links.
  - **Session-ID Härtung:** Alle Endpunkte und internen Pfadoperationen validieren die Session-ID strikt über `is_safe_session_id` gegen das Regex `^[a-zA-Z0-9_-]{1,64}$`.
  - **agy Parameter:** Es werden Standardparameter (`--prompt`, `--output-format stream-json`, `--dangerously-skip-permissions` sowie optional `--conversation <conversation_id>` zur nativen Kontextfortführung, `--model` und `--effort`) verwendet. Der Aufruf ist im kanonischen Service `AGYService` (`app/services/agy_service.py`) gekapselt (mit `AgyClient` in `app/agy_client.py` als transparenter Fassade).
- **Schichtenarchitektur & Entkopplung:** Strikte Trennung zwischen API-Routen (`app/routers/`), Service-Layer (`app/services/`), Core/Domain-Modellen (`app/core/`, `app/models/`) und atomaren Storage-Primitiven. `storage.py` und `agy_client.py` dienen als schlanke, abwärtskompatible Fassaden.
- **Avatar-/Icon-Generierung:** SVG-Icon-Erstellung (`generate_chat_icon`) im modernen App-Icon-Stil (`viewBox="0 0 100 100"`, `rx="22"`, zentriertes Vektor-Piktogramm ohne Text, themenbezogene Farben). Die Generierung erfolgt asynchron nach Abschluss der ersten KI-Antwort (unter Einbeziehung von Titel, Benutzeranfrage und KI-Antwort als Kontext) sowie bei jeder nachträglichen Titeländerung. Der Aufruf nutzt `--effort low` und `--disable-slash-commands` zur schnellen Erstellung, bereinigt eventuelle Reasoning-Tags (`<thought>`) vor dem SVG-Parsing und protokolliert `stderr` bei Fehlern. Bei einem Generierungsfehler wird keine fehlerhafte Fallback-Datei gespeichert, sodass das Standard-Icon erhalten bleibt und erneute Versuche möglich sind.


