"""Refresh the running list against a file stored in GitHub."""
import base64
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import requests

from update_running_list import run


def refresh_github_store(store_path: Path, repository: str, branch: str, token: str,
                         progress=None) -> dict:
    url = f"https://api.github.com/repos/{repository}/contents/data/tournaments.json"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if progress:
        progress("Loading the current tournament list from GitHub...")
    response = requests.get(url, headers=headers, params={"ref": branch}, timeout=30)
    response.raise_for_status()
    remote = response.json()
    content = base64.b64decode(remote["content"])

    store_path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=store_path.parent) as directory:
        temporary_store = Path(directory) / "tournaments.json"
        temporary_store.write_bytes(content)
        result = run(temporary_store, progress=progress)
        updated_content = temporary_store.read_bytes()
        if progress:
            progress("Publishing the updated tournament list to GitHub...")
        response = requests.put(
            url,
            headers=headers,
            json={
                "message": "Update tournament list",
                "content": base64.b64encode(updated_content).decode("ascii"),
                "sha": remote["sha"],
                "branch": branch,
            },
            timeout=30,
        )
        response.raise_for_status()
        os.replace(temporary_store, store_path)
    return result
