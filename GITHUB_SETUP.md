# Put Rushline on GitHub

This folder is a ready-to-go GitHub repository:

- `.gitignore` keeps your videos, database and login secret **out** of GitHub.
- `.gitattributes` keeps Windows and Linux line endings consistent.
- **Automatic tests** (`.github/workflows/ci.yml`) run on every upload. They check a full upload → AI edit → export on GitHub's own computers, build the web app and build the Docker image. You'll see a green ✓ or red ✗ next to each change.
- **Optional auto-deploy** (`.github/workflows/deploy-huggingface.yml`) updates your Hugging Face Space every time you push.

> GitHub stores and tests the code. It can't *run* the app, because GitHub Pages only hosts plain static websites and Rushline needs a Python server with ffmpeg. For hosting, connect the repo to Hugging Face Spaces (below), Render, Railway or a server. They all read the `Dockerfile` in this repo.

## Upload it (easiest: GitHub Desktop)

1. Make a free account at **github.com**.
2. Install **GitHub Desktop** from desktop.github.com and sign in.
3. In GitHub Desktop: **File → Add local repository…** and choose your `rushline` folder (the one containing `Dockerfile`).
   - It will say "this directory does not appear to be a Git repository". Click **create a repository** there, then **Create repository**.
4. Click **Publish repository**. **Keep "Keep this code private" ticked**, since this is your product.
5. Done. Open the repo on github.com and click the **Actions** tab to watch the tests run (about 5 minutes).

When I send you updated files later: put them in the folder, open GitHub Desktop, type a short summary (for example "cleaner menus"), click **Commit to main**, then **Push origin**.

> Tip: GitHub's website drag-and-drop upload only takes 100 files at a time, and Rushline has more than that. Use GitHub Desktop.

## Auto-deploy to Hugging Face (optional)

1. Create your Space first (see `WEB_APP_SETUP.md`, Option A, steps 1–4 and 7).
2. On huggingface.co, go to **Settings → Access Tokens → Create new token**, type **Write**, and copy it.
3. In your GitHub repo, go to **Settings → Secrets and variables → Actions**:
   - **Secrets** tab, **New repository secret**: name `HF_TOKEN`, paste the token.
   - **Variables** tab, **New repository variable**: name `HF_SPACE`, value `your-hf-username/rushline`.
4. From now on, every push updates the live site. You can also run it by hand from **Actions → Deploy to Hugging Face → Run workflow**.

## Other hosts that deploy straight from GitHub

Render, Railway, Koyeb and Fly.io can all "deploy from GitHub repo" using the `Dockerfile`. In each one:

- Set `RUSHLINE_SECRET`.
- Add a persistent disk mounted at `/data` if you want uploads to survive restarts.

Their free tiers change often and are usually too small for video processing, so check current limits.

## Never commit these

- `backend/data/`: your videos, the database and the login secret. It's already ignored.
- `.env` and API keys: put them in the host's "Secrets" page instead. `.env.example` shows the names.
