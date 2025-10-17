# 🤖 LLM Auto-Deployment API

This is a FastAPI application that acts as an "agent-on-demand." It listens for webhook requests, uses an LLM to generate a complete web application, and automatically creates, updates, and deploys that application to GitHub Pages.

This project is designed to handle a multi-round "build and revise" workflow.

---

## Core Features

* **Secure API Endpoint**: The `/api-endpoint` is protected by a shared secret (`TDS_SECRET`).
* **LLM Code Generation**: Uses `gpt-4o-mini` via an API proxy to generate deployable HTML/JS/CSS from a text `brief`.
* **Automated Git Operations**: Automatically creates a new public GitHub repository or updates an existing one.
* **Intelligent File Handling**: Safely "upserts" (creates or updates) files like `index.html`, `README.md`, `LICENSE`, and any data attachments (e.g., CSV, JSON, images).
* **Revision-Aware**: For "Round 2" requests, it fetches the *existing* code, provides it to the LLM as context, and commits the revised version.
* **Automatic Deployment**: Activates GitHub Pages for the target repository on the first round.
* **Evaluation Callback**: Notifies a provided `evaluation_url` with the new repository URL, commit SHA, and live GitHub Pages URL, with built-in exponential backoff for retries.

---

## How It Works: Request Lifecycle

1.  **Receive Request**: An external service sends a `POST` request to `/api-endpoint` with a JSON payload containing the task `brief`, `secret`, `attachments`, `round`, and `evaluation_url`.
2.  **Authenticate**: The API validates the `secret` from the request. If it's invalid, it returns a `403 Forbidden`.
3.  **Get/Create Repo**: The API uses the `task` name to either `user.create_repo()` a new repository or `user.get_repo()` the existing one.
4.  **Generate Code**:
    * **If `round == 1`**: The API sends the `brief` to the LLM to generate code from scratch.
    * **If `round > 1`**: The API first fetches the current `index.html` from the repo, then sends *both* the old code and the new `brief` to the LLM, asking it to revise the code.
5.  **Commit Files**: The API uses the `upsert_file_in_repo` helper to commit the `LICENSE`, an updated `README.md`, any attachments, and the new/revised `index.html` to the repository.
6.  **Deploy**: If it's a new repo, the API sends a request to the GitHub API to enable GitHub Pages.
7.  **Notify**: The API sends a `POST` request to the `evaluation_url` with the `repo_url`, `pages_url`, and latest `commit_sha`.

---

## API Documentation

### `POST /api-endpoint`

This single endpoint handles all application creation and revision tasks.

#### Request Body (JSON)

```json
{
  "email": "student@example.com",
  "secret": "your-shared-secret",
  "task": "sum-of-sales-test",
  "round": 1,
  "nonce": "test-nonce-sales-123",
  "brief": "Publish a single-page site that fetches data.csv from attachments, sums its sales column, displays the total inside #total-sales, and loads Bootstrap 5.",
  "evaluation_url": "[https://webhook.site/](https://webhook.site/)...",
  "attachments": [
    {
      "name": "data.csv",
      "url": "data:text/csv;base64,cHJvZHVjdCxzYWxlcyxyZWdpb24KV2lkZ2V0LDEwMCxOb3J0aA=="
    }
  ]
}
