"""
Unit tests for fotointegrator utility functions.

These tests focus on pure functions without external dependencies (no API calls, no file I/O).
Run with: pytest test_fotointegrator.py -v
"""

import os
import tempfile
import shutil
from unittest.mock import patch, MagicMock

# Import functions to test
from run_fotointegrator import (
    extract_folder_id,
    should_convert_video,
    check_ffmpeg_installed,
    save_planned_file,
    load_planned_files,
    get_planned_files_log
)


class TestExtractFolderId:
    """Test folder ID extraction from URLs and direct IDs."""

    def test_extract_from_drive_url(self):
        """Test extracting folder ID from Google Drive URL."""
        url = "https://drive.google.com/drive/folders/0B08IQ87a7dKcY3VmMGhKblBWMzA"
        result = extract_folder_id(url)
        assert result == "0B08IQ87a7dKcY3VmMGhKblBWMzA"

    def test_extract_from_drive_url_with_params(self):
        """Test extracting folder ID from URL with query parameters."""
        url = "https://drive.google.com/drive/folders/0B08IQ87a7dKcY3VmMGhKblBWMzA?usp=sharing"
        result = extract_folder_id(url)
        assert result == "0B08IQ87a7dKcY3VmMGhKblBWMzA"

    def test_extract_from_direct_id(self):
        """Test that direct folder IDs are returned unchanged."""
        folder_id = "0B08IQ87a7dKcY3VmMGhKblBWMzA"
        result = extract_folder_id(folder_id)
        assert result == "0B08IQ87a7dKcY3VmMGhKblBWMzA"

    def test_extract_from_short_id(self):
        """Test with a shorter folder ID format."""
        folder_id = "1a2B3c4D5e6F7g8H9i0J"
        result = extract_folder_id(folder_id)
        assert result == "1a2B3c4D5e6F7g8H9i0J"


class TestShouldConvertVideo:
    """Test video format detection for conversion."""

    def test_mts_should_convert(self):
        """Test that MTS files should be converted."""
        assert should_convert_video("video.mts") is True
        assert should_convert_video("VIDEO.MTS") is True
        assert should_convert_video("00007.MTS") is True

    def test_m2ts_should_convert(self):
        """Test that M2TS files should be converted."""
        assert should_convert_video("video.m2ts") is True
        assert should_convert_video("VIDEO.M2TS") is True

    def test_avi_should_convert(self):
        """Test that AVI files should be converted."""
        assert should_convert_video("video.avi") is True
        assert should_convert_video("VIDEO.AVI") is True

    def test_mov_should_convert(self):
        """Test that MOV files should be converted."""
        assert should_convert_video("video.mov") is True
        assert should_convert_video("VIDEO.MOV") is True

    def test_mkv_should_convert(self):
        """Test that MKV files should be converted."""
        assert should_convert_video("video.mkv") is True

    def test_wmv_should_convert(self):
        """Test that WMV files should be converted."""
        assert should_convert_video("video.wmv") is True

    def test_mpg_should_convert(self):
        """Test that MPG/MPEG files should be converted."""
        assert should_convert_video("video.mpg") is True
        assert should_convert_video("video.mpeg") is True

    def test_mp4_should_not_convert(self):
        """Test that MP4 files should NOT be converted (already optimized)."""
        assert should_convert_video("video.mp4") is False
        assert should_convert_video("VIDEO.MP4") is False

    def test_jpg_should_not_convert(self):
        """Test that image files should NOT be converted."""
        assert should_convert_video("photo.jpg") is False
        assert should_convert_video("photo.jpeg") is False
        assert should_convert_video("photo.png") is False

    def test_no_extension_should_not_convert(self):
        """Test that files without extension should NOT be converted."""
        assert should_convert_video("videofile") is False

    def test_case_insensitive(self):
        """Test that extension matching is case-insensitive."""
        assert should_convert_video("Video.MtS") is True
        assert should_convert_video("VIDEO.mTs") is True


