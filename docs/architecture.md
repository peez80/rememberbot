# RememberBot - Architectural Blueprint & Design System

Dieses Dokument beschreibt die modulare, schichtenbasierte Architektur von **RememberBot**. Die Codebase folgt den Prinzipien des **Clean Architecture**-, **Domain-Driven Design (DDD)**- und **Test-Driven Development (TDD)**-Ansatzes.

---

## 1. Schichtenarchitektur (Overview)

```mermaid
graph TD
    subgraph Frontend ["Frontend (Vanilla ES Modules)"]
        UI_Main["main.js (Orchestrator)"]
        UI_Components["components/ (sidebar, chat, input, modals)"]
        UI_API["api/ (client.js, sse.js)"]
        UI_Utils["utils/ (dom, formatters, image)"]
        UI_State["state.js (Shared State)"]
        UI_Main --> UI_Components
        UI_Main --> UI_API
        UI_Main --> UI_State
        UI_Components --> UI_Utils
    end

    subgraph Backend ["Backend (FastAPI & Services)"]
        AppEntry["main.py (App Setup & Middlewares)"]
        
        subgraph Routers ["Routers (app/routers)"]
            R_Auth["routers/auth.py"]
            R_Sessions["routers/sessions.py"]
            R_Chat["routers/chat.py"]
            R_Files["routers/files.py"]
        end

        subgraph Facades ["Facades (Compatibility & Shared Locks)"]
            F_Storage["storage.py"]
            F_AGY["agy_client.py"]
        end

        subgraph Services ["Service Layer (app/services)"]
            S_Auth["auth_service.py"]
            S_UB["user_backends/ (base, json, factory)"]
            S_Session["session_service.py"]
            S_Chat["chat_service.py"]
            S_AGY["agy_service.py"]
            S_Storage["storage_service.py"]
            S_Auth --> S_UB
        end

        subgraph Core ["Core & Domain (app/core, app/models)"]
            C_Config["core/config.py"]
            C_Formatters["core/formatters.py"]
            C_Tasks["core/tasks.py (Supervisor)"]
            M_Domain["models/ (chat, session, auth)"]
        end
    end

    subgraph External ["External & Storage"]
        CLI["antigravity-cli (agy subprocess)"]
        Disk["Filesystem (DATA_DIR: JSON, Uploads, Thumbnails)"]
    end

    UI_API --> Routers
    AppEntry --> Routers
    Routers --> Services
    Facades --> Services
    Services --> Core
    Services --> M_Domain
    S_AGY --> CLI
    S_Storage --> Disk
```

---

## 2. Backend-Architektur

