# RememberBot - Agent Rules

Diese Datei enthält projektspezifische Verhaltensregeln und Standard-Anweisungen für den AI-Agenten in diesem Workspace.

## 1. Backend (Python / FastAPI)
- Halte dich an den PEP 8 Standard für Python-Code.
- Nutze asynchrone Funktionen (`async def`), wo immer es bei FastAPI Sinn macht (z.B. bei allen I/O-Operationen, Dateizugriffen und Subprocess-Aufrufen).
- Respektiere die bestehende Architektur: Trennung zwischen API-Routen (`main.py`), CLI-Aufrufen (`agy_client.py`) und Speicherlogik (`storage.py`).
- **Live-Streaming:** Nutze für KI-Chat-Ausgaben standardmäßig Server-Sent Events (SSE via FastAPI `StreamingResponse` mit `text/event-stream`) und `agy --output-format stream-json`.
- **Session Lifecycle & Concurrency:** Registriere aktive Sessions unmittelbar beim Betreten des Endpoints in `_active_chat_sessions` (stets im `try ... finally: _active_chat_sessions.discard(...)`-Block), damit Status-Abfragen (`/api/sessions/{id}/status`) sofort `is_processing: true` melden und keine Polling-Race-Conditions entstehen.
- **Hintergrund-Absicherung:** Sichere KI-Verarbeitung und Persistierungsschritte mit `asyncio.shield` gegen Verbindungsabbrüche ab, damit der Chat-Verlauf bei einem Tab-Schließen nicht korrumpiert wird.

## 2. Frontend (Vanilla Web-Technologien)
- Verwende **keine** Frontend-Frameworks wie React, Vue oder Angular.
- Schreibe sauberes, modernes Vanilla JavaScript (ES6+).
- Nutze reguläres CSS (Vanilla CSS). Verwende **kein** TailwindCSS, es sei denn, es wird explizit gefordert.
- **DOM-Schutz bei aktiven Submits:** `selectSession()`, Hintergrund-Polling oder `visibilitychange` dürfen den Chat-Container niemals leeren (`innerHTML = ''`), während eine Nachricht aktiv gesendet/gestreamt wird (`activeSubmittingSessionId`).
- **Streaming-Verarbeitung:** Verwende für SSE-Streams die `ReadableStream`-API (`response.body.getReader()`) und formatiere `<thought>`-Gedankengänge progressiv als einklappbare `<details class="ai-reasoning">`-Elemente.

## 3. Testing
- Verfolge bei allen Code-Änderungen strikt den **Test-Driven Development (TDD)** Ansatz (Red, Green, Refactor):
  1. **Red:** Schreibe oder aktualisiere zuerst die Tests, bevor du Implementierungsänderungen vornimmst. Führe die Tests aus und stelle sicher, dass sie fehlschlagen.
  2. **Green:** Implementiere den minimale Code-Menge, um die Tests erfolgreich passieren zu lassen. Führe die Tests erneut aus.
  3. **Refactor:** Räume den Code bei Bedarf auf, während alle Tests weiterhin grün bleiben.
- **Planungsvorgabe:** Wenn du mit dem `/plan` Befehl einen Implementierungsplan erstellst, strukturiere den Plan (insbesondere die "Proposed Changes") **immer explizit** in die drei TDD-Phasen (Phase 1: Red, Phase 2: Green, Phase 3: Refactor).
- Wenn neuer Code geschrieben wird, erstelle oder erweitere immer direkt die passenden Unit-Tests im `tests/` Ordner.
- Test-Framework ist `pytest`.

## 4. Allgemeine Richtlinien
- Bewahre die Integrität bestehender Kommentare und Docstrings, es sei denn, der Code ändert sich grundlegend.
- Füge für neue komplexe Funktionen oder Klassen aussagekräftige Docstrings hinzu.
- Schreibe Code-Kommentare auf Englisch (passend zum restlichen Code), kommuniziere mit dem Nutzer aber weiterhin auf Deutsch.
- Aktualisiere bei Änderungen die entsprechenden Texte in den Markdown-Dateien im `docs` Ordner und in der README.md.

## 5. Ausführung & Umgebung
- Führe **alle** Befehle (wie Tests, Skripte, Applikationsstart) immer streng über `docker compose` bzw. im Container aus. 
- Nutze auf dem Host-System keine nativen Tools wie `uv`, lokales `pip` oder lokales `python`.
- Beispiel für Tests: `docker compose run --rm web pytest tests/`
- **WSL & Test-Performance / Netzwerk-Hinweis:** Frage den Nutzer einmalig pro Session, ob er aktuell in WSL mit der CLI unterwegs ist. Falls ja, müssen Tests bzw. Container mit `network=host` (bzw. `--net=host`) gestartet werden (z. B. `docker compose run --rm --net=host web pytest tests/`), da sich die Tests andernfalls wegen NAT'ing-Problemen zwischen WSL und Docker-Container nicht beenden und ewig hängen.


