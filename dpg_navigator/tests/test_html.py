"""Tests for dpg_navigator._html — Chrome detection and render timeout.

These exercise pure logic (backend availability, subprocess-timeout wiring)
without launching a real Chrome/Chromium process.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

import dpg_navigator._html as htmlmod
from dpg_navigator._html import (
    HTMLRenderer,
    chrome_available,
    html_available,
    _CHROME_TIMEOUT,
    _inject_helpers,
    _read_overflow_marker,
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


class TestHtmlSizeLimit:
    """open()/open_string() reject oversized sources before Chrome."""

    def test_open_string_rejects_oversized(self):
        from dpg_navigator import _html as htmlmod

        big = "x" * (htmlmod._MAX_HTML_BYTES + 10)
        renderer = HTMLRenderer("test_tag")
        # Avoid real texture/chrome work: close() is fine without open
        with patch.object(renderer, "_recreate_texture"), \
             patch.object(renderer, "_start_render") as start:
            ok = renderer.open_string(big, 100, 100)
            assert ok is False
            start.assert_not_called()
            assert "large" in renderer.status_text.lower()

    def test_shutdown_shared_clears_singleton(self):
        HTMLRenderer._hti = object()
        htmlmod = __import__("dpg_navigator._html", fromlist=["_chrome_available_cache"])
        htmlmod._chrome_available_cache = True
        HTMLRenderer.shutdown_shared()
        assert HTMLRenderer._hti is None
        assert htmlmod._chrome_available_cache is None
