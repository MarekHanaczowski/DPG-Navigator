"""Tests for safe/trusted HTML preparation, Chrome sessions, and handoff."""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import dpg_navigator._html as htmlmod
from dpg_navigator._html import (
    _BG_COLOR_RGBA,
    _CHROME_TIMEOUT,
    HTMLRenderer,
    _auto_trim,
    _chrome_custom_flags,
    _chrome_popen_run,
    _ChromeCancelled,
    _clear_marker,
    _ensure_chromium_run_hook,
    _inject_helpers,
    _is_headless_shell,
    _looks_vertically_clipped,
    _PendingRender,
    _prepare_safe_document,
    _read_overflow_marker,
    _resolve_chrome_executable,
    chrome_available,
    html_available,
)


@pytest.fixture(autouse=True)
def mock_html_dpg():
    """Never let GUI-free unit tests call an uninitialized real DPG context."""
    with patch.object(htmlmod, "dpg") as mock_dpg:
        mock_dpg.get_frame_count.return_value = 10
        mock_dpg.does_item_exist.return_value = False
        yield mock_dpg


@pytest.fixture(autouse=True)
def reset_html_class_state():
    HTMLRenderer._chrome_procs.clear()
    HTMLRenderer._poll_targets.clear()
    HTMLRenderer._poll_armed = False
    htmlmod._chrome_owner.renderer = None
    htmlmod._chrome_owner.generation = None
    htmlmod._chrome_available_cache = None
    htmlmod._chrome_executable_cache = None
    yield
    HTMLRenderer._chrome_procs.clear()
    HTMLRenderer._poll_targets.clear()
    HTMLRenderer._poll_armed = False
    htmlmod._chrome_owner.renderer = None
    htmlmod._chrome_owner.generation = None
    htmlmod._chrome_available_cache = None
    htmlmod._chrome_executable_cache = None


def _fake_session(tmp_path):
    return SimpleNamespace(
        hti=MagicMock(),
        output_path=str(tmp_path),
        cleanup=MagicMock(),
    )


class TestChromeAvailable:
    """chrome_available() uses a disposable session and caches the result."""

    def test_false_when_html_deps_missing(self):
        with (
            patch.object(htmlmod, "_chrome_available_cache", None),
            patch.object(htmlmod, "html_available", return_value=False),
        ):
            assert chrome_available() is False

    def test_true_when_executable_resolves(self):
        with (
            patch.object(htmlmod, "_chrome_available_cache", None),
            patch.object(htmlmod, "html_available", return_value=True),
            patch.object(htmlmod, "_discover_chrome_executable", return_value=r"C:\chrome.exe"),
        ):
            assert chrome_available() is True

    def test_false_when_executable_missing(self):
        with (
            patch.object(htmlmod, "_chrome_available_cache", None),
            patch.object(htmlmod, "html_available", return_value=True),
            patch.object(htmlmod, "_discover_chrome_executable", return_value=None),
        ):
            assert chrome_available() is False

    def test_false_when_resolution_raises(self):
        with (
            patch.object(htmlmod, "_chrome_available_cache", None),
            patch.object(htmlmod, "html_available", return_value=True),
            patch.object(htmlmod, "_discover_chrome_executable", side_effect=RuntimeError),
        ):
            assert chrome_available() is False

    def test_result_is_cached(self):
        with (
            patch.object(htmlmod, "_chrome_available_cache", None),
            patch.object(htmlmod, "html_available", return_value=True),
            patch.object(htmlmod, "_discover_chrome_executable", return_value="/usr/bin/chromium") as discover,
        ):
            assert chrome_available() is True
            assert chrome_available() is True
            discover.assert_called_once()

    def test_false_result_is_not_cached(self):
        with (
            patch.object(htmlmod, "_chrome_available_cache", None),
            patch.object(htmlmod, "html_available", return_value=True),
            patch.object(htmlmod, "_discover_chrome_executable", side_effect=[None, "/usr/bin/chromium"]) as discover,
        ):
            assert chrome_available() is False
            assert chrome_available() is True
            assert discover.call_count == 2