### 2.1 Core-Schicht (`app/core/`)
- **[`config.py`](file:///apps/app/core/config.py)**: Zentralisierte Konfiguration und Konstanten (Dateigrößenlimits, Timeout-Werte wie `ICON_GENERATION_TIMEOUT_SECONDS` [Standard: 180s], Security-Flags, Cookie-Attribute, Modell-Katalog `MODEL_CATALOG` und Standardwerte `AGY_DEFAULT_MODEL` [Standard: `gemini-3.8-flash`] / `AGY_DEFAULT_THINKING_EFFORT` [Standard: `medium`] mit `validate_model_and_effort()`).
- **[`formatters.py`](file:///apps/app/core/formatters.py)**: Reine Transformations- und Formatierungsfunktionen (z. B. `<thought>`-Folding, Markdown-Pfad-Umschreibung, SVG-Sanitization).
- **[`tasks.py`](file:///apps/app/core/tasks.py)**: `BackgroundSupervisor` für Task-Tracking, Session-Locking und Exception-Logging bei Hintergrundoperationen (`fire_and_forget`).

### 2.2 Domain-Modelle (`app/models/`)
- **[`chat.py`](file:///apps/app/models/chat.py)**: `ChatMessage`, `AttachmentMeta`, `ChatStatusResponse`.
- **[`session.py`](file:///apps/app/models/session.py)**: `SessionMetadata`, `SessionSettings`, `SessionSettingsRequest` (inkl. `model` und `thinking_effort`), `SessionCreateResponse`.
- **[`auth.py`](file:///apps/app/models/auth.py)**: `LoginRequest`, `AuthStatusResponse`.

### 2.3 Service-Schicht (`app/services/`)
- **[`auth_service.py`](file:///apps/app/services/auth_service.py)**: Kapselt Session-Token-Lebenszyklus, Cookie-Verwaltung und Rate-Limiting gegen Brute-Force-Angriffe. Delegiert die Verifikation von Zugangsdaten an die konfigurierte Benutzerbackend-Schicht.
- **[`user_backends/`](file:///apps/app/services/user_backends/)**: Modulare Authentifizierungs- und Benutzerquellen:
  - `base.py`: Abstrakter Vertrag `BaseUserBackend(ABC)` mit `is_oauth` und `is_password_supported` Flags.
  - `json_backend.py`: Dateibasiertes Backend für `users.json` mit `secrets.compare_digest`.
  - `oauth_backend.py`: OAuth2 / OpenID Connect Backend (`OAuthUserBackend`), delegiert Passwort-Authentifizierung ab und authentifiziert Benutzer über OIDC Identity Provider (z.B. Nextcloud).
  - `factory.py`: Zentrale Registry (`USER_BACKEND_REGISTRY`) und Fabrikfunktion `get_user_backend()` (gesteuert durch `USER_BACKEND`, Optionen: `json`, `file`, `oauth`, `oidc`, `nextcloud`).
- **[`oauth/`](file:///apps/app/services/oauth/)**: Kapselt OAuth2 & OpenID Connect:
  - `client.py`: Asynchroner `OAuthClient` mit automatischer OIDC Discovery (`.well-known/openid-configuration`), PKCE (RFC 7636, S256), State-Validierung (RFC 6749), Code Exchange, UserInfo-Abruf und robuster Claim-Extraktion (`preferred_username` -> `sub` -> `email`) inklusive Path-Traversal-Sanitization für Benutzerordner.
- **[`storage_service.py`](file:///apps/app/services/storage_service.py)**: Verantwortlich für atomare JSON-Schreibzugriffe (mit Temp-Files und `os.replace`), Dateisystem-Locks, On-Demand-Thumbnail-Erstellung und temporäre Bereinigungen.
- **[`session_service.py`](file:///apps/app/services/session_service.py)**: Verwaltet Session-Lebenszyklen (CRUD), Einstellungs- und Titel-Updates, Historienverwaltung, Upload-Persistierung mit PIL-Dimensionsextraktion (`save_user_attachments`) und ZipSlip-geschützte ZIP-Exporte/Importe mit automatischer URL- und Pfad-Remappung.
- **[`agy_service.py`](file:///apps/app/services/agy_service.py)**: Kapselt die `agy`-CLI-Subprozess-Ausführung mit nativer Session-Fortführung (`--conversation <id>`), One-Time-History-Seeding bei bestehenden/importierten Sessions, DB-Prüfung (`conversation_exists`), dynamischer Parameterübergabe (`--model`, `--effort`), NDJSON-Stream-Parsing und SVG-Avatar-Generierung.
- **[`chat_service.py`](file:///apps/app/services/chat_service.py)**: Orchestriert die Konversationslogik über eine deduplizierte Lifecycle-Pipeline (`_prepare_chat_turn` für Historie/Seeding/Prompting und `_finalize_chat_turn` für Link-Formatierung, Icon-Trigger und Persistierung) sowohl für Non-Streaming als auch für SSE-Token-Streams.

### 2.4 Fassaden-Schicht (`app/storage.py` & `app/agy_client.py`)
- **[`storage.py`](file:///apps/app/storage.py)**: Transparente Fassade, die historische Aufrufe direkt an die kanonischen Instanzen von `storage_service` und `session_service` delegiert und sicherstellt, dass alle Komponenten dieselben Concurrency-Locks (`session_locks`) teilen.
- **[`agy_client.py`](file:///apps/app/agy_client.py)**: Transparente Fassade, die Aufrufe an `AGYService` weiterleitet und Rückwärtskompatibilität für bestehende Aufrufer und Test-Mocks wahrt.

### 2.5 Router-Schicht (`app/routers/`)
- **[`auth.py`](file:///apps/app/routers/auth.py)**: Endpunkte für Login, Logout, Authentifizierungsstatus (`/api/auth/*`) sowie OAuth2-Endpoints (`/api/auth/oauth/login`, `/api/auth/oauth/callback`).
- **[`sessions.py`](file:///apps/app/routers/sessions.py)**: Endpunkte für Session-Management, Status, Historie, Einstellungen, Titel, Icons, Modell-Katalog (`GET /api/sessions/models/catalog`) sowie Export und Import (`/api/sessions/*`).
- **[`chat.py`](file:///apps/app/routers/chat.py)**: Endpunkt für Chat-Nachrichten und SSE-Streaming (`/api/sessions/{id}/chat`), delegiert Upload-Verarbeitung und Turn-Generierung vollständig an die Services.
- **[`files.py`](file:///apps/app/routers/files.py)**: Datei- und Thumbnail-Auslieferung (`/uploads/*`, `/app/data/*`).

### 2.6 Orchestrator (`app/main.py`)
- Initialisiert FastAPI, globale Exception-Handler, HTTP-Security-Header, bindet die Router ein und validiert beim Anwendungsstart via Lifespan-Event die Standard-Modell- und Thinking-Konfiguration gegen `agy`.

---

## 3. Frontend-Architektur (Native ES Modules)

Das Frontend verzichtet auf schwere Frameworks und Build-Tools und setzt auf moderne, native ECMAScript-Module (`type="module"`):

- **[`main.js`](file:///apps/app/static/js/main.js)**: Zentraler Application Orchestrator, dynamische Thinking-Effort-Optionen, Header-Modell-Badge, Event-Bus-Verbindung und entkoppelte SSE-Stream-Steuerung via `chatView`-Lifecycle-Methoden.
- **[`state.js`](file:///apps/app/static/js/state.js)**: Zentraler, reaktiver UI-State (aktive Session, Submit-Locks, Nachrichten-Batches, Anhänge).
- **[`api/client.js`](file:///apps/app/static/js/api/client.js)**: REST-Client mit globaler 401-Authentifizierungs-Abfanglogik und Modellkatalog-Abruf.
- **[`api/sse.js`](file:///apps/app/static/js/api/sse.js)**: Streaming-Reader für Server-Sent Events via `ReadableStream`.
- **[`components/chat_view.js`](file:///apps/app/static/js/components/chat_view.js)**: Rendern von Nachrichten, Markdown, `<details class="ai-reasoning">`-Blöcken, Dateikarten, Infinite-Scroll sowie Kapselung des SSE-Streaming-Lifecycles (`initStreamingMessage`, `updateStreamingMessage`, `finalizeStreamingMessage`, `removeStreamingMessage`) mit zustandsstabiler Aufklapp-Verwaltung (`manuallyOpened`) während des Streamings.
- **[`components/sidebar_view.js`](file:///apps/app/static/js/components/sidebar_view.js)**: Session-Listenanzeige, Icon-Rendering, Löschen und Aktiv-Indikator.
- **[`components/input_bar.js`](file:///apps/app/static/js/components/input_bar.js)**: Textarea-Auto-Resize, Drag-and-Drop, Paste und clientseitige Bildkompression (Canvas).
- **[`components/modals.js`](file:///apps/app/static/js/components/modals.js)**: Login-Modal (dynamische Umschaltung zwischen klassischem Passwort-Formular und OAuth SSO Button), Einstellungs-Dialog (Modell & Thinking Effort Auswahl mit dynamischen Validierungshinweisen), asynchrones Export-Status-Modal (Ladeanzeige während der ZIP-Generierung auf dem Server, automatisches Schließen bei Download-Start, Abbruch- und Fehlerbehandlung) sowie Import-Status-Modal (4-Schritte-Checkliste mit Upload-Fortschritt, Verifikation, Medien-Remapping, Session-Reload, Abbruch- und Inline-Fehlerbehandlung).
- **[`utils/dom.js`](file:///apps/app/static/js/utils/dom.js)**, **[`utils/formatters.js`](file:///apps/app/static/js/utils/formatters.js)**, **[`utils/image.js`](file:///apps/app/static/js/utils/image.js)**: DOM-Sicherheit (XSS-Schutz), Dateitypen und Bild-Optimierung.

---

## 4. Sicherheit & Robustheit

1. **Zero Silent Failures**: Jeder Ausnahmefall wird mit strukturiertem Kontext und Traceback protokolliert.
2. **Hintergrund-Absicherung**: SSE-Streams und Hintergrundaufgaben laufen bei Verbindungsabbrüchen via `asyncio.shield` und `BackgroundSupervisor` fehlerfrei bis zur Persistierung durch.
3. **ZipSlip- & Zip-Bomb-Schutz**: ZIP-Importe weisen bösartige Pfade (`..` oder absolute Pfade) strikt ab und begrenzen das dekomprimierte Gesamtvolumen (max. 10.000 MB) sowie die Dateianzahl (max. 10.000 Dateien), um Archiv-Dekompressionsexplosionen (Zip Bombs) zu verhindern. Import-Uploads werden im Router speicherschonend gestreamt (Chunked Reading, max. 2000 MB) zur Vermeidung von OOM-DoS.
4. **Session-ID Strict Validation**: Alle API-Routen, Storage-Funktionen und `agy`-Prüfungen validieren Session-IDs strikt gegen ein Regex-Muster (`^[a-zA-Z0-9_-]{1,64}$`), wodurch Path Traversal und Subdirectory-Injection vollständig ausgeschlossen sind.
5. **Defense-in-Depth File & Thumbnail Serving**: Alle Datei-Auslieferungen (`/uploads/*`, `/uploads/*/thumbnails/*`, `/app/data/*`) erzwingen restriktive HTTP-Security-Header (`Content-Security-Policy: default-src 'none'; sandbox` und `X-Content-Type-Options: nosniff`), um XSS durch manipulierte SVG-, HTML- oder Bilddateien zu unterbinden.
6. **XSS- & SVG-Sanitization**: Vollständige Bereinigung über DOMPurify mit Subresource Integrity (SRI) im Frontend, sichere URL-Schema-Validierung gegen `javascript:`-Links und serverseitige SVG-Prüfung (`defusedxml`/Regex).
7. **Timing-Attack-Schutz**: Benutzerpasswörter werden mittels `secrets.compare_digest` mit konstanter Ausführungszeit abgeglichen.
8. **OAuth 2.0 / OIDC Härtung (RFC 6749, RFC 7636)**: PKCE (S256 Code Challenge/Verifier) schützt vor Authorization Code Interception; kryptographische State-Tokens mit 10-Minuten TTL verhindern CSRF; Username-Claims werden strikt gegen Path-Traversal gesäubert (`..` und illegale Zeichen werden entfernt), bevor Benutzerverzeichnisse erstellt werden.

---

## 5. Caching- & Cache-Busting-Architektur

Die Caching-Strategie von RememberBot ist auf maximale Performance (Zero-Byte Revalidierung) und vollständige Stale-Cache-Prävention ausgelegt:

1. **`GET /` (`index.html`)**:
   - Antwortet mit `Cache-Control: no-cache, no-store, must-revalidate`.
   - Injiziert serverseitig in `serve_index()` dynamische Cache-Busting-Query-Parameter (`?v=<mtime>`) für `styles.css`, `main.js` und `favicon.png`.
2. **Statische Assets (`/static/**`)**:
   - Werden über die angepasste Klasse `NoCacheStaticFiles` mit `Cache-Control: no-cache` ausgeliefert.
   - Ermöglicht dem Browser, modulare Vanilla-ES-Dateien (`state.js`, `components/*.js`, `utils/*.js`, `api/*.js`) im lokalen Disk-Cache vorzuhalten, zwingt ihn jedoch zur Revalidierung via `ETag` (`If-None-Match`). Bei unveränderten Dateien antwortet der Server mit `304 Not Modified` (< 1 ms Latenz, 0 Bytes Payload). Bei Dateiänderungen wird der neue Stand sofort mit `200 OK` geladen.
3. **Icons & dynamische Session-Dateien**:
   - `/api/sessions/{id}/icon` und `/app/data/...`: Werden mit `Cache-Control: no-cache, must-revalidate` ausgeliefert, sodass neu generierte Avatare oder Workspace-Dateien sofort aktualisiert werden.
4. **Unveränderliche Medien (Uploads & Thumbnails)**:
   - `/uploads/{id}/...`: Werden mit `Cache-Control: public, max-age=31536000, immutable` dauerhaft gecacht, da Dateinamen eindeutige Content-/Zufallspräfixe tragen.

