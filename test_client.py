from services.drupal_api_client import DrupalAPIClient

client = DrupalAPIClient()

issue = client.get_issue_metadata(
    "https://www.drupal.org/project/drupal/issues/3517198"
)

print(issue)