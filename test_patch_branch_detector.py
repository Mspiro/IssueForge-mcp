from services.patch_branch_detector import PatchBranchDetector

# Test 1: Extract version from filename
print("--- Test 1: Filename Parsing ---")
filenames = [
    ("multiselect-group-filters-broken-3517198-2-10.3.x.patch", "10.3.x"),
    ("some-patch-11.x-dev.patch", "11.x"),
    ("fix-issue-9.5.x-4.patch", "9.5.x"),
    ("drupal-core-7.x-bug.patch", "7.x"),
    ("no-version-here.patch", None),
]

for filename, expected in filenames:
    detected = PatchBranchDetector.detect_branch_from_filename(filename)
    print(f"File: {filename:55} | Detected: {str(detected):10} | Match: {detected == expected}")

# Test 2: Detect Drupal major version from modified file paths
print("\n--- Test 2: Major Version Path Detection ---")
paths_d8 = ["core/modules/node/src/NodeStorage.php", "core/lib/Drupal.php"]
paths_d7 = ["modules/node/node.module", "includes/common.inc"]

print("D8 Paths:", PatchBranchDetector.detect_major_from_paths(paths_d8), "(Expected: 8+)")
print("D7 Paths:", PatchBranchDetector.detect_major_from_paths(paths_d7), "(Expected: 7)")

# Test 3: Compatibility Checks
print("\n--- Test 3: Compatibility Verification ---")
checks = [
    # Mismatch D7 vs D8
    ("patch-7.x.patch", ["core/modules/node/node.module"], "7.x", False),
    # Compatible
    ("patch-10.3.x.patch", ["core/modules/node/src/NodeStorage.php"], "10.3.x", True),
    # Mismatch minor branch
    ("patch-10.2.x.patch", ["core/modules/node/src/NodeStorage.php"], "11.x", False),
    # Generic compatible (no version in filename)
    ("patch.patch", ["core/modules/node/src/NodeStorage.php"], "11.x", True),
]

for filename, paths, checkout_ref, expected_compat in checks:
    res = PatchBranchDetector.check_compatibility(filename, paths, checkout_ref)
    is_compat = res["is_compatible"]
    warning = res["warning"]
    print(f"Ref: {checkout_ref:6} | File: {filename:20} | Compat: {str(is_compat):5} | Expected: {str(expected_compat):5} | Warning: {warning}")
