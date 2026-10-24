import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.services.agy_service import AGYService

@pytest.fixture
def agy_service():
    return AGYService()

@pytest.mark.asyncio
async def test_agy_service_generate_chat_icon(agy_service, tmp_path):
    target_path = str(tmp_path / "icon.svg")
    
    mock_process = AsyncMock()
    mock_process.communicate.return_value = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="40"/></svg>', b'')
    mock_process.returncode = 0
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        await agy_service.generate_chat_icon(
            title="Meeting Notes",
            output_path=target_path,
            user_context="Besprechung über Roadmap",
            ai_context="Hier ist die Zusammenfassung der Meilensteine"
        )
        
    import os
    assert os.path.exists(target_path)
    with open(target_path, "r", encoding="utf-8") as f:
        content = f.read()
        assert "<circle" in content

    mock_exec.assert_called_once()
    called_cmd = mock_exec.call_args[0]
    assert "--effort" in called_cmd
    effort_idx = called_cmd.index("--effort")
    assert called_cmd[effort_idx + 1] == "low"
    assert "--disable-slash-commands" in called_cmd


@pytest.mark.asyncio
async def test_agy_service_generate_chat_icon_timeout_uses_configured_constant(agy_service, tmp_path, caplog):
    import os
    import logging
    import asyncio
    from app.core.config import ICON_GENERATION_TIMEOUT_SECONDS

    target_path = str(tmp_path / "icon.svg")
    mock_process = AsyncMock()
    mock_process.communicate = AsyncMock(return_value=(b"", b""))
    mock_process.kill = MagicMock()

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()) as mock_wait_for:
            with caplog.at_level(logging.WARNING):
                await agy_service.generate_chat_icon("Meeting Notes", target_path)

            mock_wait_for.assert_called_once()
            call_kwargs = mock_wait_for.call_args[1]
            assert call_kwargs.get("timeout") == ICON_GENERATION_TIMEOUT_SECONDS
            assert ICON_GENERATION_TIMEOUT_SECONDS == 180.0
            assert mock_process.kill.called
            # No fallback file created on timeout
            assert not os.path.exists(target_path)
            assert f"timed out after {ICON_GENERATION_TIMEOUT_SECONDS}s" in caplog.text


@pytest.mark.asyncio
async def test_agy_service_generate_chat_icon_failure_logs_stderr(agy_service, tmp_path, caplog):
    import os
    import logging

    target_path = str(tmp_path / "icon.svg")
    mock_process = MagicMock()
    async def mock_comm():
        return (b"", b"Fatal CLI error")
    mock_process.communicate = mock_comm
    mock_process.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        with caplog.at_level(logging.ERROR):
            await agy_service.generate_chat_icon("Meeting Notes", target_path)

    assert not os.path.exists(target_path)
    assert "Fatal CLI error" in caplog.text



