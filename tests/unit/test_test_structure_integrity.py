import configparser
import os
import pytest

def test_pytest_ini_defines_markers():
    """Verify that pytest.ini configures custom markers: unit, integration, e2e."""
    config = configparser.ConfigParser()
    config.read("pytest.ini")
    assert "pytest" in config, "pytest.ini must have a [pytest] section"
    markers = config.get("pytest", "markers", fallback="")
    assert "unit:" in markers, "pytest.ini must define 'unit' marker"
    assert "integration:" in markers, "pytest.ini must define 'integration' marker"
    assert "e2e:" in markers, "pytest.ini must define 'e2e' marker"

def test_directory_structure_exists():
    """Verify that tests/ is structured into unit/, integration/, and e2e/ directories."""
    assert os.path.isdir("tests/unit"), "tests/unit directory must exist"
    assert os.path.isdir("tests/integration"), "tests/integration directory must exist"
    assert os.path.isdir("tests/e2e"), "tests/e2e directory must exist"

def test_unit_tests_have_no_playwright_or_uvicorn():
    """Verify that unit tests do not import playwright or start uvicorn servers."""
    if not os.path.isdir("tests/unit"):
        pytest.fail("tests/unit directory does not exist")
    for root, _, files in os.walk("tests/unit"):
        for file in files:
            if file.startswith("test_") and file.endswith(".py") and file != "test_test_structure_integrity.py":
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                assert "playwright" not in content, f"Unit test {file} must not reference playwright"
                assert "uvicorn" not in content, f"Unit test {file} must not reference uvicorn"

def test_integration_tests_have_no_playwright():
    """Verify that integration tests do not import playwright."""
    if not os.path.isdir("tests/integration"):
        pytest.fail("tests/integration directory does not exist")
    for root, _, files in os.walk("tests/integration"):
        for file in files:
            if file.startswith("test_") and file.endswith(".py"):
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                assert "playwright" not in content, f"Integration test {file} must not reference playwright"

def test_all_e2e_tests_use_playwright():
    """Verify that all tests in tests/e2e actually involve Playwright."""
    if not os.path.isdir("tests/e2e"):
        pytest.fail("tests/e2e directory does not exist")
    for root, _, files in os.walk("tests/e2e"):
        for file in files:
            if file.startswith("test_") and file.endswith(".py"):
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                assert "playwright" in content, f"E2E test {file} must reference playwright"

def test_no_loose_tests_in_tests_root():
    """Verify that no feature test files remain directly in the root tests/ directory."""
    allowed_root_files = {
        "__init__.py",
        "conftest.py",
    }
    loose_tests = [
        f for f in os.listdir("tests")
        if f.endswith(".py") and f not in allowed_root_files
    ]
    assert not loose_tests, f"Loose test files found in tests/: {loose_tests}"
