"""Tests for dpg_navigator._html — Chrome detection, timeout, and process kill.

These exercise backend availability, subprocess-timeout wiring, and Chrome
process ownership without launching a real Chrome/Chromium browser.
"""

from __future__ import annotations

import os
import subprocess
import sys
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


class TestChromeFlags:
    """Production Chrome flags disable JS and block network."""

    def test_disable_javascript_and_dead_proxy(self, tmp_path):
        fake_hti = MagicMock()
        fake_hti.browser._subprocess_run_kwargs = {}
        profile = str(tmp_path / "chrome")
        with patch.object(HTMLRenderer, "_hti", None), \
             patch.object(HTMLRenderer, "_chrome_profile_dir", None), \
             patch("dpg_navigator._html.tempfile.mkdtemp", return_value=profile), \
             patch.object(htmlmod, "_Html2Image", return_value=fake_hti) as ctor:
            HTMLRenderer._get_hti()
        flags = ctor.call_args.kwargs["custom_flags"]
        assert "--disable-javascript" in flags
        assert any(item.startswith("--proxy-server=") for item in flags)
        assert "--block-new-web-contents" in flags
        assert ctor.call_args.kwargs["output_path"] == profile


class TestInjectHelpers:
    def test_injects_css_reset_and_overflow_script(self):
        html = "<html><head></head><body><p>hi</p></body></html>"
        out = _inject_helpers(html)
        assert "<style>" in out
        assert out.index("<style>") < out.index("</head>")
        assert "<script>" in out
        assert "scrollWidth" in out

    def test_strips_file_urls(self):
        html = (
            "<html><head></head><body>"
            '<img src="file:///C:/secret.png">'
            '<a href="file://localhost/etc/passwd">x</a>'
            "<div style=\"background:url(file:///tmp/x.png)\"></div>"
            "</body></html>"
        )
        out = _inject_helpers(html)
        assert "file:" not in out.lower()


class TestChromeTimeout:
    """_get_hti() injects a subprocess timeout so a hung Chrome cannot block."""

    @pytest.mark.skipif(
        not html_available(),
        reason="html2image backend not importable in this environment",
    )
    def test_timeout_injected_into_subprocess_kwargs(self):
        with patch.object(HTMLRenderer, "_hti", None), \
             patch.object(HTMLRenderer, "_chrome_profile_dir", None):
            try:
                hti = HTMLRenderer._get_hti()
                assert hti.browser._subprocess_run_kwargs.get("timeout") == _CHROME_TIMEOUT
            finally:
                HTMLRenderer.shutdown_shared()


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

    def test_shutdown_shared_clears_singleton(self, tmp_path):
        profile = tmp_path / "dpg_nav_chrome_test"
        profile.mkdir()
        HTMLRenderer._hti = object()
        HTMLRenderer._chrome_profile_dir = str(profile)
        htmlmod._chrome_available_cache = True
        HTMLRenderer.shutdown_shared()
        assert HTMLRenderer._hti is None
        assert HTMLRenderer._chrome_profile_dir is None
        assert htmlmod._chrome_available_cache is None
        assert not profile.exists()


class TestRenderCancellation:
    def test_close_cancels_render_future(self):
        renderer = HTMLRenderer("test_tag")
        fut = MagicMock()
        renderer._render_future = fut
        with patch("dpg_navigator._html.dpg") as mock_dpg:
            mock_dpg.does_item_exist.return_value = False
            renderer.close()
        fut.cancel.assert_called_once()
        assert renderer._render_future is None

    def test_start_render_cancels_previous_future(self):
        renderer = HTMLRenderer("test_tag")
        old = MagicMock()
        new = MagicMock()
        renderer._render_future = old
        with patch("dpg_navigator._html.JobManager.submit", return_value=new):
            renderer._start_render(100)
        old.cancel.assert_called_once()
        assert renderer._render_future is new

    def test_render_worker_skips_screenshot_when_stale(self):
        renderer = HTMLRenderer("test_tag")
        renderer._render_generation = 5
        renderer._is_rendering = True
        with patch.object(renderer, "_hti_screenshot") as shot:
            renderer._render_worker(100, gen=4)
        shot.assert_not_called()
        assert renderer._is_rendering is False


class TestScreenshotOutputDir:
    def test_reads_png_from_chrome_output_path(self, tmp_path):
        Image = pytest.importorskip("PIL.Image")
        profile = tmp_path / "dpg_nav_chrome_test"
        profile.mkdir()
        renderer = HTMLRenderer("test_tag")
        renderer._html_content = "<p>x</p>"
        fake_hti = MagicMock()
        fake_hti.output_path = str(profile)

        def screenshot(*, html_str, save_as, size):
            Image.new("RGB", size, (255, 0, 0)).save(profile / save_as)

        fake_hti.screenshot.side_effect = screenshot
        with patch.object(HTMLRenderer, "_get_hti", return_value=fake_hti), \
             patch.object(HTMLRenderer, "_chrome_profile_dir", str(profile)):
            img = renderer._hti_screenshot(10, 10)
        assert img is not None
        assert img.size == (10, 10)
        img.close()
        assert list(profile.iterdir()) == []


