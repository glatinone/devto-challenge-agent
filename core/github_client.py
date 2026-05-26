"""
GitHub API client for file operations and issue management.
All agents use this — never import PyGithub or requests-to-github directly.
"""

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Optional


class GitHubClient:
    def __init__(self) -> None:
        self.token = os.environ["GITHUB_TOKEN"]
        self.repo = os.environ.get(
            "GITHUB_REPOSITORY", "glatinone/devto-challenge-agent"
        )
        self.branch = os.environ.get("GITHUB_BRANCH", "main")
        self._base = f"https://api.github.com/repos/{self.repo}"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _request(self, method: str, endpoint: str, data: Optional[dict] = None) -> dict:
        url = self._base + endpoint
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(
            url, data=body, headers=self._headers(), method=method
        )
        try:
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"GitHub {method} {endpoint}: {exc.code} {exc.read().decode()}"
            ) from exc

    def _get_sha(self, path: str) -> Optional[str]:
        try:
            r = self._request("GET", f"/contents/{path}?ref={self.branch}")
            return r.get("sha")
        except RuntimeError:
            return None

    def commit_file(self, path: str, content: str, message: str) -> None:
        sha = self._get_sha(path)
        payload: dict = {
            "message": message,
            "content": base64.b64encode(content.encode()).decode(),
            "branch": self.branch,
        }
        if sha:
            payload["sha"] = sha
        self._request("PUT", f"/contents/{path}", payload)

    def read_file(self, path: str) -> Optional[str]:
        try:
            r = self._request("GET", f"/contents/{path}?ref={self.branch}")
            return base64.b64decode(r["content"]).decode()
        except RuntimeError:
            return None

    def create_issue(
        self, title: str, body: str, labels: Optional[list[str]] = None
    ) -> str:
        if labels:
            self._ensure_labels(labels)
        payload: dict = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        r = self._request("POST", "/issues", payload)
        return r["html_url"]

    def list_open_issues(self, label: Optional[str] = None) -> list[dict]:
        endpoint = "/issues?state=open"
        if label:
            endpoint += f"&labels={label}"
        return self._request("GET", endpoint)  # type: ignore[return-value]

    def _ensure_labels(self, labels: list[str]) -> None:
        for label in labels:
            try:
                self._request("POST", "/labels", {"name": label, "color": "0075ca"})
            except RuntimeError:
                pass  # label already exists
