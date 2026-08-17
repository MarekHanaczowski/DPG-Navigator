"""Tests for dpg_navigator._platform — cross-platform abstractions.

Tests all functions including is_mod_key_down() (mocked DPG).
"""

from __future__ import annotations

import os
import platform
from unittest.mock import MagicMock, patch

import pytest

from dpg_navigator._platform import (
    _INVALID_FILE_ATTRIBUTES,
    get_drives,
    get_file_time,
    get_special_dirs,
    is_hidden,
    is_mod_key_down,
)

# ── is_hidden ───────────────────────────────────────────────────


class TestIsHidden:
    def test_dot_prefix_is_hidden(self, tmp_path):
        f = tmp_path / ".hidden"
        f.write_text("x")
        assert is_hidden(str(f)) is True

    def test_no_dot_prefix_not_hidden(self, tmp_path):
        f = tmp_path / "visible.txt"
        f.write_text("x")
        assert is_hidden(str(f)) is False

    def test_dotfile_in_subdirectory(self, tmp_path):
        d = tmp_path / "sub"
        d.mkdir()
        f = d / ".config"
        f.write_text("x")
        assert is_hidden(str(f)) is True

    def test_regular_file_in_dot_directory(self, tmp_path):
        """A regular file inside a hidden dir — only basename matters."""
        d = tmp_path / ".hidden_dir"
        d.mkdir()
        f = d / "regular.txt"
        f.write_text("x")
        # is_hidden checks basename of the FILE, not the parent
        assert is_hidden(str(f)) is False

    def test_hidden_directory(self, tmp_path):
        d = tmp_path / ".secret"
        d.mkdir()
        assert is_hidden(str(d)) is True

    def test_regular_directory(self, tmp_path):
        d = tmp_path / "normal"
        d.mkdir()
        assert is_hidden(str(d)) is False

    def test_double_dot_prefix(self, tmp_path):
        f = tmp_path / "..weird"
        f.write_text("x")
        assert is_hidden(str(f)) is True

    @pytest.mark.skipif(os.name != "nt", reason="Windows-only test")
    def test_windows_hidden_attribute(self, tmp_path):
        """On Windows, test the NTFS hidden attribute detection."""
        import ctypes

        f = tmp_path / "win_hidden.txt"
        f.write_text("x")

        # Set hidden attribute
        FILE_ATTRIBUTE_HIDDEN = 0x2
        ctypes.windll.kernel32.SetFileAttributesW(str(f), FILE_ATTRIBUTE_HIDDEN)

        try:
            assert is_hidden(str(f)) is True
        finally:
            # Remove hidden attribute
            ctypes.windll.kernel32.SetFileAttributesW(str(f), 0)


# ── get_file_time ───────────────────────────────────────────────