class TestCheckFfmpegInstalled:
    """Test ffmpeg installation detection."""

    def test_ffmpeg_installed(self):
        """Test detection when ffmpeg is installed."""
        with patch('shutil.which', return_value='/usr/local/bin/ffmpeg'):
            assert check_ffmpeg_installed() is True

    def test_ffmpeg_not_installed(self):
        """Test detection when ffmpeg is not installed."""
        with patch('shutil.which', return_value=None):
            assert check_ffmpeg_installed() is False


class TestPlannedFileHandling:
    """Test planned file save/load operations."""

    def setup_method(self):
        """Create a temporary directory for test files."""
        self.test_dir = tempfile.mkdtemp()
        self.test_folder_id = "test_folder_123"

    def teardown_method(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_save_and_load_planned_files(self):
        """Test saving and loading planned files."""
        test_file = os.path.join(self.test_dir, 'test_planned.txt')

        # Mock the get_planned_files_log function
        with patch('run_fotointegrator.get_planned_files_log', return_value=test_file):
            # Save some test files
            save_planned_file(self.test_folder_id, "file1", "https://drive.google.com/file1", "test1.jpg", "image/jpeg")
            save_planned_file(self.test_folder_id, "file2", "https://drive.google.com/file2", "test2.mp4", "video/mp4")
            save_planned_file(self.test_folder_id, "file3", "https://drive.google.com/file3", "test3.mts", "video/mp2t")

            # Load and verify
            planned = load_planned_files(self.test_folder_id)

            assert planned is not None
            assert len(planned) == 3

            # Check first file
            assert planned[0] == ("file1", "https://drive.google.com/file1", "test1.jpg", "image/jpeg")

            # Check second file
            assert planned[1] == ("file2", "https://drive.google.com/file2", "test2.mp4", "video/mp4")

            # Check third file
            assert planned[2] == ("file3", "https://drive.google.com/file3", "test3.mts", "video/mp2t")

    def test_load_planned_files_not_exists(self):
        """Test loading when plan file doesn't exist."""
        non_existent = os.path.join(self.test_dir, 'nonexistent.txt')

        with patch('run_fotointegrator.get_planned_files_log', return_value=non_existent):
            result = load_planned_files(self.test_folder_id)
            assert result is None

    def test_load_planned_files_empty(self):
        """Test loading an empty plan file."""
        empty_file = os.path.join(self.test_dir, 'empty.txt')
        open(empty_file, 'w').close()

        with patch('run_fotointegrator.get_planned_files_log', return_value=empty_file):
            result = load_planned_files(self.test_folder_id)
            assert result == []

    def test_load_planned_files_malformed_line(self):
        """Test loading with malformed lines (should skip them)."""
        test_file = os.path.join(self.test_dir, 'malformed.txt')

        with open(test_file, 'w') as f:
            f.write("incomplete|line\n")  # Only 2 fields
            f.write("file1|url1|name1|type1\n")  # Valid line
            f.write("another|bad\n")  # Only 2 fields
            f.write("file2|url2|name2|type2\n")  # Valid line

        with patch('run_fotointegrator.get_planned_files_log', return_value=test_file):
            result = load_planned_files(self.test_folder_id)

            # Should only load the 2 valid lines
            assert len(result) == 2
            assert result[0] == ("file1", "url1", "name1", "type1")
            assert result[1] == ("file2", "url2", "name2", "type2")

    def test_planned_file_with_special_characters(self):
        """Test files with special characters in names."""
        test_file = os.path.join(self.test_dir, 'special.txt')

        with patch('run_fotointegrator.get_planned_files_log', return_value=test_file):
            # Save file with special characters
            save_planned_file(
                self.test_folder_id,
                "file1",
                "https://drive.google.com/file/d/123?view=true",
                "test file (2024).jpg",
                "image/jpeg"
            )

            # Load and verify
            planned = load_planned_files(self.test_folder_id)
            assert len(planned) == 1
            assert planned[0][2] == "test file (2024).jpg"
            assert "?" in planned[0][1]  # URL with query param


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