@pytest.mark.asyncio
async def test_generate_chat_icon_deduplicates_concurrent_calls_for_same_path(agy_service, tmp_path):
    import asyncio
    import os

    target_path = str(tmp_path / "icon.svg")
    mock_process = MagicMock()

    async def slow_communicate():
        await asyncio.sleep(0.05)
        return (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="40"/></svg>', b'')

    mock_process.communicate = slow_communicate
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        await asyncio.gather(
            agy_service.generate_chat_icon("Meeting Notes", target_path),
            agy_service.generate_chat_icon("Meeting Notes", target_path),
            agy_service.generate_chat_icon("Meeting Notes", target_path)
        )

    assert mock_exec.call_count == 1
    assert os.path.exists(target_path)


@pytest.mark.asyncio
async def test_generate_chat_icon_skips_existing_when_not_forced(agy_service, tmp_path):
    import os

    target_path = str(tmp_path / "icon.svg")
    with open(target_path, "w", encoding="utf-8") as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100"/></svg>')

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        await agy_service.generate_chat_icon("Neuer Titel", target_path, force=False)

    mock_exec.assert_not_called()


@pytest.mark.asyncio
async def test_generate_chat_icon_overwrites_existing_when_forced(agy_service, tmp_path):
    import os

    target_path = str(tmp_path / "icon.svg")
    with open(target_path, "w", encoding="utf-8") as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100"/></svg>')

    mock_process = AsyncMock()
    mock_process.communicate.return_value = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="35" fill="#10b981"/></svg>',
        b''
    )
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        await agy_service.generate_chat_icon("Aktualisierter Titel", target_path, force=True)

    mock_exec.assert_called_once()
    assert os.path.exists(target_path)
    with open(target_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "<circle" in content
    assert "#10b981" in content


@pytest.mark.asyncio
async def test_is_generating_icon_tracks_active_generation(agy_service, tmp_path):
    import asyncio

    target_path = str(tmp_path / "icon.svg")
    started_event = asyncio.Event()
    finish_event = asyncio.Event()

    mock_process = AsyncMock()

    async def controlled_communicate():
        started_event.set()
        await finish_event.wait()
        return (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="40"/></svg>', b'')

    mock_process.communicate.side_effect = controlled_communicate
    mock_process.returncode = 0

    assert agy_service.is_generating_icon(target_path) is False

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        task = asyncio.create_task(agy_service.generate_chat_icon("Live Check", target_path))
        await asyncio.wait_for(started_event.wait(), timeout=2.0)

        assert agy_service.is_generating_icon(target_path) is True

        finish_event.set()
        await task

    assert agy_service.is_generating_icon(target_path) is False


@pytest.mark.asyncio
async def test_get_model_catalog_timeout_and_fallback(agy_service, caplog):
    import asyncio
    import logging
    from app.core.config import MODEL_CATALOG

    # Clear catalog cache
    agy_service._model_catalog_cache = None

    mock_process = AsyncMock()
    mock_process.kill = MagicMock()

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
            with caplog.at_level(logging.WARNING):
                catalog = await agy_service.get_model_catalog()

    assert catalog == MODEL_CATALOG
    assert "Timeout beim Abrufen von 'agy models'" in caplog.text


@pytest.mark.asyncio
async def test_get_model_catalog_nonzero_and_unparseable(agy_service, caplog):
    import logging
    from app.core.config import MODEL_CATALOG

    # 1. Nonzero exit code
    agy_service._cached_model_catalog = None
    mock_nonzero = MagicMock()
    async def mock_nz_comm():
        return (b"", b"Unknown subcommand: models")
    mock_nonzero.communicate = mock_nz_comm
    mock_nonzero.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_nonzero):
        with caplog.at_level(logging.WARNING):
            catalog = await agy_service.get_model_catalog(force_refresh=True)
    assert catalog == MODEL_CATALOG
    assert "Exit-Code 1" in caplog.text

    # 2. Output with empty/no valid models
    agy_service._cached_model_catalog = None
    mock_empty = MagicMock()
    async def mock_empty_comm():
        return (b"No models found", b"")
    mock_empty.communicate = mock_empty_comm
    mock_empty.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_empty):
        with caplog.at_level(logging.WARNING):
            catalog = await agy_service.get_model_catalog(force_refresh=True)
    assert catalog == MODEL_CATALOG
    assert "Keine Modelle in der Ausgabe" in caplog.text


@pytest.mark.asyncio
async def test_stream_message_edge_cases(agy_service, caplog):
    import logging

    # 1. FileNotFoundError triggers mock stream
    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("agy not found")):
        with caplog.at_level(logging.WARNING):
            events = [ev async for ev in agy_service.stream_message([], "hello")]
    assert any(ev.get("type") == "done" for ev in events)
    assert "mock stream" in caplog.text.lower()

    # 2. Invalid non-JSON lines are ignored cleanly (logged as debug)
    mock_lines = [
        b'Invalid line that is not json\n',
        b'{"event":"step_update","step_update":{"text_delta":"Hi"}}\n',
        b'{"event":"result","result":{"response":"Hi"}}\n'
    ]
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    async def mock_readline():
        if mock_lines:
            return mock_lines.pop(0)
        return b''
    mock_proc.stdout.readline = mock_readline
    mock_proc.stderr.read = MagicMock(return_value=b'')
    async def mock_wait(): return 0
    mock_proc.wait = mock_wait

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with caplog.at_level(logging.DEBUG):
            events = [ev async for ev in agy_service.stream_message([], "hello")]
    assert any(ev.get("text") == "Hi" for ev in events)
    assert any(ev.get("type") == "done" for ev in events)

    # 3. Stream ending without result event falls back to accumulated done event
    mock_lines_no_result = [
        b'{"event":"step_update","step_update":{"text_delta":"Only delta"}}\n'
    ]
    mock_proc_no_result = MagicMock()
    mock_proc_no_result.returncode = 0
    async def mock_readline_no_result():
        if mock_lines_no_result:
            return mock_lines_no_result.pop(0)
        return b''
    mock_proc_no_result.stdout.readline = mock_readline_no_result
    mock_proc_no_result.stderr.read = MagicMock(return_value=b'')
    mock_proc_no_result.wait = mock_wait

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc_no_result):
        events = [ev async for ev in agy_service.stream_message([], "hello")]
    done_events = [ev for ev in events if ev.get("type") == "done"]
    assert len(done_events) == 1
    assert done_events[0]["reply"] == "Only delta"


@pytest.mark.asyncio
async def test_generate_chat_icon_invalid_svg_logged(agy_service, tmp_path, caplog):
    import logging
    import os

    target_path = str(tmp_path / "invalid_icon.svg")
    mock_process = AsyncMock()
    mock_process.communicate.return_value = (b"I am not an SVG format", b"")
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        with caplog.at_level(logging.WARNING):
            await agy_service.generate_chat_icon("Test Title", target_path)

    assert not os.path.exists(target_path)
    assert "Failed to extract valid SVG" in caplog.text


def test_agy_client_facade_alias():
    from app.agy_client import AgyClient, agy_client
    assert AgyClient is AGYService
    assert agy_client is not None

