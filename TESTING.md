# Testing

This project includes unit tests for the core utility functions.

## Running Tests

### Quick Start

```bash
# Install test dependencies
pip install pytest

# Run all tests
pytest test_fotointegrator.py -v

# Run with coverage info
pytest test_fotointegrator.py -v --tb=short
```

### What's Tested

The test suite covers:

✅ **URL/ID Parsing** (`extract_folder_id`)
- Extracting folder IDs from Google Drive URLs
- Handling direct folder IDs
- URLs with query parameters

✅ **Video Format Detection** (`should_convert_video`)
- MTS, M2TS, MOV, AVI, MKV, WMV, MPG formats
- Case-insensitive matching
- MP4 files (should not convert)
- Image files (should not convert)

✅ **FFmpeg Detection** (`check_ffmpeg_installed`)
- System availability check

✅ **Planned File Handling**
- Saving and loading planned files
- Handling missing/empty files
- Malformed line handling
- Special characters in filenames

## Test Results

```
22 tests passing in ~0.3 seconds
```

## Test Coverage

**Focus**: Pure utility functions without external dependencies (no API calls, no I/O operations)

**Not Tested**:
- Google Drive/Photos API calls (require mocking)
- File upload/download operations
- Video conversion (requires ffmpeg)
- OAuth authentication flow

These would require extensive mocking and are better validated through integration testing.
