from server import IssueForgeServer


server = IssueForgeServer()


def analyze_issue_tool(issue_url: str) -> dict:
    """
    MCP-exposed tool for analyzing Drupal issues.
    """

    return server.analyze_issue(issue_url)