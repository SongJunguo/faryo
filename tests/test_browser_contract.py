from __future__ import annotations

import json
from pathlib import Path
import unittest

from faryo_cli import browser_contract


class BrowserContractTest(unittest.TestCase):
    def test_response_wrap_is_versioned_without_mutating_input(self) -> None:
        source = {"ok": True, "futureField": "ignored"}
        wrapped = browser_contract.wrap_response(source)

        self.assertEqual(wrapped["envelopeVersion"], 1)
        self.assertNotIn("envelopeVersion", source)
        self.assertEqual(wrapped["futureField"], "ignored")

    def test_legacy_is_allowed_but_explicit_unknown_version_fails(self) -> None:
        browser_contract.require_supported_version({"ok": True})
        browser_contract.require_supported_version({"envelopeVersion": 1})
        for value in (0, 2, True, "1"):
            with self.subTest(value=value):
                with self.assertRaises(browser_contract.BrowserContractError):
                    browser_contract.require_supported_version(
                        {"envelopeVersion": value}
                    )

    def test_public_fixture_matches_the_python_contract(self) -> None:
        fixture = json.loads(
            (Path(__file__).parent / "fixtures/browser-envelope-v1.json").read_text(
                encoding="utf-8"
            )
        )
        browser_contract.require_supported_version(fixture)
        self.assertEqual(fixture["session"], "fixture-session")


if __name__ == "__main__":
    unittest.main()
