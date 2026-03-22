from dotenv import load_dotenv
import requests
import sys
import os
import json
import subprocess

# ─── ENV Variables ────────────────────────────────────────────
load_dotenv()  # Liest .env Datei ein
git_token = os.getenv("GIT_TOKEN")
if not git_token:
    raise SystemExit("Missing GIT_TOKEN in .env or in the environment.")

git_path = os.getenv("GIT_WORKFLOW_PATH_DEPLOYMENT")
if not git_path:
    raise SystemExit("Missing GIT_WORKFLOW_PATH_DEPLOYMENT in .env or in the environment.")

# ─── Docker Login Check ───────────────────────────────────────
def is_docker_logged_in(registry="ghcr.io"):
    config_path = os.path.expanduser("~/.docker/config.json")
    if not os.path.exists(config_path):
        return False
    with open(config_path) as f:
        config = json.load(f)
    auths = config.get("auths", {})
    return registry in auths

if not is_docker_logged_in("ghcr.io"):
    raise SystemExit("❌ Nicht bei Docker eingeloggt!\n👉 Bitte zuerst ausführen: docker login ghcr.io")

print("✅ Docker Login OK")

# ─── Getting changes ──────────────────────────────────────────
changes = sys.argv[1] if len(sys.argv) > 1 else "unknown changes made"
if not changes.strip():
    changes = "unknown changes made"

# ─── Frontend Build ───────────────────────────────────────────
print("\n📦 Building Frontend...")
subprocess.run("npm install", cwd="frontend", check=True, shell=True)
subprocess.run("npm run build", cwd="frontend", check=True, shell=True)
print("✅ Frontend Build OK")

# ─── Docker Build & Push ──────────────────────────────────────
print("\n🐳 Building Docker Image...")
subprocess.run("docker build -t dentinic/hikeplanner .", check=True, shell=True)

print("🐳 Pushing Docker Image...")
subprocess.run("docker push dentinic/hikeplanner", check=True, shell=True)
print("✅ Docker Push OK")

# ─── Git Commit & Push ────────────────────────────────────────
print("\n📤 Pushing to GitHub...")
subprocess.run("git add -A", check=True, shell=True)
subprocess.run(f"git commit -m \"{changes}\"", check=True, shell=True)
subprocess.run("git push", check=True, shell=True)
print(f"✅ Git Push OK – Message: '{changes}'")

# ─── Trigger GitHub Workflow ──────────────────────────────────
def trigger_github_workflow(uri, token, ref="main"):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": f"Bearer {token}"
    }
    body = {"ref": ref}
    try:
        response = requests.post(uri, headers=headers, json=body)
        response.raise_for_status()
        data = response.json() if response.content else {}
        run_id = data.get("id", "N/A")
        print(f"✅ Workflow triggered! Run-ID: {run_id}")
    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP Error: {e}")
        print(f"Response: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    trigger_github_workflow(
        uri=git_path,
        token=git_token,
        ref="main"
    )