from services.patch_applier import PatchApplier
import os

base_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(base_dir, "environments", "env_3517198")
patch_id = "7032291"

print("--- Step 1: Performing Dry-Run Compatibility Check ---")
check_res = PatchApplier.check_patch(env_path, patch_id)
print("Check clean?", check_res["clean"])
print("Check message:\n", check_res["message"])

if check_res["clean"]:
    print("\n--- Step 2: Applying Patch and Rebuilding Cache ---")
    apply_res = PatchApplier.apply_patch(env_path, patch_id)
    print("Apply success?", apply_res["success"])
    print("Apply message:\n", apply_res["message"])
else:
    print("\nCheck failed, skipping application.")
