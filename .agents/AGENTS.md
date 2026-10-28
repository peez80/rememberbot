# RememberBot - Agent Rules

Diese Datei enthält projektspezifische Verhaltensregeln und Standard-Anweisungen für den AI-Agenten in diesem Workspace.

## 1. Backend (Python / FastAPI)
- Halte dich an den PEP 8 Standard für Python-Code.
- Nutze asynchrone Funktionen (`async def`), wo immer es bei FastAPI Sinn macht (z.B. bei allen I/O-Operationen, Dateizugriffen und Subprocess-Aufrufen).
- Respektiere die bestehende Architektur: Trennung zwischen API-Routen (`main.py`), CLI-Aufrufen (`agy_client.py`) und Speicherlogik (`storage.py`).
- **Live-Streaming:** Nutze für KI-Chat-Ausgaben standardmäßig Server-Sent Events (SSE via FastAPI `StreamingResponse` mit `text/event-stream`) und `agy --output-format stream-json`.
- **Session Lifecycle & Concurrency:** Registriere aktive Sessions unmittelbar beim Betreten des Endpoints in `_active_chat_sessions` (stets im `try ... finally: _active_chat_sessions.discard(...)`-Block), damit Status-Abfragen (`/api/sessions/{id}/status`) sofort `is_processing: true` melden und keine Polling-Race-Conditions entstehen.
- **Hintergrund-Absicherung:** Sichere KI-Verarbeitung und Persistierungsschritte mit `asyncio.shield` gegen Verbindungsabbrüche ab, damit der Chat-Verlauf bei einem Tab-Schließen nicht korrumpiert wird.
- **Logging & Error Observability:**
  - **Zero Silent Failures:** Fange niemals Fehler lautlos ab (`except Exception: pass` oder `except: continue` ohne Logging ist strikt verboten). Jeder abgefangene Fehler oder Ausnahmefall muss mit aussagekräftigem Kontext (Pfad, Username, Session-ID) und Traceback protokolliert werden.
  - **Log-Level-Standards:**
    - `logger.error`: Bei internen 500-Fehlern, I/O-/Dateisystem-Schreibfehlern, Subprozess-Abstürzen oder Ausnahmen in Hintergrund-Tasks (stets mit `exc_info=True`).
    - `logger.warning`: Bei 4xx-Clientfehlern (z.B. ungültige Schemas 422, unbefugter Zugriff 401/403, Path-Traversal 400, nicht gefundene Ressourcen 404) und tolerierten Einzeldateifehlern mit Fallback.
    - `logger.info`: Bei wesentlichen Lifecycle-Ereignissen (Session erstellt/gelöscht/umbenannt, Login/Logout, Client-Disconnects).
    - `logger.debug`: Bei internen Ablauf-Details und Befehlsaufrufen.
  - **Datenschutz & Security:** Schreibe **niemals** sensible Daten (wie Klartext-Passwörter, Session-Tokens oder API-Schlüssel) in Log-Ausgaben.
  - **Background Tasks & Subprocesses:** Alle via `fire_and_forget` gestarteten Hintergrund-Tasks müssen Exceptions über einen Done-Callback loggen. Bei Subprozessen (`agy`) muss bei Fehler-Exit (`returncode != 0`) stets `stderr` ausgelesen und geloggt werden.

## 2. Frontend (Vanilla Web-Technologien)
- Verwende **keine** Frontend-Frameworks wie React, Vue oder Angular.
- Schreibe sauberes, modernes Vanilla JavaScript (ES6+).
- Nutze reguläres CSS (Vanilla CSS). Verwende **kein** TailwindCSS, es sei denn, es wird explizit gefordert.
- **DOM-Schutz bei aktiven Submits:** `selectSession()`, Hintergrund-Polling oder `visibilitychange` dürfen den Chat-Container niemals leeren (`innerHTML = ''`), während eine Nachricht aktiv gesendet/gestreamt wird (`activeSubmittingSessionId`).
- **Streaming-Verarbeitung:** Verwende für SSE-Streams die `ReadableStream`-API (`response.body.getReader()`) und formatiere `<thought>`-Gedankengänge progressiv als einklappbare `<details class="ai-reasoning">`-Elemente.
- **DOM- & Interaktions-Testpflicht für UI-Komponenten:** Interaktive Frontend-Features (z. B. aufklappbare Thinking-Boxen, Modals, Session-Wechsel, Upload-Vorschauen) dürfen nicht ausschließlich durch Python-String-Mocks getestet werden. Sie müssen durch automatisierte Browser-Tests (Playwright) auf echtes DOM-Verhalten (Klicks, Streaming-Zustände, CSS-Sichtbarkeit) abgesichert sein.

