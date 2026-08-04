# RememberBot - Agent Rules

Diese Datei enthält projektspezifische Verhaltensregeln und Standard-Anweisungen für den AI-Agenten in diesem Workspace.

## 1. Backend (Python / FastAPI)
- Halte dich an den PEP 8 Standard für Python-Code.
- Nutze asynchrone Funktionen (`async def`), wo immer es bei FastAPI Sinn macht (z.B. bei allen I/O-Operationen, Dateizugriffen und Subprocess-Aufrufen).
- Respektiere die bestehende Architektur: Trennung zwischen API-Routen (`main.py`), CLI-Aufrufen (`agy_client.py`) und Speicherlogik (`storage.py`).

## 2. Frontend (Vanilla Web-Technologien)
- Verwende **keine** Frontend-Frameworks wie React, Vue oder Angular.
- Schreibe sauberes, modernes Vanilla JavaScript (ES6+).
- Nutze reguläres CSS (Vanilla CSS). Verwende **kein** TailwindCSS, es sei denn, es wird explizit gefordert.

## 3. Testing
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


