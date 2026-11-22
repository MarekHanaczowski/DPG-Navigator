"""Tests for secure XML preview handling."""

from __future__ import annotations

from unittest.mock import patch

from dpg_navigator._preview_registry import PreviewCapabilities
from dpg_navigator._types import FileEntry
from dpg_navigator.renderers._base import PreviewContext
from dpg_navigator.renderers.data import DataRenderer, format_xml_preview


def test_format_xml_preview_pretty_prints():
    assert format_xml_preview("<a><b>x</b></a>").splitlines() == [
        '<?xml version="1.0" ?>',
        "<a>",
        "    <b>x</b>",
        "</a>",
    ]


def test_format_xml_preview_keeps_invalid_xml():
    assert format_xml_preview("<a><b>") == "<a><b>"


class TestXmlPreview:
    def test_external_entities_are_not_expanded(self, tmp_path):
        secret_path = tmp_path / "secret.txt"
        secret_path.write_text("do-not-read")
        raw_xml = f'<!DOCTYPE data [<!ENTITY secret SYSTEM "{secret_path.as_uri()}">]><data>&secret;</data>'
        renderer = DataRenderer(lambda path, offset: (raw_xml, False))
        ctx = PreviewContext(
            panel_id="panel", table_wrapper=0, config_tag="xml-test", capabilities=PreviewCapabilities()
        )
        entry = FileEntry("sample.xml", "sample.xml", False, len(raw_xml), 0.0, False)

        with patch("dpg_navigator.renderers.data.dpg") as mock_dpg:
            mock_dpg.does_item_exist.return_value = False
            renderer.render(entry, ctx)

        mock_dpg.add_text.assert_any_call(raw_xml, wrap=0)
        assert "do-not-read" not in [str(call) for call in mock_dpg.add_text.call_args_list]
