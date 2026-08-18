"""DearPyGui preview renderers (image, text, data, archive, document, font).

Each implements ``BaseRenderer`` and is driven by ``PreviewPanel``. Parsing
stays in the GUI-free ``_preview_*.py`` loaders.
"""

from __future__ import annotations
