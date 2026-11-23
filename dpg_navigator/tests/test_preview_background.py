"""Background preview loading: PreviewPanel's queue and the renderer jobs.

DearPyGui is mocked. ``JobManager.submit`` is replaced by a list so each
test decides when the "worker" runs.
"""

from __future__ import annotations

import io
from concurrent.futures import Future
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from dpg_navigator._preview import LOADING_PLACEHOLDER_DELAY, PreviewPanel
from dpg_navigator._preview_registry import PreviewCapabilities, PreviewKind
from dpg_navigator._types import DialogConfig, FileEntry
from dpg_navigator.renderers._base import PreviewContext


def _entry(name: str, path: str | None = None, size: int = 10) -> FileEntry:
    return FileEntry(name, path or f"/data/{name}", is_dir=False, size_bytes=size, modified_time=0.0, is_hidden=False)


class _FakeRenderer:
    """Records which jobs ran and which finish steps were applied."""

    def __init__(self) -> None:
        self.jobs: list[str] = []
        self.finished: list[str] = []
        self.cleared = 0
        self.fail_job = False

    def prepare(self, entry: FileEntry, ctx: PreviewContext) -> Any:
        def job() -> Any:
            self.jobs.append(entry.name)
            if self.fail_job:
                raise RuntimeError("decoder exploded")
            return lambda: self.finished.append(entry.name)

        return job

    def render(self, entry: FileEntry, ctx: PreviewContext) -> None:
        self.prepare(entry, ctx)()()

    def clear(self) -> None:
        self.cleared += 1


@pytest.fixture
def mock_dpg():
    with patch("dpg_navigator._preview.dpg") as m:
        m.does_item_exist.return_value = True
        yield m


@pytest.fixture
def workers():
    """Capture submitted worker functions instead of running them."""
    submitted: list[tuple[Any, Future[Any]]] = []

    def submit(fn: Any, *args: Any) -> Future[Any]:
        future: Future[Any] = Future()
        submitted.append((fn, future))
        return future

    with patch("dpg_navigator._preview.JobManager.submit", side_effect=submit):
        yield submitted


def _run_workers(workers: list[tuple[Any, Future[Any]]]) -> None:
    while workers:
        fn, future = workers.pop(0)
        future.set_running_or_notify_cancel()
        fn()
        future.set_result(None)


@pytest.fixture
def panel(mock_dpg):
    p = PreviewPanel(DialogConfig(tag="bg_test"), preview_width=300, show=True)
    p.attach(table_wrapper=5, panel_id=7)
    fake = _FakeRenderer()
    p._renderers[PreviewKind.TEXT] = fake  # type: ignore[assignment]
    p.fake = fake  # type: ignore[attr-defined]
    return p


class TestSynchronousWithoutNotifier:
    def test_update_loads_and_renders_in_place(self, panel, workers):
        panel.update(_entry("a.txt"))
        assert panel.fake.finished == ["a.txt"]
        assert workers == []
        assert not panel.has_pending()

    def test_run_in_background_runs_in_place(self, panel, workers):
        done: list[str] = []
        panel.ctx.run_in_background("sheet", lambda: lambda: done.append("x"))
        assert done == ["x"]
        assert workers == []


