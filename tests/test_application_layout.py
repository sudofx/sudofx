from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
APPLICATIONS = ROOT / "applications"


class ApplicationLayoutTests(unittest.TestCase):
    def test_applications_are_package_directories(self) -> None:
        loose_modules = sorted(
            path.name
            for path in APPLICATIONS.glob("*.py")
            if path.name != "__init__.py"
        )
        self.assertEqual(
            loose_modules,
            [],
            f"application implementations must live in their own package directories: {loose_modules}",
        )

    def test_application_directories_are_importable_packages(self) -> None:
        package_dirs = sorted(
            path
            for path in APPLICATIONS.iterdir()
            if path.is_dir() and not path.name.startswith(".") and path.name != "__pycache__"
        )
        self.assertTrue(package_dirs, "at least one application package must exist")
        for package_dir in package_dirs:
            self.assertTrue(
                (package_dir / "__init__.py").is_file(),
                f"{package_dir.name} must define an __init__.py package boundary",
            )


if __name__ == "__main__":
    unittest.main()
