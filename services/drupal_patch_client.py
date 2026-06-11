import requests
import time


class DrupalPatchClient:
    """
    Downloads patch files safely with retry + caching.
    """

    BASE_URL = "https://www.drupal.org/api-d7/file"

    def __init__(self):
        self.session = requests.Session()
        self.cache = {}

    def safe_request(self, url):

        if url in self.cache:
            return self.cache[url]

        retries = 5
        backoff = 1

        for _ in range(retries):

            response = self.session.get(
                url,
                headers={
                    "User-Agent": "IssueForge-MCP-Client"
                }
            )

            if response.status_code == 200:
                self.cache[url] = response
                return response

            if response.status_code == 429:
                time.sleep(backoff)
                backoff *= 2
                continue

            raise Exception(
                f"Failed patch request: {url} ({response.status_code})"
            )

        raise Exception("Rate limited after multiple retries")

    def get_patch_metadata(self, patch_id):
        metadata_url = f"{self.BASE_URL}/{patch_id}.json"
        metadata_response = self.safe_request(metadata_url)
        return metadata_response.json()

    def get_patch_download_url(self, patch_id):
        metadata = self.get_patch_metadata(patch_id)
        return metadata.get("url")

    def download_patch(self, patch_id, output_path):

        metadata_json = self.get_patch_metadata(patch_id)

        patch_url = metadata_json.get("url")

        if not patch_url:
            raise Exception("Patch URL missing from metadata")

        patch_response = self.safe_request(patch_url)

        with open(output_path, "wb") as f:
            f.write(patch_response.content)

        return output_path, metadata_json.get("name")