class TestBackgroundQueue:
    def test_job_runs_on_worker_and_finish_on_apply(self, panel, workers):
        notify = MagicMock()
        panel.set_notifier(notify)
        panel.update(_entry("a.txt"))

        assert panel.fake.jobs == []
        assert panel.has_pending()
        assert len(workers) == 1
        notify.assert_called()  # keeps the dialog in the frame pump

        notify.reset_mock()
        _run_workers(workers)
        assert panel.fake.jobs == ["a.txt"]
        assert panel.fake.finished == []
        notify.assert_called_once()

        panel.apply_pending()
        assert panel.fake.finished == ["a.txt"]
        assert panel._current_entry.name == "a.txt"
        assert panel._active_renderer is panel.fake
        assert not panel.has_pending()

    def test_burst_of_selections_runs_only_the_newest_job(self, panel, workers):
        panel.set_notifier(lambda: None)
        for name in ("a.txt", "b.txt", "c.txt"):
            panel.update(_entry(name))
        assert len(workers) == 1, "one worker drains the queue"

        _run_workers(workers)
        panel.apply_pending()
        assert panel.fake.jobs == ["c.txt"]
        assert panel.fake.finished == ["c.txt"]

    def test_selecting_a_folder_drops_the_pending_load(self, panel, workers):
        panel.set_notifier(lambda: None)
        panel.update(_entry("a.txt"))
        panel.update(FileEntry("dir", "/data/dir", is_dir=True, size_bytes=None, modified_time=0.0, is_hidden=False))

        _run_workers(workers)
        panel.apply_pending()
        assert panel.fake.jobs == []
        assert panel.fake.finished == []
        assert not panel.has_pending()

    def test_result_superseded_while_job_runs_is_not_published(self, panel, workers):
        panel.set_notifier(lambda: None)
        original_prepare = panel.fake.prepare

        def prepare_and_supersede(entry, ctx):
            job = original_prepare(entry, ctx)

            def racing_job():
                finish = job()
                panel._cancel_pending_load()  # a newer request arrives meanwhile
                return finish

            return racing_job

        panel.fake.prepare = prepare_and_supersede
        panel.update(_entry("a.txt"))
        _run_workers(workers)
        panel.apply_pending()
        assert panel.fake.jobs == ["a.txt"]
        assert panel.fake.finished == []

    def test_job_error_is_shown_in_the_panel(self, panel, workers, mock_dpg):
        panel.set_notifier(lambda: None)
        panel.fake.fail_job = True
        panel.update(_entry("a.txt"))
        _run_workers(workers)
        panel.apply_pending()
        texts = [call.args[0] for call in mock_dpg.add_text.call_args_list]
        assert "Preview failed" in texts
        assert "decoder exploded" in texts

    def test_worker_cancelled_by_shutdown_frees_the_queue(self, panel, workers):
        panel.set_notifier(lambda: None)
        panel.update(_entry("a.txt"))
        _fn, future = workers.pop()
        future.cancel()
        assert panel._worker_busy is False

        panel.update(_entry("b.txt"))
        assert len(workers) == 1, "a new worker starts after the cancelled one"

    def test_shutdown_forgets_pending_work(self, panel, workers):
        panel.set_notifier(lambda: None)
        panel.update(_entry("a.txt"))
        panel.shutdown()
        _run_workers(workers)
        panel.apply_pending()
        assert panel.fake.finished == []
        assert not panel.has_pending()
        assert panel._notify is None


class TestDeferredClearAndPlaceholder:
    def test_old_preview_stays_until_the_new_one_is_ready(self, panel, workers, mock_dpg):
        panel.set_notifier(lambda: None)
        panel.update(_entry("a.txt"))
        _run_workers(workers)
        panel.apply_pending()
        mock_dpg.delete_item.reset_mock()

        with patch("dpg_navigator._preview.time.monotonic", return_value=1000.0):
            panel.update(_entry("b.txt"))
            panel.apply_pending()
        mock_dpg.delete_item.assert_not_called()
        assert panel._current_entry.name == "a.txt"

    def test_loading_line_appears_after_the_delay(self, panel, workers, mock_dpg):
        panel.set_notifier(lambda: None)
        with patch("dpg_navigator._preview.time.monotonic", return_value=1000.0):
            panel.update(_entry("slow.txt"))
            panel.apply_pending()
        assert not any("Loading" in str(c.args[0]) for c in mock_dpg.add_text.call_args_list)

        with patch("dpg_navigator._preview.time.monotonic", return_value=1000.0 + LOADING_PLACEHOLDER_DELAY):
            panel.apply_pending()
            panel.apply_pending()
        loading = [c for c in mock_dpg.add_text.call_args_list if "Loading" in str(c.args[0])]
        assert len(loading) == 1
        assert loading[0].args[0] == "Loading slow.txt..."
        assert panel.has_pending(), "still waiting for the job"

        _run_workers(workers)
        panel.apply_pending()
        assert panel.fake.finished == ["slow.txt"]

    def test_follow_up_load_keeps_the_renderer(self, panel, workers):
        panel.set_notifier(lambda: None)
        panel.update(_entry("a.txt"))
        _run_workers(workers)
        panel.apply_pending()

        done: list[str] = []
        panel.ctx.run_in_background("Sheet2", lambda: lambda: done.append("sheet"))
        assert done == []
        _run_workers(workers)
        panel.apply_pending()
        assert done == ["sheet"]
        assert panel._active_renderer is panel.fake
        assert panel.fake.cleared == 0


