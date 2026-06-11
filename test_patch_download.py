from services.drupal_patch_client import DrupalPatchClient

client = DrupalPatchClient()

patch_url = client.get_patch_download_url("7032291")

print("Patch URL:", patch_url)

client.download_patch("7032291", "test_patch.diff")

print("Patch downloaded successfully")