class TestGetFileTime:
    def test_returns_float(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        result = get_file_time(str(f))
        assert isinstance(result, float)

    def test_positive_value(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        result = get_file_time(str(f))
        assert result > 0

    def test_recent_file_time(self, tmp_path):
        """Newly created file should have a recent modification time."""
        import time

        f = tmp_path / "new.txt"
        f.write_text("data")
        result = get_file_time(str(f))
        assert abs(result - time.time()) < 5  # within 5 seconds

    def test_directory_time(self, tmp_path):
        d = tmp_path / "mydir"
        d.mkdir()
        result = get_file_time(str(d))
        assert isinstance(result, float)
        assert result > 0

    def test_nonexistent_raises(self, tmp_path):
        with pytest.raises(OSError):
            get_file_time(str(tmp_path / "nonexistent"))


# ── get_special_dirs ────────────────────────────────────────────


class TestGetSpecialDirs:
    def test_returns_dict(self):
        result = get_special_dirs()
        assert isinstance(result, dict)

    def test_home_always_present(self):
        result = get_special_dirs()
        assert "Home" in result

    def test_home_path_is_valid(self):
        result = get_special_dirs()
        assert os.path.isdir(result["Home"])

    def test_home_matches_expanduser(self):
        result = get_special_dirs()
        assert result["Home"] == os.path.expanduser("~")

    def test_all_paths_are_existing_dirs(self):
        result = get_special_dirs()
        for name, path in result.items():
            assert os.path.isdir(path), f"{name}: {path} does not exist"

    def test_expected_keys_subset(self):
        """At least Home should always exist; others depend on OS."""
        result = get_special_dirs()
        assert "Home" in result

    def test_values_are_strings(self):
        result = get_special_dirs()
        for name, path in result.items():
            assert isinstance(path, str), f"{name}: path is not a string"

    def test_values_are_absolute(self):
        result = get_special_dirs()
        for name, path in result.items():
            assert os.path.isabs(path), f"{name}: {path} is not absolute"


# ── get_special_dirs (mocked platform branches) ─────────────────


class TestGetSpecialDirsMocked:
    """Test Linux and macOS branches via mocking _SYSTEM."""

    def test_linux_calls_xdg_dir(self, tmp_path):
        """On Linux, get_special_dirs should call _get_xdg_dir for each name."""
        home = str(tmp_path / "fakehome")
        os.makedirs(home)
        # Create expected directories
        for name in ("Desktop", "Downloads", "Pictures", "Documents", "Music", "Videos"):
            os.makedirs(os.path.join(home, name))

        with patch("dpg_navigator._platform._SYSTEM", "Linux"), patch(
            "dpg_navigator._platform.os.path.expanduser", return_value=home
        ), patch("dpg_navigator._platform._get_xdg_dir", return_value=None) as mock_xdg:
            result = get_special_dirs()

        # _get_xdg_dir should have been called for each of the 6 directory names
        assert mock_xdg.call_count == 6
        assert result["Home"] == home

    def test_linux_xdg_dir_used_when_available(self, tmp_path):
        """When _get_xdg_dir returns a path, it should be used instead of fallback."""
        home = str(tmp_path / "fakehome")
        custom_docs = str(tmp_path / "Dokumenty")
        os.makedirs(home)
        os.makedirs(custom_docs)
        for name in ("Desktop", "Downloads", "Pictures", "Music", "Videos"):
            os.makedirs(os.path.join(home, name))

        def mock_xdg_side_effect(name):
            if name == "Documents":
                return custom_docs
            return None

        with patch("dpg_navigator._platform._SYSTEM", "Linux"), patch(
            "dpg_navigator._platform.os.path.expanduser", return_value=home
        ), patch("dpg_navigator._platform._get_xdg_dir", side_effect=mock_xdg_side_effect):
            result = get_special_dirs()

        assert result["Documents"] == custom_docs

    def test_darwin_videos_maps_to_movies(self, tmp_path):
        """On macOS, 'Videos' should be mapped to 'Movies' directory."""
        home = str(tmp_path / "fakehome")
        os.makedirs(home)
        # Create Movies instead of Videos (macOS convention)
        for name in ("Desktop", "Downloads", "Pictures", "Documents", "Music", "Movies"):
            os.makedirs(os.path.join(home, name))

        with patch("dpg_navigator._platform._SYSTEM", "Darwin"), patch(
            "dpg_navigator._platform.os.path.expanduser", return_value=home
        ):
            result = get_special_dirs()

        # "Videos" key should point to the "Movies" directory
        assert result["Videos"] == os.path.join(home, "Movies")

    def test_nonexistent_dirs_filtered_out(self, tmp_path):
        """Directories that don't exist should be excluded from results."""
        home = str(tmp_path / "fakehome")
        os.makedirs(home)
        # Only create Desktop — others don't exist
        os.makedirs(os.path.join(home, "Desktop"))

        def fake_query(key, name):
            return os.path.join(home, name), 1

        mock_winreg = MagicMock()
        mock_winreg.OpenKey.return_value = MagicMock(__enter__=MagicMock(), __exit__=MagicMock())
        mock_winreg.QueryValueEx.side_effect = fake_query

        with patch("dpg_navigator._platform._SYSTEM", "Windows"), patch(
            "dpg_navigator._platform.os.path.expanduser", return_value=home
        ), patch("dpg_navigator._platform.winreg", mock_winreg, create=True):
            result = get_special_dirs()

        assert "Home" in result
        assert "Desktop" in result
        # Non-existent dirs should be excluded
        assert "Downloads" not in result
        assert "Music" not in result


# ── get_drives ──────────────────────────────────────────────────


class TestGetDrives:
    def test_returns_list(self):
        result = get_drives()
        assert isinstance(result, list)

    def test_not_empty(self):
        """Should have at least one drive/mount point."""
        result = get_drives()
        assert len(result) > 0

    def test_all_strings(self):
        result = get_drives()
        for drive in result:
            assert isinstance(drive, str)

    def test_all_absolute_paths(self):
        result = get_drives()
        for drive in result:
            assert os.path.isabs(drive), f"{drive} is not an absolute path"

    @pytest.mark.skipif(os.name != "nt", reason="Windows-only")
    def test_windows_has_c_drive(self):
        result = get_drives()
        assert any("C:\\" in d for d in result)

    @pytest.mark.skipif(os.name == "nt", reason="Unix-only")
    def test_unix_has_root(self):
        result = get_drives()
        assert "/" in result

    def test_psutil_failure_returns_empty_list(self):
        """If psutil fails on non-Darwin, result should be an empty list."""
        with patch("dpg_navigator._platform.psutil") as mock_psutil, patch(
            "dpg_navigator._platform._SYSTEM", "Windows"
        ):
            mock_psutil.disk_partitions.side_effect = OSError("simulated failure")
            result = get_drives()
            assert result == []

    def test_psutil_permission_error_returns_empty(self):
        """PermissionError is also handled gracefully."""
        with patch("dpg_navigator._platform.psutil") as mock_psutil, patch(
            "dpg_navigator._platform._SYSTEM", "Windows"
        ):
            mock_psutil.disk_partitions.side_effect = PermissionError("access denied")
            result = get_drives()
            assert result == []


# ── _INVALID_FILE_ATTRIBUTES ───────────────────────────────────


class TestConstants:
    def test_invalid_file_attributes_value(self):
        assert _INVALID_FILE_ATTRIBUTES == -1


# ── is_hidden edge cases ───────────────────────────────────────


class TestIsHiddenEdgeCases:
    @pytest.mark.skipif(os.name != "nt", reason="Windows root path test")
    def test_root_c_drive_has_hidden_attribute(self):
        """On Windows, C:\\ has the HIDDEN system attribute set (attr=22).
        This is real Windows behavior — root drives are system+hidden."""
        assert is_hidden("C:\\") is True

    @pytest.mark.skipif(os.name == "nt", reason="Unix root path test")
    def test_root_slash_not_hidden(self):
        assert is_hidden("/") is False

    @pytest.mark.skipif(os.name == "nt", reason="Symlinks need privileges on Windows")
    def test_symlink_to_hidden_file_not_hidden(self, tmp_path):
        """A visible symlink pointing to a hidden file is NOT hidden."""
        hidden = tmp_path / ".secret"
        hidden.write_text("x")
        link = tmp_path / "visible_link"
        link.symlink_to(hidden)
        assert is_hidden(str(link)) is False

    @pytest.mark.skipif(os.name == "nt", reason="Symlinks need privileges on Windows")
    def test_hidden_symlink_is_hidden(self, tmp_path):
        """A dot-prefixed symlink is hidden regardless of target."""
        target = tmp_path / "visible.txt"
        target.write_text("x")
        link = tmp_path / ".hidden_link"
        link.symlink_to(target)
        assert is_hidden(str(link)) is True

    @pytest.mark.skipif(os.name != "nt", reason="Windows-only: INVALID_FILE_ATTRIBUTES")
    def test_invalid_file_attributes_returns_false(self):
        """When GetFileAttributesW returns -1 (file not found), is_hidden
        should fall through to return False."""
        assert is_hidden(r"C:\__nonexistent_path_1234567890__") is False


# ── is_mod_key_down (mocked DPG) ─────────────────────────────


class TestIsModKeyDown:
    """Test is_mod_key_down() by mocking dpg.is_key_down."""

    def test_darwin_left_super(self):
        """On macOS, left Command key should return True."""
        with patch("dpg_navigator._platform._SYSTEM", "Darwin"), patch("dpg_navigator._platform.dpg") as mock_dpg:
            mock_dpg.mvKey_LSuper = 343
            mock_dpg.mvKey_RSuper = 347
            mock_dpg.is_key_down.side_effect = lambda k: k == 343
            assert is_mod_key_down() is True

    def test_darwin_right_super(self):
        """On macOS, right Command key should return True."""
        with patch("dpg_navigator._platform._SYSTEM", "Darwin"), patch("dpg_navigator._platform.dpg") as mock_dpg:
            mock_dpg.mvKey_LSuper = 343
            mock_dpg.mvKey_RSuper = 347
            mock_dpg.is_key_down.side_effect = lambda k: k == 347
            assert is_mod_key_down() is True

    def test_darwin_no_key_pressed(self):
        """On macOS, no modifier key pressed should return False."""
        with patch("dpg_navigator._platform._SYSTEM", "Darwin"), patch("dpg_navigator._platform.dpg") as mock_dpg:
            mock_dpg.mvKey_LSuper = 343
            mock_dpg.mvKey_RSuper = 347
            mock_dpg.is_key_down.return_value = False
            assert is_mod_key_down() is False

    def test_windows_left_ctrl(self):
        """On Windows/Linux, left Ctrl key should return True."""
        with patch("dpg_navigator._platform._SYSTEM", "Windows"), patch("dpg_navigator._platform.dpg") as mock_dpg:
            mock_dpg.mvKey_LControl = 341
            mock_dpg.mvKey_RControl = 345
            mock_dpg.is_key_down.side_effect = lambda k: k == 341
            assert is_mod_key_down() is True

    def test_windows_right_ctrl(self):
        """On Windows/Linux, right Ctrl key should return True."""
        with patch("dpg_navigator._platform._SYSTEM", "Windows"), patch("dpg_navigator._platform.dpg") as mock_dpg:
            mock_dpg.mvKey_LControl = 341
            mock_dpg.mvKey_RControl = 345
            mock_dpg.is_key_down.side_effect = lambda k: k == 345
            assert is_mod_key_down() is True

    def test_windows_no_key_pressed(self):
        """On Windows/Linux, no modifier key should return False."""
        with patch("dpg_navigator._platform._SYSTEM", "Windows"), patch("dpg_navigator._platform.dpg") as mock_dpg:
            mock_dpg.mvKey_LControl = 341
            mock_dpg.mvKey_RControl = 345
            mock_dpg.is_key_down.return_value = False
            assert is_mod_key_down() is False

    def test_linux_uses_ctrl_not_super(self):
        """On Linux, Ctrl (not Super) should be the modifier."""
        with patch("dpg_navigator._platform._SYSTEM", "Linux"), patch("dpg_navigator._platform.dpg") as mock_dpg:
            mock_dpg.mvKey_LControl = 341
            mock_dpg.mvKey_RControl = 345
            mock_dpg.is_key_down.side_effect = lambda k: k == 341
            assert is_mod_key_down() is True


# ── _get_xdg_dir (Linux-only, mocked) ─────────────────────────


class TestGetXdgDir:
    @pytest.fixture(autouse=True)
    def _skip_non_linux(self):
        if platform.system() != "Linux":
            pytest.skip("Linux-only test")

    def test_valid_dir_returned(self, tmp_path):
        from dpg_navigator._platform import _get_xdg_dir

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=str(tmp_path) + "\n")
            result = _get_xdg_dir("DOCUMENTS")
        assert result == str(tmp_path)

    def test_downloads_uses_xdg_download_key(self, tmp_path):
        from dpg_navigator._platform import _get_xdg_dir

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=str(tmp_path) + "\n")
            result = _get_xdg_dir("Downloads")

        assert result == str(tmp_path)
        mock_run.assert_called_once_with(
            ["xdg-user-dir", "DOWNLOAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )

    def test_decode_error_returns_none(self):
        from dpg_navigator._platform import _get_xdg_dir

        with patch(
            "subprocess.run",
            side_effect=UnicodeDecodeError("utf-8", b"", 0, 1, "invalid byte"),
        ):
            assert _get_xdg_dir("Documents") is None

    def test_nonexistent_dir_returns_none(self):
        from dpg_navigator._platform import _get_xdg_dir

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="/nonexistent/path\n")
            result = _get_xdg_dir("DOCUMENTS")
        assert result is None

    def test_timeout_returns_none(self):
        import subprocess

        from dpg_navigator._platform import _get_xdg_dir

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="xdg-user-dir", timeout=2)
            result = _get_xdg_dir("DOCUMENTS")
        assert result is None

    def test_command_not_found_returns_none(self):
        from dpg_navigator._platform import _get_xdg_dir

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("xdg-user-dir not found")
            result = _get_xdg_dir("DOCUMENTS")
        assert result is None

    def test_nonzero_return_code_returns_none(self):
        from dpg_navigator._platform import _get_xdg_dir

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            result = _get_xdg_dir("DOCUMENTS")
        assert result is None