class TestTextEncodingPerFile:
    def test_later_page_reuses_only_the_same_files_encoding(self, panel, tmp_path):
        utf16 = tmp_path / "wide.txt"
        utf16.write_bytes("hello".encode("utf-16"))
        plain = tmp_path / "plain.txt"
        plain.write_bytes(b"xabc")

        panel._load_text_content(str(utf16), 0)
        assert panel._text_encoding == (str(utf16), "utf-16")
        text, is_bin = panel._load_text_content(str(plain), 1)
        assert (text, is_bin) == ("abc", False)


# ── Renderer jobs never call DearPyGui ──────────────────────────


def _read_text(path: str, offset: int) -> tuple[str, bool]:
    return Path(path).read_text(encoding="utf-8")[offset:], False


def _ctx() -> PreviewContext:
    return PreviewContext(panel_id=1, table_wrapper=2, config_tag="job_test", capabilities=PreviewCapabilities())


def _run_job_only(renderer: Any, entry: FileEntry, module: str, ctx: PreviewContext | None = None) -> Any:
    targets = ["dpg_navigator.renderers._base.dpg"]
    if module != "archive":  # archive.py draws through _base's table helper
        targets.append(f"dpg_navigator.renderers.{module}.dpg")
    with patch(targets[0]) as base_dpg, patch(targets[-1]) as mock_dpg:
        mock_dpg.get_item_rect_size.return_value = (500, 400)
        job = renderer.prepare(entry, ctx or _ctx())
        mock_dpg.reset_mock()
        base_dpg.reset_mock()
        finish = job()
        assert mock_dpg.mock_calls == [], f"worker job called DearPyGui: {mock_dpg.mock_calls}"
        assert base_dpg.mock_calls == [], f"worker job called DearPyGui: {base_dpg.mock_calls}"
    return finish