## 3. Testing & Planungsmethodik
- Verfolge bei allen Code-Änderungen strikt den **Test-Driven Development (TDD)** Ansatz (Red, Green, Refactor):
  1. **Red:** Schreibe oder aktualisiere zuerst die Tests, bevor du Implementierungsänderungen vornimmst. Führe die Tests aus und stelle sicher, dass sie fehlschlagen.
  2. **Green:** Implementiere den minimale Code-Menge, um die Tests erfolgreich passieren zu lassen. Führe die Tests erneut aus.
  3. **Refactor:** Räume den Code bei Bedarf auf, während alle Tests weiterhin grün bleiben.
- **Refactoring-Sicherheit & Invarianten-Erhalt:**
  - **Baseline First (Charakterisierungs-Tests):** Vor dem Refaktorisieren oder Aufteilen bestehender Dateien/Module müssen die bestehenden Verhaltensweisen und UI-Elemente durch automatisierte Tests abgedeckt sein. Fehlen diese Tests, müssen sie VOR dem Refactoring geschrieben und verifiziert werden.
  - **Diff-Audit vor Fertigstellung:** Vor dem Abschluss einer Implementierung MUSS der gesamte `git diff` gezielt auf unbeabsichtigte Löschungen oder Seiteneffekte geprüft werden:
    - Wurden CSS-Variablen, Klassen oder Selektoren entfernt oder farblich entwertet?
    - Gingen beim Zerlegen von JavaScript-Dateien Event-Listener, DOM-Zustände (`open`, `disabled`, `classList`) oder Error-Handler verloren?
    - Wurden Backend-Prompts, Flag-Auflösungen oder Rückgabewerte versehentlich aufgeweicht?
  - **Kern-Invarianten-Checkliste (RememberBot):**
    Vor jeder Fertigmeldung von Frontend-, Streaming- oder CSS-Änderungen muss geprüft werden, ob folgende Kern-Invarianten unberührt und funktionsfähig geblieben sind:
    1. *Thinking Box:* Ist die `<details class="ai-reasoning">`-Box sichtbar, hat sie Kontrast und bleibt sie bei Nutzerklick während des Streamings offen?
    2. *Chat-Streaming & Input:* Funktionieren Absenden, Typing Indicator, Autoscroll und Streaming-Abbruch?
    3. *Session-Integrität:* Bleiben Chatverläufe beim Wechseln zwischen Sessions und nach Seiten-Reload erhalten?
- **Planungsvorgaben & Planungsphase (Immer-Pflicht, auch ohne `/plan`):**
  - **Ausführliche Planung auch im normalen Modus:** Die detaillierte Planungsphase ist bei jeder nicht-trivialen Code-Änderung oder Fehlerbehebung **ausnahmslos Pflicht** – selbst wenn der Nutzer keinen `/plan`-Befehl verwendet hat.
  - **Verhalten ohne Plan-Modus (Autonome Umsetzung nach Plan):** Befindet sich der Agent nicht im interaktiven Plan-Modus, wird der ausführliche Implementierungsplan (inkl. TDD-Phasen, betroffenen Modulen, Invarianten und Verifikationsschritten) zunächst vollständig erstellt und anschließend **direkt und autonom umgesetzt**, ohne vorab auf eine gesonderte Freigabe durch den Nutzer zu warten (es sei denn, grundlegende architektonische Design-Entscheidungen oder Unklarheiten erfordern eine Klärung).
  - Strukturiere den Plan (insbesondere die "Proposed Changes") **immer explizit** in die drei TDD-Phasen (Phase 1: Red, Phase 2: Green, Phase 3: Refactor).
  - **Strikte Einhaltung des TDD-Zyklus (Red-Phase erzwingen):** Bevor auch nur eine Zeile produktiver Code geändert wird, MUSS zuerst ein entsprechender Test geschrieben/angepasst und ausgeführt werden, der den Fehler oder die fehlende Funktionalität reproduziert (Red). Erst nach bestätigtem Fehlschlag folgt die minimale Implementierung (Green).
  - **Lösungsraum & Trade-Offs vorab abstimmen:** Bei architektonischen oder Performance-relevanten Weichenstellungen nicht vorschnell einen einzigen Pfad festlegen, sondern vorab 2–3 Alternativen mit ihren Trade-Offs (z. B. Latenz, Token-Overhead, Dateisystem-I/O vs. CLI-Flags) gegenüberstellen und mit dem Nutzer abstimmen.
  - **Historischen Kontext & Altdaten hinterfragen:** Vor früheren Architekturentscheidungen innehalten (z. B. warum eine Datei statt CLI-Prompt genutzt wurde -> Vermeidung von `ARG_MAX`-Limits). Systematisch prüfen: Was passiert mit bereits existierenden Sessions, importierten ZIP-Dateien oder leeren Anfangszuständen? Keine voreiligen Vereinfachungen (wie Abschneiden/Truncation), wenn voller Kontext benötigt wird.
  - **Mentale Simulation (Schrittweiser Walkthrough):** Vor Beginn der Umsetzung den Datenfluss und Lifecycle für alle konkreten Szenarien gedanklich Schritt für Schritt durchspielen (z. B. Turn 1 neue Session, Turn 2+ neue Session, bestehende Session Turn 1 Seeding, bestehende Session Turn 2+, Fallback bei gelöschtem State). Erst wenn alle Pfade gedanklich fehlerfrei aufgehen, mit Phase 1 (Red) starten.
