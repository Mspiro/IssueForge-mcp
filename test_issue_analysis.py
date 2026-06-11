from server import IssueForgeServer

server = IssueForgeServer()

result = server.analyze_issue(
    "https://www.drupal.org/project/drupal/issues/3517198"
)

print(result)

print(result["reproduction_steps"])