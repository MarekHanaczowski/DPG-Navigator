"""Shared fixtures for dpg_navigator tests."""

import os
import sys
import tempfile
import shutil

import pytest

# Ensure dpg_navigator package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture
def tmp_tree(tmp_path):
    """Create a temporary directory tree for filesystem tests.

    Structure:
        tmp_path/
        ├── file_a.txt       (10 bytes)
        ├── file_b.py        (20 bytes)
        ├── image.png         (5 bytes)
        ├── .hidden_file      (3 bytes)
        ├── dir_alpha/
        │   ├── nested.txt    (7 bytes)
        │   └── .hidden_dir/  (empty)
        ├── dir_beta/         (empty)
        └── .hidden_dir/      (empty)
    """
    # Files
    (tmp_path / "file_a.txt").write_text("0123456789")
    (tmp_path / "file_b.py").write_text("01234567890123456789")
    (tmp_path / "image.png").write_bytes(b"\x89PNG\x00")
    (tmp_path / ".hidden_file").write_text("abc")

    # Directories
    (tmp_path / "dir_alpha").mkdir()
    (tmp_path / "dir_alpha" / "nested.txt").write_text("1234567")
    (tmp_path / "dir_alpha" / ".hidden_dir").mkdir()
    (tmp_path / "dir_beta").mkdir()
    (tmp_path / ".hidden_dir").mkdir()

    return tmp_path


@pytest.fixture
def empty_dir(tmp_path):
    """Create an empty temporary directory."""
    d = tmp_path / "empty"
    d.mkdir()
    return d