class TestChromeProcessOwnership:
    def setup_method(self):
        HTMLRenderer._chrome_procs.clear()
        htmlmod._chrome_owner.renderer = None
        htmlmod._chrome_owner.generation = None

    def teardown_method(self):
        HTMLRenderer._chrome_procs.clear()
        htmlmod._chrome_owner.renderer = None
        htmlmod._chrome_owner.generation = None

    def test_kill_process_tree_stops_child(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
        )
        try:
            htmlmod._kill_process_tree(proc)
            assert proc.poll() is not None
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=2)

    def test_close_kills_owned_process(self):
        renderer = HTMLRenderer("test_tag")
        proc = MagicMock()
        proc.poll.return_value = None
        proc.pid = 12345
        HTMLRenderer._register_chrome(proc, renderer)
        with patch("dpg_navigator._html.dpg") as mock_dpg, \
             patch("dpg_navigator._html._kill_process_tree") as kill:
            mock_dpg.does_item_exist.return_value = False
            renderer.close()
        kill.assert_called_once_with(proc)

    def test_close_does_not_kill_other_renderer_process(self):
        mine = HTMLRenderer("a")
        other = HTMLRenderer("b")
        proc = MagicMock()
        proc.poll.return_value = None
        HTMLRenderer._register_chrome(proc, other)
        with patch("dpg_navigator._html.dpg") as mock_dpg, \
             patch("dpg_navigator._html._kill_process_tree") as kill:
            mock_dpg.does_item_exist.return_value = False
            mine.close()
        kill.assert_not_called()

    def test_shutdown_shared_kills_all(self, tmp_path):
        profile = tmp_path / "dpg_nav_chrome_test"
        profile.mkdir()
        proc = MagicMock()
        proc.poll.return_value = None
        HTMLRenderer._hti = object()
        HTMLRenderer._chrome_profile_dir = str(profile)
        HTMLRenderer._register_chrome(proc, object())
        with patch("dpg_navigator._html._kill_process_tree") as kill:
            HTMLRenderer.shutdown_shared()
        kill.assert_called_once_with(proc)
        assert HTMLRenderer._chrome_procs == []
        assert not profile.exists()

    def test_popen_run_aborts_when_generation_changed(self):
        renderer = HTMLRenderer("test_tag")
        renderer._render_generation = 2
        htmlmod._chrome_owner.renderer = renderer
        htmlmod._chrome_owner.generation = 1
        with patch("dpg_navigator._html.subprocess.Popen") as popen:
            with pytest.raises(htmlmod._ChromeCancelled):
                htmlmod._chrome_popen_run(["chrome"])
        popen.assert_not_called()

    def test_popen_run_kills_if_stale_after_spawn(self):
        renderer = HTMLRenderer("test_tag")
        renderer._render_generation = 1
        proc = MagicMock()
        proc.poll.return_value = None
        proc.pid = 99
        proc.returncode = 1
        proc.communicate.return_value = (None, None)

        def popen(*_args, **_kwargs):
            renderer._render_generation = 2
            return proc

        htmlmod._chrome_owner.renderer = renderer
        htmlmod._chrome_owner.generation = 1
        with patch("dpg_navigator._html.subprocess.Popen", side_effect=popen), \
             patch("dpg_navigator._html._kill_process_tree") as kill:
            with pytest.raises(htmlmod._ChromeCancelled):
                htmlmod._chrome_popen_run(["chrome"])
        kill.assert_called_once_with(proc)
        assert HTMLRenderer._chrome_procs == []

    def test_popen_run_kills_on_timeout(self):
        proc = MagicMock()
        proc.poll.return_value = None
        proc.pid = 1
        proc.returncode = -9
        proc.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd="chrome", timeout=0.01),
            (None, None),
        ]
        with patch("dpg_navigator._html.subprocess.Popen", return_value=proc), \
             patch("dpg_navigator._html._kill_process_tree") as kill:
            with pytest.raises(subprocess.TimeoutExpired):
                htmlmod._chrome_popen_run(["chrome"], timeout=0.01)
        kill.assert_called_once_with(proc)

    @pytest.mark.skipif(
        not html_available(),
        reason="html2image backend not importable in this environment",
    )
    def test_get_hti_installs_chromium_run_hook(self):
        with patch.object(HTMLRenderer, "_hti", None), \
             patch.object(HTMLRenderer, "_chrome_profile_dir", None):
            try:
                HTMLRenderer._get_hti()
                import html2image.browsers.chromium as chromium_mod
                assert isinstance(chromium_mod.subprocess, htmlmod._ChromiumSubprocessProxy)
            finally:
                HTMLRenderer.shutdown_shared()