class TestJobsStayOffDearPyGui:
    def test_text_job(self, tmp_path):
        from dpg_navigator.renderers.text import TextRenderer

        path = tmp_path / "a.txt"
        path.write_text("hello", encoding="utf-8")
        renderer = TextRenderer(_read_text, lambda e: None)
        _run_job_only(renderer, _entry("a.txt", str(path)), "text")

    def test_csv_and_xml_jobs(self, tmp_path):
        from dpg_navigator.renderers.data import DataRenderer

        csv_path = tmp_path / "t.csv"
        csv_path.write_text("a,b\n1,2\n", encoding="utf-8")
        renderer = DataRenderer(_read_text)
        _run_job_only(renderer, _entry("t.csv", str(csv_path)), "data")
        xml_path = tmp_path / "t.xml"
        xml_path.write_text("<a><b/></a>", encoding="utf-8")
        _run_job_only(renderer, _entry("t.xml", str(xml_path)), "data")

    def test_sqlite_job(self, tmp_path):
        import sqlite3

        from dpg_navigator.renderers.data import DataRenderer

        db = tmp_path / "t.db"
        with sqlite3.connect(db) as conn:
            conn.execute("create table t (a)")
        renderer = DataRenderer(lambda p, o: (None, False))
        _run_job_only(renderer, _entry("t.db", str(db)), "data")

    def test_zip_job(self, tmp_path):
        import zipfile

        from dpg_navigator.renderers.archive import ArchiveRenderer

        archive = tmp_path / "a.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("inner.txt", "x")
        renderer = ArchiveRenderer(lambda e: None)
        _run_job_only(renderer, _entry("a.zip", str(archive)), "archive")

    def test_image_job_decodes_with_pillow(self, tmp_path):
        image = pytest.importorskip("PIL.Image")
        pytest.importorskip("numpy")
        from dpg_navigator.renderers.image import ImageRenderer

        path = tmp_path / "p.png"
        image.new("RGB", (64, 32), (10, 20, 30)).save(path)
        renderer = ImageRenderer()
        ctx = _ctx()
        finish = _run_job_only(renderer, _entry("p.png", str(path)), "image", ctx)
        with patch("dpg_navigator.renderers.image.dpg") as mock_dpg:
            mock_dpg.get_item_rect_size.return_value = (508, 408)
            mock_dpg.does_item_exist.return_value = False
            finish()
        mock_dpg.load_image.assert_not_called()
        assert mock_dpg.add_static_texture.call_args.kwargs["width"] == 64
        assert ctx.image_cache is not None and ctx.image_cache[:2] == (64, 32)

    def test_image_without_pillow_uses_stb_in_finish(self, tmp_path):
        from dpg_navigator.renderers.image import ImageRenderer

        path = tmp_path / "p.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + (4).to_bytes(4, "big") * 2 + b"\x00" * 16)
        renderer = ImageRenderer()
        with patch("dpg_navigator.renderers.image._PILImage", None):
            finish = _run_job_only(renderer, _entry("p.png", str(path)), "image")
        with patch("dpg_navigator.renderers.image.dpg") as mock_dpg:
            mock_dpg.load_image.return_value = (4, 4, 4, [0.0] * 64)
            mock_dpg.get_item_rect_size.return_value = (108, 108)
            mock_dpg.does_item_exist.return_value = False
            finish()
        mock_dpg.load_image.assert_called_once_with(str(path))

    def test_markdown_job_converts_and_sanitizes(self, tmp_path):
        pytest.importorskip("markdown")
        from dpg_navigator.renderers.document import DocumentRenderer

        path = tmp_path / "r.md"
        path.write_text("# Title\n\n<script>alert(1)</script>", encoding="utf-8")
        renderer = DocumentRenderer(_read_text)
        with patch("dpg_navigator.renderers.document.chrome_available", return_value=True):
            _run_job_only(renderer, _entry("r.md", str(path)), "document")

    def test_pptx_job_shrinks_images_to_the_shown_width(self, tmp_path):
        pptx = pytest.importorskip("pptx")
        image = pytest.importorskip("PIL.Image")
        from pptx.util import Inches

        from dpg_navigator.renderers.document import DocumentRenderer

        buf = io.BytesIO()
        image.new("RGB", (1600, 800), (200, 0, 0)).save(buf, "PNG")
        buf.seek(0)
        prs = pptx.Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.shapes.add_picture(buf, Inches(1), Inches(1), width=Inches(4))
        path = tmp_path / "deck.pptx"
        prs.save(path)

        renderer = DocumentRenderer(lambda p, o: (None, False))
        ctx = _ctx()
        finish = _run_job_only(renderer, _entry("deck.pptx", str(path)), "document", ctx)
        with patch("dpg_navigator.renderers.document.dpg") as mock_dpg:
            mock_dpg.does_item_exist.return_value = False
            finish()
        # Panel 500 px wide -> images capped at 460 px (500 - 40).
        texture = mock_dpg.add_static_texture.call_args.kwargs
        assert (texture["width"], texture["height"]) == (460, 230)
