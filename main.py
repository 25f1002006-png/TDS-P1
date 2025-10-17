from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from github import Github, UnknownObjectException, GithubException
import os, json, base64, requests, hashlib, time
from dotenv import load_dotenv

load_dotenv() 

app = FastAPI(title="LLM Code Deployment API")

STUDENT_SECRET = os.getenv("TDS_SECRET")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
AIPROXY_TOKEN = os.getenv("AIPROXY_TOKEN")

if not all([STUDENT_SECRET, GITHUB_TOKEN, GITHUB_USERNAME, AIPROXY_TOKEN]):
    raise RuntimeError("Missing required environment variables. Make sure a .env file exists and is populated.")

gh = Github(GITHUB_TOKEN)
user = gh.get_user()

def upsert_file_in_repo(repo, file_path, content, commit_message):
    try:
        file_contents = repo.get_contents(file_path)
        
        existing_content = file_contents.decoded_content
        is_identical = False
        if isinstance(content, str):
            try:
                is_identical = (existing_content.decode('utf-8') == content)
            except UnicodeDecodeError:
                is_identical = False
        elif isinstance(content, bytes):
            is_identical = (existing_content == content)

        if is_identical:
            print(f"Skipping {file_path}, content is unchanged.")
            return

        print(f"Updating file: {file_path}")
        repo.update_file(
            path=file_path,
            message=commit_message,
            content=content,
            sha=file_contents.sha
        )
    except GithubException as e:
        if e.status == 404:
            print(f"Creating file (404 received): {file_path}")
            repo.create_file(
                path=file_path,
                message=commit_message,
                content=content
            )
        else:
            print(f"Failed to upsert {file_path}: {e}")
            raise
    except Exception as e:
        print(f"Failed to upsert {file_path}: {e}")
        raise

def call_llm(prompt: str) -> str:
    url = "https://aipipe.org/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {AIPROXY_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "You are a senior web developer. Generate minimal, complete, and deployable HTML/JS/CSS code based on the user's request. Provide only the code block."},
            {"role": "user", "content": prompt}
        ]
    }
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    response_text = r.json()["choices"][0]["message"]["content"]
    if "```" in response_text:
        parts = response_text.split("```", 2)
        if len(parts) > 1:
            code = parts[1]
            if code.startswith("html"):
                code = code[4:]
            return code.strip()
    return response_text

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

    repo_name = f"{task}".replace("/", "-")[:80]

    try:
        repo = user.create_repo(repo_name, private=False, auto_init=False)
        print(f"Created new repo: {repo_name}")
    except GithubException as e:
        if e.status == 422 and e.data and "name already exists" in str(e.data.get("errors", "")):
            print(f"Repo '{repo_name}' already exists. Fetching it.")
            repo = user.get_repo(repo_name) 
        else:
            raise e
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        raise
    license_text = "MIT License\n\nCopyright (c) 2025 Student"
    upsert_file_in_repo(repo, "LICENSE", license_text, "Add/Update MIT License")

    readme_path = "README.md"
    readme_commit_msg = f"Update README for round {round_}"
    try:
        readme_contents = repo.get_contents(readme_path)
        old_readme = readme_contents.decoded_content.decode('utf-8')
    except GithubException as e:
        if e.status == 404:
             old_readme = f"# {task}\n\nAuto-generated via LLM."
        else:
             raise
    
    new_readme = f"{old_readme}\n\n## Round {round_}\n\nBrief:\n{brief}"
    upsert_file_in_repo(repo, readme_path, new_readme, readme_commit_msg)

    for a in attachments:
        fname = a["name"]
        data_url = a["url"]
        if "," in data_url:
            _, b64data = data_url.split(",", 1)
            binary = base64.b64decode(b64data)
            upsert_file_in_repo(repo, fname, binary, f"Add/Update {fname}")

    index_path = "index.html"
    if round_ == 1:
        prompt = f"{brief}\n\nGenerate a complete, single-file deployable HTML/JS code snippet to accomplish this."
        llm_code = call_llm(prompt)
        upsert_file_in_repo(repo, index_path, llm_code, "Add index.html")
    else:
        try:
            old_code_contents = repo.get_contents(index_path)
            old_code = old_code_contents.decoded_content.decode('utf-8')
        except GithubException as e:
            if e.status == 404:
                old_code = ""
            else:
                raise
        
        prompt = f"Here is the existing code for 'index.html':\n\n```html\n{old_code}\n```\n\nNow, please modify this code to implement the following new requirement: {brief}\n\nProvide only the full, complete, updated HTML/JS code snippet."
        new_llm_code = call_llm(prompt)
        upsert_file_in_repo(repo, index_path, new_llm_code, f"Update index.html for round {round_}")

    if not repo.has_pages:
        try:
            headers = {
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json"
            }
            data = {"source": {"branch": repo.default_branch, "path": "/"}}
            api_url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{repo.name}/pages"
            r_pages = requests.post(api_url, headers=headers, json=data, timeout=30)
            
            if r_pages.status_code == 409:
                print("GitHub Pages enabling is in progress.")
            else:
                r_pages.raise_for_status()
                print("Enabled GitHub Pages successfully.")
                time.sleep(5)
        except Exception as e:
            print(f"Could not enable GitHub Pages via API: {e}")
            try:
                repo.edit(has_pages=True)
                print("Enabled pages via (deprecated) repo.edit()")
            except Exception as e_old:
                print(f"Fallback repo.edit() also failed: {e_old}")

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

    max_retries = 5
    delay = 1
    for i in range(max_retries):
        try:
            resp = requests.post(
                evaluation_url,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=30
            )
            if resp.status_code == 200:
                print("Successfully notified evaluation URL.")
                return JSONResponse({"status": "ok", "repo": repo_url, "pages_url": pages_url})
            
            print(f"Eval notify failed with {resp.status_code}: {resp.text}. Retrying in {delay}s...")
        
        except requests.exceptions.RequestException as e:
            print(f"Eval notify failed with exception: {e}. Retrying in {delay}s...")

        time.sleep(delay)
        delay *= 2
    
    raise HTTPException(status_code=500, detail="Evaluation notification failed after multiple retries.")

