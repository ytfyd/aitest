#!/usr/bin/env python3
"""Debug - check execute_tests return value"""

import subprocess
import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

os.environ['GIT_REPO_PATH'] = r'C:\Users\DELL\Desktop\aitest\campus-master'

from run_tests import TestRunner

runner = TestRunner.__new__(TestRunner)

result = runner.execute_tests(r"C:\Users\DELL\Desktop\aitest\pytestjava\tests\generated\test_generated_20260325_195818.py")

print("=== FAILED DETAILS (from execute_tests) ===")
for i, fail in enumerate(result.get('failed_details', [])):
    print(f"{i}: {fail['name']}")
    print(f"   Error: {fail['error'][:60]}...")
