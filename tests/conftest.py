import pytest

def pytest_collection_modifyitems(items):
    """Automatically attach markers (unit, integration, e2e) based on test directory location."""
    for item in items:
        fspath = str(item.fspath)
        if "/tests/unit/" in fspath or fspath.endswith("/tests/unit") or "\\tests\\unit\\" in fspath:
            item.add_marker(pytest.mark.unit)
        elif "/tests/integration/" in fspath or fspath.endswith("/tests/integration") or "\\tests\\integration\\" in fspath:
            item.add_marker(pytest.mark.integration)
        elif "/tests/e2e/" in fspath or fspath.endswith("/tests/e2e") or "\\tests\\e2e\\" in fspath:
            item.add_marker(pytest.mark.e2e)