# ── get_drives Darwin /Volumes fallback ────────────────────────


class TestGetDrivesDarwin:
    def test_darwin_volumes_added(self):
        """On Darwin, /Volumes entries should be included."""
        mock_partition = MagicMock()
        mock_partition.mountpoint = "/"

        # Use posixpath.join to get correct / separators regardless of host OS
        import posixpath

        with patch("dpg_navigator._platform._SYSTEM", "Darwin"), patch(
            "dpg_navigator._platform.psutil"
        ) as mock_psutil, patch("dpg_navigator._platform.os.listdir", return_value=["Macintosh HD", "USB"]), patch(
            "dpg_navigator._platform.os.path.join", side_effect=posixpath.join
        ):
            mock_psutil.disk_partitions.return_value = [mock_partition]
            result = get_drives()

        assert "/" in result
        assert "/Volumes/Macintosh HD" in result
        assert "/Volumes/USB" in result

    def test_darwin_volumes_no_duplicates(self):
        """If psutil already returns a /Volumes path, don't duplicate it."""
        mock_p1 = MagicMock(mountpoint="/")
        mock_p2 = MagicMock(mountpoint="/Volumes/USB")

        import posixpath

        with patch("dpg_navigator._platform._SYSTEM", "Darwin"), patch(
            "dpg_navigator._platform.psutil"
        ) as mock_psutil, patch("dpg_navigator._platform.os.listdir", return_value=["USB"]), patch(
            "dpg_navigator._platform.os.path.join", side_effect=posixpath.join
        ):
            mock_psutil.disk_partitions.return_value = [mock_p1, mock_p2]
            result = get_drives()

        assert result.count("/Volumes/USB") == 1

    def test_darwin_volumes_oserror_handled(self):
        """If os.listdir('/Volumes') raises OSError, drives from psutil still returned."""
        mock_partition = MagicMock(mountpoint="/")

        with patch("dpg_navigator._platform._SYSTEM", "Darwin"), patch(
            "dpg_navigator._platform.psutil"
        ) as mock_psutil, patch("dpg_navigator._platform.os.listdir", side_effect=OSError("permission denied")):
            mock_psutil.disk_partitions.return_value = [mock_partition]
            result = get_drives()

        assert "/" in result
