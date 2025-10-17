from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from github import Github
import os, json, base64, requests, hashlib, time

app = FastAPI(title="LLM Code Deployment API")

STUDENT_SECRET = os.getenv("tds-powpowhello-worldpowpow-2025")
GITHUB_TOKEN = os.getenv("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")
GITHUB_USERNAME = os.getenv("25f1002006-png")
AIPROXY_TOKEN = os.getenv("https://aipipe.org/openai/v1/chat/completions")

if not all([STUDENT_SECRET, GITHUB_TOKEN, GITHUB_USERNAME, AIPROXY_TOKEN]):
    raise RuntimeError("Missing required environment variables")

gh = Github(GITHUB_TOKEN)
user = gh.get_user()

def call_llm(prompt: str) -> str:
    url = "https://aiproxy.sanand.workers.dev/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {AIPROXY_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "Generate minimal HTML/JS code for deployment"},
            {"role": "user", "content": prompt}
        ]
    }
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

@app.post("/api-endpoint")
async def handle_request(req: Request):
    data = await req.json()

    if data.get("secret") != STUDENT_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")

    email = data["email"]
    task = data["task"]
    round_ = data.get("round", 1)
    nonce = data["nonce"]
    evaluation_url = data["evaluation_url"]
    brief = data.get("brief", "")
    attachments = data.get("attachments", [])

    repo_name = f"{task}-{round_}".replace("/", "-")[:80]

    try:
        repo = user.create_repo(repo_name, private=False, auto_init=False)
    except Exception:
        repo = user.get_repo(f"{GITHUB_USERNAME}/{repo_name}")

    llm_code = call_llm(f"{brief}\nGenerate deployable HTML/JS code snippet.")
    readme = f"# {task}\n\nBrief:\n{brief}\n\nAuto-generated via LLM."
    license_text = "MIT License\n\nCopyright (c) 2025 Student"

    repo.create_file("README.md", "Add README", readme)
    repo.create_file("LICENSE", "Add MIT License", license_text)
    repo.create_file("index.html", "Add index", llm_code)

    for a in attachments:
        fname = a["name"]
        data_url = a["url"]
        if "," in data_url:
            _, b64data = data_url.split(",", 1)
            binary = base64.b64decode(b64data)
            repo.create_file(fname, f"Add {fname}", binary)

    commit_sha = repo.get_commits()[0].sha
    pages_url = f"https://{GITHUB_USERNAME}.github.io/{repo_name}/"
    repo_url = repo.html_url

    payload = {
        "email": email,
        "task": task,
        "round": round_,
        "nonce": nonce,
        "repo_url": repo_url,
        "commit_sha": commit_sha,
        "pages_url": pages_url
    }

    resp = requests.post(
        evaluation_url,
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=30
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=500, detail=f"Eval notify failed: {resp.text}")

    return JSONResponse({"status": "ok", "repo": repo_url, "pages_url": pages_url})