"""The server package stands alone: it never imports the database tools.

The database tools connect as the admin role, so they're a separate package that
a server install leaves out (server-spec.md, decision 2). If a server module
imported one, the server would break when deployed on its own.
"""

import pkgutil
import subprocess
import sys

import insurance_mcp


def test_no_server_module_imports_the_database_package():
    modules = [f"insurance_mcp.{m.name}" for m in pkgutil.iter_modules(insurance_mcp.__path__)]
    # A fresh Python process: this test session has already imported the
    # database package, to build the test database.
    check = (
        f"import importlib, sys\n"
        f"for name in {modules!r}: importlib.import_module(name)\n"
        f"print(sorted(m for m in sys.modules if m.split('.')[0] == 'insurance_database'))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", check], capture_output=True, text=True, check=True
    )

    assert "insurance_mcp.main" in modules
    assert result.stdout.strip() == "[]"
