"""Import-boundary check for the MCP interface adapter.

docs/architecture.md: interfaces -> application -> domain, with infrastructure
implementing application ports and wired only at the composition root
(`kinetiq.bootstrap.container`). The MCP interface therefore must not import
Django persistence (ORM models, `django.db`, the auth user model) or any
module's `infrastructure` package.
"""

import ast
from pathlib import Path

import pytest

import kinetiq.interfaces.mcp as mcp_package

MCP_DIR = Path(mcp_package.__file__).parent

FORBIDDEN_MODULE_PREFIXES = (
    "django.db",
    "django.contrib",
    "django.core.cache",
)
ALLOWED_DJANGO_MODULES = {"django.conf"}


def _imports(path: Path) -> list[tuple[int, str, list[str]]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[int, str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, alias.name, []))
        elif isinstance(node, ast.ImportFrom):
            found.append((node.lineno, node.module or "", [a.name for a in node.names]))
    return found


MCP_FILES = sorted(MCP_DIR.glob("*.py"))


def test_mcp_package_files_were_discovered() -> None:
    assert {p.name for p in MCP_FILES} >= {"auth.py", "server.py", "tools.py"}


@pytest.mark.parametrize("path", MCP_FILES, ids=lambda p: p.name)
def test_mcp_interface_does_not_import_persistence(path: Path) -> None:
    violations: list[str] = []
    for lineno, module, names in _imports(path):
        if module.startswith(FORBIDDEN_MODULE_PREFIXES):
            violations.append(f"{path.name}:{lineno} imports {module}")
        if module.startswith("django.") and module not in ALLOWED_DJANGO_MODULES:
            violations.append(f"{path.name}:{lineno} imports {module}")
        parts = module.split(".")
        if module.startswith("kinetiq.") and "infrastructure" in parts:
            violations.append(f"{path.name}:{lineno} imports infrastructure module {module}")
        if module.endswith(".models") or "models" in names:
            violations.append(f"{path.name}:{lineno} imports ORM models from {module}")
        if "get_user_model" in names:
            violations.append(f"{path.name}:{lineno} imports get_user_model")
    assert violations == []