class TestChromeFlagsAndSessions:
    def test_safe_flags_block_network_without_noop_js_switches(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DPG_CHROME_NO_SANDBOX", raising=False)
        flags = _chrome_custom_flags(str(tmp_path), trusted=False)
        assert "--blink-settings=scriptEnabled=false" not in flags
        assert "--disable-javascript" not in flags
        assert "--proxy-server=http://127.0.0.1:1" in flags
        assert "--proxy-bypass-list=<-loopback>" in flags
        assert "--block-new-web-contents" in flags
        assert "--disable-gpu" in flags
        assert "--no-sandbox" not in flags

    def test_trusted_flags_allow_resources_but_keep_isolation(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DPG_CHROME_NO_SANDBOX", raising=False)
        flags = _chrome_custom_flags(str(tmp_path), trusted=True)
        assert not any(flag.startswith("--proxy-server=") for flag in flags)
        assert "--block-new-web-contents" in flags
        assert f"--user-data-dir={tmp_path}" in flags
        assert f"--crash-dumps-dir={tmp_path}" in flags

    def test_no_sandbox_is_only_explicit_environment_opt_in(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DPG_CHROME_NO_SANDBOX", "1")
        flags = _chrome_custom_flags(str(tmp_path), trusted=False)
        assert "--no-sandbox" in flags
        assert "--disable-setuid-sandbox" in flags
        assert "--disable-dev-shm-usage" in flags
        assert "--no-zygote" in flags
        assert "--virtual-time-budget=10000" in flags
        assert "--disable-gpu" not in flags

    def test_create_session_isolates_all_chrome_paths_under_one_root(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DPG_CHROME_BIN", raising=False)
        monkeypatch.delenv("CHROME_BIN", raising=False)
        monkeypatch.delenv("CHROME_PATH", raising=False)
        temp = MagicMock()
        temp.name = str(tmp_path / "session")
        fake_hti = MagicMock()
        fake_hti.browser._subprocess_run_kwargs = {}
        with (
            patch.object(htmlmod.tempfile, "TemporaryDirectory", return_value=temp),
            patch.object(htmlmod, "_discover_chrome_executable", return_value="/chrome"),
            patch.object(htmlmod, "_Html2Image", return_value=fake_hti) as ctor,
        ):
            session = HTMLRenderer._create_chrome_session(trusted=False)
        kwargs = ctor.call_args.kwargs
        output_dir = htmlmod.os.path.join(temp.name, "output")
        input_dir = htmlmod.os.path.join(temp.name, "input")
        profile_dir = htmlmod.os.path.join(temp.name, "profile")
        crash_dir = htmlmod.os.path.join(temp.name, "crash")
        assert kwargs["output_path"] == output_dir
        assert kwargs["temp_path"] == input_dir
        assert f"--user-data-dir={profile_dir}" in kwargs["custom_flags"]
        assert f"--crash-dumps-dir={crash_dir}" in kwargs["custom_flags"]
        assert fake_hti.browser._subprocess_run_kwargs["timeout"] == _CHROME_TIMEOUT
        assert fake_hti.browser.use_new_headless is True
        assert session.output_path == output_dir
        session.cleanup()
        temp.cleanup.assert_called_once()

    def test_constructor_failure_cleans_profile(self, tmp_path):
        temp = MagicMock()
        temp.name = str(tmp_path / "failed")
        with (
            patch.object(htmlmod.tempfile, "TemporaryDirectory", return_value=temp),
            patch.object(htmlmod, "_discover_chrome_executable", return_value="/chrome"),
            patch.object(htmlmod, "_Html2Image", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError, match="boom"),
        ):
            HTMLRenderer._create_chrome_session(trusted=False)
        temp.cleanup.assert_called_once()

    def test_headless_shell_uses_plain_headless_mode(self):
        fake_hti = MagicMock()
        fake_hti.browser._subprocess_run_kwargs = {}
        with (
            patch.object(
                htmlmod,
                "_discover_chrome_executable",
                return_value="/opt/chrome-headless-shell",
            ),
            patch.object(htmlmod, "_Html2Image", return_value=fake_hti),
        ):
            session = HTMLRenderer._create_chrome_session(trusted=False)
        try:
            assert fake_hti.browser.use_new_headless is None
        finally:
            session.cleanup()

    def test_each_render_gets_a_distinct_temporary_session(self, tmp_path):
        fake_a = MagicMock()
        fake_a.browser._subprocess_run_kwargs = {}
        fake_b = MagicMock()
        fake_b.browser._subprocess_run_kwargs = {}
        with (
            patch.object(htmlmod, "_discover_chrome_executable", return_value="/chrome"),
            patch.object(htmlmod, "_Html2Image", side_effect=[fake_a, fake_b]),
        ):
            first = HTMLRenderer._create_chrome_session(trusted=False)
            second = HTMLRenderer._create_chrome_session(trusted=False)
        try:
            assert first.output_path != second.output_path
        finally:
            first.cleanup()
            second.cleanup()


class TestResolveChromeExecutable:
    def test_prefers_dpg_chrome_bin(self, tmp_path, monkeypatch):
        chrome = tmp_path / "dpg-chrome"
        chrome.write_bytes(b"")
        other = tmp_path / "other-chrome"
        other.write_bytes(b"")
        monkeypatch.setenv("DPG_CHROME_BIN", str(chrome))
        monkeypatch.setenv("CHROME_BIN", str(other))
        assert _resolve_chrome_executable() == str(chrome)

    def test_missing_path_is_ignored(self, monkeypatch):
        monkeypatch.setenv("DPG_CHROME_BIN", "/no/such/chrome-binary")
        monkeypatch.delenv("CHROME_BIN", raising=False)
        monkeypatch.delenv("CHROME_PATH", raising=False)
        assert _resolve_chrome_executable() is None

    def test_headless_shell_matches_basename(self):
        assert _is_headless_shell("/opt/chrome-headless-shell") is True
        assert _is_headless_shell("/opt/hostedtoolcache/chrome") is False
        assert _is_headless_shell(None) is False

    def test_posix_validation_probe_has_a_timeout(self):
        completed = MagicMock(returncode=0, stdout=b"Chromium 123")
        with (
            patch.object(htmlmod.os, "name", "posix"),
            patch.object(htmlmod.shutil, "which", return_value="/usr/bin/chromium"),
            patch.object(htmlmod.subprocess, "run", return_value=completed) as run,
        ):
            assert htmlmod._validate_chrome_executable("chromium") == "/usr/bin/chromium"
        assert run.call_args.kwargs["timeout"] == htmlmod._CHROME_PROBE_TIMEOUT


class TestSafeHtmlPreparation:
    @pytest.mark.parametrize(
        "payload, forbidden",
        [
            ('<img src="file:///C:/secret.png">', "file:"),
            ('<img src="f&#105;le:///C:/secret.png">', "file:"),
            ('<img/src="file:///C:/secret.png">', "file:"),
            ('<img src="fi\tle:///C:/secret.png">', "fi\tle:"),
            ('<img src="./secret.png">', 'src="./secret.png"'),
            ('<img src="//host/share/secret.png">', "//host/share"),
            ('<img srcset="data:image/png;base64,AA== 1x, file:///C:/secret.png 2x">', "srcset="),
            ('<iframe srcdoc="<script>x()</script>"></iframe>', "<iframe"),
            ('<object data="file:///etc/passwd"></object>', "<object"),
            ('<div style="background:url(https://example.test/x)">x</div>', "style="),
            ('<table background="//host/share/x.png"><tr><td>x</td></tr></table>', "background="),
            ('<svg><image xlink:href="file:///C:/secret.png"></image></svg>', "xlink:href"),
            ('<form action="https://example.test"><input></form>', "<form"),
            ('<a href="https://example.test">link</a>', "href="),
            ('<img src=x onerror="alert(1)">', "onerror"),
            ('<base href="file:///C:/"><meta http-equiv="refresh" content="0;url=//host/">', "<base"),
        ],
    )
    def test_vectors_cannot_load_or_execute(self, payload, forbidden):
        out = _prepare_safe_document(payload)
        assert forbidden not in out.lower()
        assert "script-src 'none'" in out
        assert "default-src 'none'" in out

    def test_csp_precedes_body_and_author_meta_is_removed(self):
        out = _prepare_safe_document('<meta http-equiv="Content-Security-Policy" content="default-src *"><p>ok</p>')
        assert out.index("Content-Security-Policy") < out.index("<body>")
        assert out.lower().count("content-security-policy") == 1
        assert "default-src *" not in out

    def test_only_verified_embedded_raster_images_are_kept(self):
        allowed = "data:image/png;base64,iVBORw0KGgo="
        out = _prepare_safe_document(f'<img src="{allowed}"><img src="data:image/svg+xml;base64,PHN2Zz4=">')
        assert allowed in out
        assert "svg+xml" not in out

    def test_huge_data_image_is_stripped(self):
        huge = "data:image/png;base64," + ("A" * 3_000_000)
        out = _prepare_safe_document(f'<img src="{huge}">')
        assert "data:image/png" not in out

    def test_event_handlers_scripts_and_author_css_are_removed(self):
        out = _prepare_safe_document(
            '<script>alert(1)</script><style>body{background:url(//x)}</style><p onclick="alert(2)">safe text</p>'
        )
        assert "<script" not in out.lower()
        assert "<style>body{" not in out.lower()
        assert "onclick" not in out.lower()
        assert "safe text" in out

    def test_css_import_is_only_inert_text_in_body(self):
        out = _prepare_safe_document("<style>@import url(//example.test/x.css)</style>")
        body = out.split("<body>", 1)[1]
        assert "<style" not in body.lower()

    def test_controlled_css_and_wrapper_are_preserved(self):
        out = _prepare_safe_document("<h1>Title</h1>", css=".md-wrapper{padding:7px}", wrapper_class="md-wrapper")
        assert ".md-wrapper{padding:7px}" in out
        assert '<div class="md-wrapper"><h1>Title</h1></div>' in out

    def test_trusted_helpers_preserve_raw_behavior(self):
        raw = '<HTML><HEAD></HEAD><BODY><script>window.ran=true</script><img src="file:///C:/secret.png"></BODY></HTML>'
        out = _inject_helpers(raw)
        assert "window.ran=true" in out
        assert "file:///C:/secret.png" in out
        assert "scrollWidth" in out
        assert out.lower().index("<style>") < out.lower().index("</head>")


class TestOpenPolicyAndLimits:
    def test_open_defaults_to_safe_mode(self, tmp_path):
        page = tmp_path / "page.html"
        page.write_text('<script>x()</script><img src="./local.png">', encoding="utf-8")
        renderer = HTMLRenderer("test")
        with patch.object(renderer, "_recreate_texture"), patch.object(renderer, "_start_render"):
            assert renderer.open(str(page), 100, 100)
        assert renderer._trusted is False
        assert "Content-Security-Policy" in renderer._html_content
        assert "<script" not in renderer._html_content
        assert "./local.png" not in renderer._html_content
        assert "scrollWidth" not in renderer._html_content

    def test_open_trusted_is_explicit_and_preserves_raw_html(self, tmp_path):
        page = tmp_path / "page.html"
        page.write_text('<script>x()</script><img src="./local.png">', encoding="utf-8")
        renderer = HTMLRenderer("test")
        with patch.object(renderer, "_recreate_texture"), patch.object(renderer, "_start_render"):
            assert renderer.open(str(page), 100, 100, trusted=True)
        assert renderer._trusted is True
        assert "<script>x()</script>" in renderer._html_content
        assert "./local.png" in renderer._html_content
        assert "<base href=" in renderer._html_content
        assert "scrollWidth" in renderer._html_content

    def test_open_string_is_always_safe(self):
        renderer = HTMLRenderer("test")
        with patch.object(renderer, "_recreate_texture"), patch.object(renderer, "_start_render"):
            assert renderer.open_string(
                '<script>x()</script><p onclick="x()">hello</p>',
                100,
                100,
                css=".md-wrapper{padding:1px}",
                wrapper_class="md-wrapper",
            )
        assert renderer._trusted is False
        assert "<script" not in renderer._html_content
        assert "onclick" not in renderer._html_content
        assert ".md-wrapper{padding:1px}" in renderer._html_content
        assert "scrollWidth" not in renderer._html_content

    def test_open_string_rejects_oversized(self):
        big = "x" * (htmlmod._MAX_HTML_BYTES + 10)
        renderer = HTMLRenderer("test")
        with patch.object(renderer, "_recreate_texture"), patch.object(renderer, "_start_render") as start:
            assert renderer.open_string(big, 100, 100) is False
        start.assert_not_called()
        assert "large" in renderer.status_text.lower()


class TestRenderQualityHelpers:
    def test_auto_trim_reduces_a_truly_blank_document(self):
        image = pytest.importorskip("PIL.Image")
        img = image.new("RGBA", (20, 20), _BG_COLOR_RGBA)
        trimmed = _auto_trim(img)
        try:
            assert trimmed.size == (20, 1)
        finally:
            img.close()
            trimmed.close()

    def test_auto_trim_keeps_low_contrast_dark_content(self):
        image = pytest.importorskip("PIL.Image")
        img = image.new("RGBA", (20, 30), _BG_COLOR_RGBA)
        img.putpixel((10, 20), (27, 26, 26, 255))
        trimmed = _auto_trim(img)
        try:
            assert 1 < trimmed.height < 30
            assert trimmed.getpixel((10, 2))[:3] == (27, 26, 26)
        finally:
            img.close()
            trimmed.close()

    def test_auto_trim_keeps_sparse_content_row(self):
        image = pytest.importorskip("PIL.Image")
        img = image.new("RGBA", (20, 30), _BG_COLOR_RGBA)
        img.putpixel((10, 20), (255, 255, 255, 255))
        trimmed = _auto_trim(img)
        try:
            assert 1 < trimmed.height < 30
            assert trimmed.getpixel((10, 2))[:3] == (255, 255, 255)
        finally:
            img.close()
            trimmed.close()

    def test_marker_requires_signature_and_decodes_both_dimensions(self):
        np = pytest.importorskip("numpy")
        pixels = np.zeros((10, 10, 4), dtype=np.uint8)
        width, height = 1234, 5678
        pixels[3, 3, :3] = (width >> 8, width & 255, 255)
        pixels[4, 3, :3] = (height >> 8, height & 255, 255)
        assert _read_overflow_marker(pixels) == (False, 0, 0)
        pixels[3, 4, :3] = (17, 34, 51)
        assert _read_overflow_marker(pixels) == (True, width, height)

    def test_clear_marker_changes_only_top_left_ten_pixels(self):
        np = pytest.importorskip("numpy")
        pixels = np.zeros((15, 15, 4), dtype=np.uint8)
        pixels[:10, :10] = 9
        pixels[:10, 10] = 7
        before_outside = pixels[10:].copy()
        _clear_marker(pixels)
        assert np.all(pixels[:10, :10] == 7)
        assert np.array_equal(pixels[10:], before_outside)

    def test_safe_clipping_heuristic_uses_bottom_rows(self):
        np = pytest.importorskip("numpy")
        pixels = np.empty((20, 10, 4), dtype=np.uint8)
        pixels[:] = _BG_COLOR_RGBA
        assert _looks_vertically_clipped(pixels) is False
        pixels[-1, 2] = (255, 255, 255, 255)
        assert _looks_vertically_clipped(pixels) is True

    def test_texture_status_reports_vertical_clipping(self):
        np = pytest.importorskip("numpy")
        renderer = HTMLRenderer("test")
        renderer._doc_array = np.zeros((1, 1, 4), dtype=np.uint8)
        renderer._doc_w = 1
        renderer._doc_h = 1
        renderer._tex_w = 21
        renderer._tex_h = 1
        renderer._viewport_buf = np.zeros((1, 21, 4), dtype=np.float32)
        renderer._buf_ptr = 1
        renderer._vertically_clipped = True
        with patch.object(htmlmod.ctypes, "memmove"):
            renderer._update_texture()
        assert f"Clipped at {htmlmod._RENDER_H}px" in renderer.status_text


class TestMainThreadHandoff:
    def test_start_render_arms_poll_before_submitting(self):
        renderer = HTMLRenderer("test")
        renderer._html_content = "<p>x</p>"
        old = MagicMock()
        renderer._render_future = old
        events = []
        future = MagicMock()
        with (
            patch.object(renderer, "_arm_poll", side_effect=lambda: events.append("poll")),
            patch.object(
                htmlmod.JobManager,
                "submit",
                side_effect=lambda *_args: events.append("submit") or future,
            ),
        ):
            renderer._start_render(100)
        old.cancel.assert_called_once()
        assert events == ["poll", "submit"]
        assert renderer._render_future is future

    def test_render_worker_skips_stale_generation_without_state_mutation(self):
        renderer = HTMLRenderer("test")
        renderer._render_generation = 5
        renderer._is_rendering = True
        with patch.object(renderer, "_create_chrome_session") as create:
            renderer._render_worker(100, 4, "<p>x</p>", False)
        create.assert_not_called()
        assert renderer._is_rendering is True

    def test_worker_success_queues_result_without_touching_dpg(self, mock_html_dpg, tmp_path):
        image = pytest.importorskip("PIL.Image")
        renderer = HTMLRenderer("test")
        renderer._html_content = "<p>x</p>"
        renderer._render_generation = 1
        renderer._is_rendering = True
        session = _fake_session(tmp_path)
        screenshot = image.new("RGBA", (100, 30), _BG_COLOR_RGBA)
        screenshot.putpixel((10, 10), (255, 255, 255, 255))
        mock_html_dpg.reset_mock()
        with (
            patch.object(renderer, "_create_chrome_session", return_value=session),
            patch.object(renderer, "_hti_screenshot", return_value=screenshot),
        ):
            renderer._render_worker(100, 1, renderer._html_content, False)
        assert renderer._pending_render is not None
        assert renderer._pending_render.error is None
        assert renderer._is_rendering is True
        assert mock_html_dpg.mock_calls == []
        session.cleanup.assert_called_once()

    def test_worker_failure_becomes_polled_failure(self, mock_html_dpg):
        renderer = HTMLRenderer("test")
        renderer._html_content = "<p>x</p>"
        renderer._render_generation = 1
        renderer._is_rendering = True
        callback = MagicMock()
        renderer._on_complete = callback
        mock_html_dpg.reset_mock()
        with patch.object(renderer, "_create_chrome_session", side_effect=RuntimeError("boom")):
            renderer._render_worker(100, 1, renderer._html_content, False)
        assert renderer._pending_render is not None
        assert renderer._pending_render.error == "Render failed"
        assert renderer.status_text != "Render failed"
        assert mock_html_dpg.mock_calls == []
        renderer._apply_pending()
        assert renderer.is_rendering is False
        assert renderer.status_text == "Render failed"
        callback.assert_called_once()

    def test_cancelled_worker_is_silent(self):
        renderer = HTMLRenderer("test")
        renderer._html_content = "<p>x</p>"
        renderer._render_generation = 1
        with patch.object(renderer, "_create_chrome_session", side_effect=_ChromeCancelled):
            renderer._render_worker(100, 1, renderer._html_content, False)
        assert renderer._pending_render is None

    def test_stale_pending_result_does_not_invoke_callback(self):
        renderer = HTMLRenderer("test")
        renderer._html_content = "<p>x</p>"
        renderer._render_generation = 2
        callback = MagicMock()
        renderer._on_complete = callback
        renderer._pending_render = _PendingRender(1, None, 0, 0, None, 0, 0, 0, 0.0, False, "old")
        renderer._apply_pending()
        callback.assert_not_called()

    def test_frame_poll_applies_pending_result_under_dpg_mutex(self, mock_html_dpg):
        renderer = HTMLRenderer("test")
        renderer._html_content = "<p>x</p>"
        renderer._render_generation = 1
        renderer._is_rendering = True
        renderer._pending_render = _PendingRender(1, None, 0, 0, None, 0, 0, 0, 0.0, False, "failed")
        HTMLRenderer._poll_targets.append(renderer)

        HTMLRenderer._poll_frame()

        mock_html_dpg.mutex.assert_called_once()
        assert renderer.status_text == "failed"
        assert renderer.is_rendering is False

    def test_resize_worker_queues_without_dpg_then_poll_applies(self, mock_html_dpg):
        np = pytest.importorskip("numpy")
        renderer = HTMLRenderer("test")
        renderer._html_content = "<p>x</p>"
        renderer._full_array = np.zeros((20, 20, 4), dtype=np.uint8)
        renderer._full_w = 20
        renderer._full_h = 20
        renderer._tex_w = 100
        renderer._tex_h = 100
        callback = MagicMock()
        renderer._on_resize_complete = callback
        scheduled = {}

        def schedule(_delay, fn):
            scheduled["fn"] = fn
            return MagicMock()

        with patch.object(htmlmod.JobManager, "schedule_timer", side_effect=schedule):
            renderer.on_resize(200, 150)
        mock_html_dpg.reset_mock()
        scheduled["fn"]()
        assert renderer._pending_resize is not None
        assert mock_html_dpg.mock_calls == []
        with (
            patch.object(renderer, "_recreate_texture") as recreate,
            patch.object(renderer, "_start_render") as start,
            patch.object(HTMLRenderer, "_kill_owned_chrome"),
        ):
            renderer._apply_pending()
        recreate.assert_called_once_with(200, 150)
        start.assert_called_once_with(180)
        callback.assert_called_once()

    def test_close_clears_pending_unregisters_poll_and_cancels_work(self):
        renderer = HTMLRenderer("test")
        renderer._html_content = "<p>x</p>"
        renderer._render_future = MagicMock()
        renderer._resize_timer = MagicMock()
        renderer._pending_render = _PendingRender(0, None, 0, 0, None, 0, 0, 0, 0.0, False, "old")
        HTMLRenderer._poll_targets.append(renderer)
        future = renderer._render_future
        timer = renderer._resize_timer
        with (
            patch.object(htmlmod.JobManager, "cancel_timer") as cancel_timer,
            patch.object(HTMLRenderer, "_kill_owned_chrome"),
        ):
            renderer.close()
        future.cancel.assert_called_once()
        cancel_timer.assert_called_once_with(timer)
        assert renderer._pending_render is None
        assert renderer not in HTMLRenderer._poll_targets
        assert not renderer.is_open

    def test_two_renderers_keep_results_and_sessions_independent(self, tmp_path):
        image = pytest.importorskip("PIL.Image")
        first = HTMLRenderer("first")
        second = HTMLRenderer("second")
        first._html_content = "<p>one</p>"
        second._html_content = "<p>two</p>"
        first._render_generation = second._render_generation = 1
        sessions = [_fake_session(tmp_path / "one"), _fake_session(tmp_path / "two")]

        def screenshot(_session, _html, width, _height, _generation):
            return image.new("RGBA", (width, 20), _BG_COLOR_RGBA)

        with (
            patch.object(HTMLRenderer, "_create_chrome_session", side_effect=sessions),
            patch.object(HTMLRenderer, "_hti_screenshot", side_effect=screenshot),
        ):
            first._render_worker(100, 1, first._html_content, False)
            second._render_worker(120, 1, second._html_content, False)
        assert first._pending_render is not None
        assert second._pending_render is not None
        assert first._pending_render.doc_width == 100
        assert second._pending_render.doc_width == 120
        sessions[0].cleanup.assert_called_once()
        sessions[1].cleanup.assert_called_once()


class TestScreenshotOutput:
    def test_reads_png_from_session_and_removes_it(self, tmp_path):
        image = pytest.importorskip("PIL.Image")
        renderer = HTMLRenderer("test")
        renderer._render_generation = 1
        session = _fake_session(tmp_path)

        def screenshot(*, html_str, save_as, size):
            assert html_str == "<p>x</p>"
            image.new("RGB", size, (255, 0, 0)).save(tmp_path / save_as)

        session.hti.screenshot.side_effect = screenshot
        img = renderer._hti_screenshot(session, "<p>x</p>", 10, 10, 1)
        try:
            assert img.size == (10, 10)
        finally:
            img.close()
        assert list(tmp_path.iterdir()) == []


class TestChromeProcessOwnership:
    def test_kill_process_tree_stops_child(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            htmlmod._kill_process_tree(proc)
            assert proc.poll() is not None
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=2)

    def test_close_kills_owned_process(self):
        renderer = HTMLRenderer("test")
        proc = MagicMock()
        proc.poll.return_value = None
        proc.pid = 12345
        # Stub the create-time probe: a real psutil lookup of PID 12345 is
        # nondeterministic on CI (the PID may or may not exist).
        with patch.object(htmlmod, "_chrome_create_time", return_value=111.0):
            HTMLRenderer._register_chrome(proc, renderer)
        with patch.object(htmlmod, "_kill_process_tree") as kill:
            renderer.close()
        kill.assert_called_once_with(proc, 111.0)

    def test_close_does_not_kill_other_renderer_process(self):
        mine = HTMLRenderer("mine")
        other = HTMLRenderer("other")
        proc = MagicMock()
        proc.poll.return_value = None
        HTMLRenderer._register_chrome(proc, other)
        with patch.object(htmlmod, "_kill_process_tree") as kill:
            mine.close()
        kill.assert_not_called()

    def test_shutdown_shared_kills_all_and_resets_poll(self):
        proc = MagicMock()
        proc.poll.return_value = None
        renderer = HTMLRenderer("test")
        with patch.object(htmlmod, "_chrome_create_time", return_value=None):
            HTMLRenderer._register_chrome(proc, renderer)
        HTMLRenderer._poll_targets.append(renderer)
        HTMLRenderer._poll_armed = True
        htmlmod._chrome_available_cache = True
        with patch.object(htmlmod, "_kill_process_tree") as kill:
            HTMLRenderer.shutdown_shared()
        kill.assert_called_once_with(proc)
        assert HTMLRenderer._chrome_procs == []
        assert HTMLRenderer._poll_targets == []
        assert HTMLRenderer._poll_armed is False
        assert htmlmod._chrome_available_cache is None

    def test_popen_run_aborts_when_generation_changed(self):
        renderer = HTMLRenderer("test")
        renderer._render_generation = 2
        htmlmod._chrome_owner.renderer = renderer
        htmlmod._chrome_owner.generation = 1
        with patch.object(subprocess, "Popen") as popen, pytest.raises(_ChromeCancelled):
            _chrome_popen_run(["chrome"])
        popen.assert_not_called()

    def test_popen_run_kills_if_stale_after_spawn(self):
        renderer = HTMLRenderer("test")
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
        with (
            patch.object(subprocess, "Popen", side_effect=popen),
            patch.object(htmlmod, "_kill_process_tree") as kill,
            pytest.raises(_ChromeCancelled),
        ):
            _chrome_popen_run(["chrome"])
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
        with (
            patch.object(subprocess, "Popen", return_value=proc),
            patch.object(htmlmod, "_kill_process_tree") as kill,
            pytest.raises(subprocess.TimeoutExpired),
        ):
            _chrome_popen_run(["chrome"], timeout=0.01)
        kill.assert_called_once_with(proc)

    @pytest.mark.skipif(
        not html_available(),
        reason="html2image backend not importable in this environment",
    )
    def test_chromium_run_hook_is_installed(self):
        with patch.object(htmlmod, "_chromium_run_patched", False):
            _ensure_chromium_run_hook()
            import html2image.browsers.chromium as chromium_mod

            assert isinstance(chromium_mod.subprocess, htmlmod._ChromiumSubprocessProxy)

    @pytest.mark.skipif(
        not html_available(),
        reason="html2image backend not importable in this environment",
    )
    def test_shutdown_shared_unpatches_html2image_hook(self):
        _ensure_chromium_run_hook()
        import html2image.browsers.chromium as chromium_mod

        assert isinstance(chromium_mod.subprocess, htmlmod._ChromiumSubprocessProxy)
        HTMLRenderer.shutdown_shared()
        assert htmlmod._chromium_run_patched is False
        assert not isinstance(chromium_mod.subprocess, htmlmod._ChromiumSubprocessProxy)
        _ensure_chromium_run_hook()

    def test_kill_process_tree_skips_reused_pid(self):
        proc = MagicMock()
        proc.poll.return_value = None
        proc.pid = 4242
        parent = MagicMock()
        parent.create_time.return_value = 100.0
        fake_psutil = MagicMock()
        fake_psutil.Process.return_value = parent
        with patch.object(htmlmod, "_psutil", fake_psutil):
            htmlmod._kill_process_tree(proc, 10.0)
        parent.kill.assert_not_called()
        proc.kill.assert_not_called()

    def test_retry_rmtree_retries_then_ignores(self, tmp_path, monkeypatch):
        target = tmp_path / "locked"
        target.mkdir()
        calls = {"n": 0}

        def boom(_path, ignore_errors=False):
            calls["n"] += 1
            if ignore_errors:
                return
            raise OSError("locked")

        monkeypatch.setattr(htmlmod.shutil, "rmtree", boom)
        monkeypatch.setattr(htmlmod.time, "sleep", lambda _seconds: None)
        htmlmod._retry_rmtree(str(target), attempts=2)
        assert calls["n"] == 3

    def test_env_helpers_clamp_and_reject_garbage(self, monkeypatch):
        monkeypatch.setenv("DPG_TEST_LIMIT", "99999")
        assert htmlmod._env_int("DPG_TEST_LIMIT", 10, minimum=1, maximum=20) == 20
        monkeypatch.setenv("DPG_TEST_LIMIT", "nope")
        assert htmlmod._env_int("DPG_TEST_LIMIT", 10, minimum=1, maximum=20) == 10
        monkeypatch.setenv("DPG_TEST_LIMIT", "0.05")
        assert htmlmod._env_float("DPG_TEST_LIMIT", 0.4, minimum=0.1, maximum=1.0) == 0.1
        monkeypatch.delenv("DPG_TEST_LIMIT", raising=False)
        assert htmlmod._env_int("DPG_TEST_LIMIT", 10, minimum=1, maximum=20) == 10


class TestKeepFirstScreenshot:
    def test_keeps_first_capture_when_wider_shot_fails(self, tmp_path):
        image = pytest.importorskip("PIL.Image")
        renderer = HTMLRenderer("test")
        renderer._html_content = "<p>x</p>"
        renderer._trusted = True
        renderer._render_generation = 1
        first = image.new("RGBA", (100, 40), _BG_COLOR_RGBA)
        first.putpixel((3, 3), (1, 244, 255, 255))  # scroll_w = 500
        first.putpixel((4, 3), (17, 34, 51, 255))
        first.putpixel((3, 4), (0, 20, 255, 255))  # scroll_h = 20
        first.putpixel((20, 20), (255, 0, 0, 255))
        session = _fake_session(tmp_path)
        with (
            patch.object(renderer, "_create_chrome_session", return_value=session),
            patch.object(renderer, "_hti_screenshot", side_effect=[first, RuntimeError("second failed")]),
        ):
            renderer._render_worker(100, 1, renderer._html_content, True)
        assert renderer._pending_render is not None
        assert renderer._pending_render.error is None
        assert renderer._pending_render.chrome_width == 100
        session.cleanup.assert_called_once()
