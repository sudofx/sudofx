from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SITE_JS = ROOT / "web" / "assets" / "site.js"


class RuntimeLightContractTests(unittest.TestCase):
    def test_runtime_light_uses_sudofx_health_not_application_activity(self) -> None:
        source = SITE_JS.read_text(encoding="utf-8")
        self.assertIn("authoritative database health check is OK", source)
        self.assertNotIn("recent governed application activity observed", source)
        self.assertNotIn("no recent application activity visible", source)


if __name__ == "__main__":
    unittest.main()
