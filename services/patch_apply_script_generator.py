class PatchApplyScriptGenerator:
    """
    Generate patch application script (only executed after confirmation).
    """

    PATCH_BASE_URL = "https://www.drupal.org/files/issues"

    @staticmethod
    def generate(patch_id):

        if not patch_id:
            return None

        return f"""#!/bin/bash

PATCH_ID={patch_id}

echo "Downloading patch $PATCH_ID..."

PATCH_URL=$(curl -s https://www.drupal.org/api-d7/file/$PATCH_ID.json \
| grep -o '"url":"[^"]*"' \
| cut -d '"' -f4)

curl -L $PATCH_URL -o issue.patch

echo "Applying patch..."

ddev ssh -s webserver <<EOF
patch -p1 < issue.patch
EOF

echo "Patch applied successfully."
"""