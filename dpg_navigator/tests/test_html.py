"""Tests for dpg_navigator._html — Chrome detection and render timeout.

These exercise pure logic (backend availability, subprocess-timeout wiring)
without launching a real Chrome/Chromium process.
"""

from unittest.mock import MagicMock, patch

import pytest

import dpg_navigator._html as htmlmod
from dpg_navigator._html import (
    HTMLRenderer,
    chrome_available,
    html_available,
    _CHROME_TIMEOUT,
)


class TestChromeAvailable:
    """chrome_available() resolves the browser binary and caches the result."""

    def test_false_when_html_deps_missing(self):
        with patch.object(htmlmod, "_chrome_available_cache", None), \
             patch.object(htmlmod, "html_available", return_value=False):
            assert chrome_available() is False

    def test_true_when_executable_resolves(self):
        fake_hti = MagicMock()
        fake_hti.browser.executable = r"C:\chrome.exe"
        with patch.object(htmlmod, "_chrome_available_cache", None), \
             patch.object(htmlmod, "html_available", return_value=True), \
             patch.object(HTMLRenderer, "_get_hti", return_value=fake_hti):
            assert chrome_available() is True

    def test_false_when_executable_missing(self):
        fake_hti = MagicMock()
        fake_hti.browser.executable = None
        with patch.object(htmlmod, "_chrome_available_cache", None), \
             patch.object(htmlmod, "html_available", return_value=True), \
             patch.object(HTMLRenderer, "_get_hti", return_value=fake_hti):
            assert chrome_available() is False

    def test_false_when_resolution_raises(self):
        with patch.object(htmlmod, "_chrome_available_cache", None), \
             patch.object(htmlmod, "html_available", return_value=True), \
             patch.object(HTMLRenderer, "_get_hti", side_effect=RuntimeError):
            assert chrome_available() is False

    def test_result_is_cached(self):
        fake_hti = MagicMock()
        fake_hti.browser.executable = "/usr/bin/chromium"
        with patch.object(htmlmod, "_chrome_available_cache", None), \
             patch.object(htmlmod, "html_available", return_value=True), \
             patch.object(HTMLRenderer, "_get_hti", return_value=fake_hti) as get_hti:
            assert chrome_available() is True
            assert chrome_available() is True
            get_hti.assert_called_once()


class TestChromeTimeout:
    """_get_hti() injects a subprocess timeout so a hung Chrome cannot block."""

    @pytest.mark.skipif(
        not html_available(),
        reason="html2image backend not importable in this environment",
    )
    def test_timeout_injected_into_subprocess_kwargs(self):
        with patch.object(HTMLRenderer, "_hti", None):
            hti = HTMLRenderer._get_hti()
            assert hti.browser._subprocess_run_kwargs.get("timeout") == _CHROME_TIMEOUT