- Wenn neuer Code geschrieben wird, erstelle oder erweitere immer direkt die passenden Tests im entsprechenden Ordner (`tests/unit/`, `tests/integration/` oder `tests/e2e/`).
- **Logging-Verifikation:** Teste Fehlerbehandlungs-Routen und Ausnahme-Pfade mit dem Pytest-Fixture `caplog`, um sicherzustellen, dass die definierten Log-Einträge im Fehlerfall zuverlässig generiert werden.
- Test-Framework ist `pytest`. Die Test-Suite ist in 3 Ebenen unterteilt (`unit/`, `integration/`, `e2e/`), die auch über Marker (`pytest -m unit`, `-m integration`, `-m e2e`) angesprochen werden können.

## Validierung des Implementierungsplans
Verification steps, all mandatory:

1. Components fit together: all files, scripts, docs and callers affected by the change are listed
   (use grep to find hard-coded references to what is being changed).
2. Completeness: every component is fully planned, no "TBD" or implicit steps.
3. Syntax and semantics: commands, config keys and file formats are correct. Run available
   checks (e.g. `kubectl kustomize`, `bash -n`) when possible.
4. External facts: check against official documentation or the internet. Comparing with
   existing files in the repo does not count as verification.

Every plan must end with a `## Verification` section stating, per step, what was checked and how,
and which assumptions could not be verified (and why). A plan without this section is incomplete.

## 4. Allgemeine Richtlinien
- Bewahre die Integrität bestehender Kommentare und Docstrings, es sei denn, der Code ändert sich grundlegend.
- Füge für neue komplexe Funktionen oder Klassen aussagekräftige Docstrings hinzu.
- Schreibe Code-Kommentare auf Englisch (passend zum restlichen Code), kommuniziere mit dem Nutzer aber weiterhin auf Deutsch.
- Aktualisiere bei Änderungen die entsprechenden Texte in den Markdown-Dateien im `docs` Ordner und in der README.md.

## 5. Ausführung & Umgebung
- Führe **alle** Befehle (wie Tests, Skripte, Applikationsstart) immer streng über `docker compose` bzw. im Container aus. 
- Nutze auf dem Host-System keine nativen Tools wie `uv`, lokales `pip` oder lokales `python`.
- Beispiel für Tests: `docker compose run --rm web pytest tests/unit` (Unit), `docker compose run --rm web pytest tests/integration` (API/Integration), `docker compose run --rm web pytest tests/e2e` (E2E Browser), oder `docker compose run --rm web pytest tests/` (Gesamtsuite).
- **WSL & Test-Performance / Netzwerk-Hinweis:** Gehe standardmäßig immer davon aus, dass **nicht** in WSL gearbeitet wird (Befehle also normal ohne `--net=host` ausführen). Falls etwas unerwartet nicht funktioniert oder Tests hängen bleiben, obwohl sie eigentlich funktionieren sollten, versuche den Befehl zuerst mit `--net=host` (z. B. `docker compose run --rm --net=host web pytest tests/`). Erst wenn auch dies fehlschlägt oder das Problem weiterhin besteht, frage den Nutzer nach der WSL-Umgebung.
