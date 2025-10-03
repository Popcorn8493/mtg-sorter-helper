#!/usr/bin/env python3
"""
Test runner for MTG Toolkit cache system tests.
This script runs comprehensive tests to verify cache system functionality.
"""

import os
import sys
import subprocess
import platform
from pathlib import Path


def run_tests():
    """Run all cache system tests."""
    print("=" * 60)
    print("MTG Toolkit Cache System Test Suite")
    print("=" * 60)
    print(f"Platform: {platform.system()} {platform.release()}")
    print(f"Python: {sys.version}")
    print(f"Working Directory: {os.getcwd()}")
    print("=" * 60)

    # Test files to run
    test_files = ["test_cache_system.py", "test_cross_platform_cache.py"]

    # Check if test files exist
    missing_files = []
    for test_file in test_files:
        if not Path(test_file).exists():
            missing_files.append(test_file)

    if missing_files:
        print(f"Error: Missing test files: {missing_files}")
        return False

    # Run pytest with verbose output
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-v",
        "--tb=short",
        "--disable-warnings",
        "--color=yes",
    ] + test_files

    print(f"Running command: {' '.join(cmd)}")
    print("-" * 60)

    try:
        result = subprocess.run(cmd, check=True, capture_output=False)
        print("-" * 60)
        print("✅ All tests passed successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print("-" * 60)
        print(f"❌ Tests failed with exit code: {e.returncode}")
        return False
    except Exception as e:
        print("-" * 60)
        print(f"❌ Error running tests: {e}")
        return False


def run_specific_tests():
    """Run specific cache-related tests."""
    print("\n" + "=" * 60)
    print("Running Specific Cache Tests")
    print("=" * 60)

    # Test cache directory creation
    print("\n1. Testing cache directory creation...")
    try:
        from core.constants import _get_global_cache_dir, _setup_global_cache

        cache_dir = _get_global_cache_dir()
        print(f"   Cache directory: {cache_dir}")
        print(f"   Directory exists: {cache_dir.exists()}")

        if not cache_dir.exists():
            print("   Creating cache directories...")
            _setup_global_cache()
            print(f"   Directory created: {cache_dir.exists()}")

        print("   [OK] Cache directory creation test passed")
    except Exception as e:
        print(f"   [FAIL] Cache directory creation test failed: {e}")
        return False

    # Test cache accessibility
    print("\n2. Testing cache accessibility...")
    try:
        from core.constants import verify_cache_accessibility

        result = verify_cache_accessibility()
        print(f"   Cache accessibility: {result}")
        print("   [OK] Cache accessibility test passed")
    except Exception as e:
        print(f"   [FAIL] Cache accessibility test failed: {e}")
        return False

    # Test ScryfallAPI initialization
    print("\n3. Testing ScryfallAPI initialization...")
    try:
        from api.scryfall_api import ScryfallAPI

        api = ScryfallAPI()
        print("   ScryfallAPI initialized successfully")
        print("   [OK] ScryfallAPI initialization test passed")
    except Exception as e:
        print(f"   [FAIL] ScryfallAPI initialization test failed: {e}")
        return False

    return True


def main():
    """Main test runner."""
    print("MTG Toolkit Cache System Test Runner")
    print("This script will test the cache system functionality.")

    # Check if we're in the right directory
    if not Path("core/constants.py").exists():
        print("Error: Please run this script from the MTG Toolkit root directory")
        sys.exit(1)

    # Run specific tests first
    if not run_specific_tests():
        print("\n[FAIL] Specific tests failed. Skipping full test suite.")
        sys.exit(1)

    # Run full test suite
    print("\n" + "=" * 60)
    print("Running Full Test Suite")
    print("=" * 60)

    if run_tests():
        print("\n[SUCCESS] All cache system tests completed successfully!")
        print("\nThe cache system is working correctly on this platform.")
        return 0
    else:
        print("\n[ERROR] Some tests failed. Please check the output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
