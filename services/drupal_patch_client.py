import requests
from typing import Dict


DRUPAL_FILE_API = "https://www.drupal.org/api-d7/file"


class DrupalPatchClient:
    """
    Client for downloading patch files attached to Drupal issues.
    """

    @staticmethod
    def get_file_metadata(file_id: str) -> Dict:
        url = f"{DRUPAL_FILE_API}/{file_id}.json"

        response = requests.get(url)

        if response.status_code != 200:
            raise Exception(
                f"Failed to fetch metadata for file {file_id}"
            )

        return response.json()

    @staticmethod
    def extract_download_url(file_json: Dict) -> str:
        """
        Extract patch download URL from file metadata.
        """
        return file_json.get("url")

    def get_patch_download_url(self, file_id: str) -> str:
        metadata = self.get_file_metadata(file_id)

        return self.extract_download_url(metadata)

    def download_patch(self, file_id: str, save_path: str):
        metadata = self.get_file_metadata(file_id)

        download_url = metadata.get("url")

        if not download_url:
            raise Exception("No download URL found")

        response = requests.get(download_url)

        if response.status_code != 200:
            raise Exception("Failed to download patch")

        with open(save_path, "wb") as f:
            f.write(response.content)