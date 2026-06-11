from services.drupal_api_client import DrupalAPIClient
from services.issue_description_parser import IssueDescriptionParser

client = DrupalAPIClient()

metadata = client.get_issue_metadata(
    "https://www.drupal.org/project/drupal/issues/3517198"
)

sections = IssueDescriptionParser.extract_sections(
    metadata["problem_description_html"]
)

print(sections)