"""Tests for secure XML preview handling."""

from __future__ import annotations

from unittest.mock import patch

from dpg_navigator._types import FileEntry
from dpg_navigator.renderers.data import DataRenderer


class TestXmlPreview:
    def test_external_entities_are_not_expanded(self, tmp_path):
        secret_path = tmp_path / "secret.txt"
        secret_path.write_text("do-not-read")
        raw_xml = f'<!DOCTYPE data [<!ENTITY secret SYSTEM "{secret_path.as_uri()}">]><data>&secret;</data>'
        renderer = DataRenderer(lambda path, offset: (raw_xml, False))
        renderer._panel_id = "panel"
        renderer._config_tag = "xml-test"
        entry = FileEntry("sample.xml", "sample.xml", False, len(raw_xml), 0.0, False)

        with patch("dpg_navigator.renderers.data.dpg") as mock_dpg:
            mock_dpg.does_item_exist.return_value = False
            renderer._render_xml_preview(entry)

        mock_dpg.add_text.assert_any_call(raw_xml, wrap=0)
        assert "do-not-read" not in [str(call) for call in mock_dpg.add_text.call_args_list]
