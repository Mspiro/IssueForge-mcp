from fastapi import FastAPI
from pydantic import BaseModel

from server import IssueForgeServer


app = FastAPI()

engine = IssueForgeServer()


class IssueRequest(BaseModel):
    issue_url: str


@app.get("/tools")
def list_tools():
    """
    MCP-style tool discovery endpoint
    """
    return [
        {
            "name": "analyze_drupal_issue",
            "description": "Analyze a Drupal.org issue and return structured reasoning context",
            "input_schema": {
                "type": "object",
                "properties": {
                    "issue_url": {
                        "type": "string"
                    }
                },
                "required": ["issue_url"]
            }
        }
    ]


@app.post("/tools/analyze_drupal_issue")
def analyze_issue(request: IssueRequest):
    """
    MCP-style tool execution endpoint
    """
    return engine.analyze_issue(request.issue_url)