# Put Rushline online as a web app

This folder is ready to run as a real website with its own `https://` address. You can open it on your iPhone from anywhere and add it to your Home Screen like an app.

There are two ways to do it. **Option A** is the easiest and takes about 15 minutes. **Option B** is free forever and keeps your videos, but takes more setup.

---

## Option A: Hugging Face Spaces (easiest, free)

Good for trying it out and showing people. **Limits of the free tier:**

- The site goes to sleep after about 2 days with no visitors. It wakes up the next time someone opens it, which takes a minute or two.
- **The free tier has no permanent storage.** When the site restarts, uploaded videos, exports, accounts and projects are wiped. Download your exports after you make them. Hugging Face sells a paid "persistent storage" add-on that fixes this; check its current price on their site.
- It has 2 CPU cores, so editing a 2–3 minute video takes several minutes.

### Steps

1. Go to **huggingface.co** and create a free account.
2. Click your profile picture, then **New Space**.
3. Fill it in:
   - **Space name:** `rushline` (or anything you like)
   - **SDK:** choose **Docker**, then **Blank**
   - **Hardware:** CPU basic (free)
   - **Visibility:** **Private** is safest while you test. Public means anyone with the link can open it.
4. Click **Create Space**.
5. On the new Space page, open the **Files** tab, then **Add file**, then **Upload files**.
6. Unzip `rushline-webapp.zip` on your computer. Open the `rushline` folder, select **everything inside it** (the `backend` and `frontend` folders, `deploy` and `docs`, `Dockerfile`, `README.md` and the other files) and drag it all into the upload box. Then click **Commit changes**.
   - The `Dockerfile` and `README.md` must be at the top level, not inside another folder.
7. Go to **Settings**, then **Variables and secrets**, and add these:
   - **Secret** `RUSHLINE_SECRET`: a long random password (mash the keyboard, 40+ characters). This keeps logins secure.
   - (optional) **Secret** `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`: makes the AI assistant and transcription smarter.
   - (optional) **Variable** `RUSHLINE_SIGNUPS` = `closed`: after you've made your own account, nobody else can sign up.
8. Open the **App** tab. It shows "Building" for 5–10 minutes the first time. When it says **Running**, the app appears.
9. **Sign up right away.** The first account created becomes the owner with the Agency plan.
10. On your iPhone:
    - If the Space is **public**, open `https://YOUR-NAME-rushline.hf.space` in Safari.
    - If it's **private**, you must be logged in to Hugging Face in Safari first.
    - Then tap **Share**, then **Add to Home Screen**.

---

## Option B: Oracle Cloud "Always Free" server (free, keeps everything)

A real server that stays on 24/7 and keeps your videos and accounts. Oracle's Always Free tier includes an ARM server with several cores, a lot of RAM and a large disk (check their site for the current limits). Oracle asks for a card to verify you, but Always Free resources aren't charged.

1. Create an account at **cloud.oracle.com** (choose "Always Free").
2. Create a **Compute instance**:
   - **Image:** Ubuntu 22.04 or 24.04
   - **Shape:** Ampere (VM.Standard.A1.Flex), 4 OCPU, 24 GB RAM
   - Download the SSH key it gives you.
3. In the instance's **Virtual Cloud Network**, open **Security List**, then **Add Ingress Rules**. Allow TCP ports **80** and **443** from `0.0.0.0/0`.
4. Get a free domain name at **duckdns.org** (for example `myrushline.duckdns.org`) and point it at your server's public IP.
5. Connect to the server (Windows: `ssh -i your-key.key ubuntu@YOUR_SERVER_IP` in PowerShell), then run:
   ```bash
   sudo apt update && sudo apt install -y docker.io docker-compose-v2 unzip
   sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT && sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
   ```
6. Copy the zip up from your PC (in PowerShell on your PC):
   ```
   scp -i your-key.key rushline-webapp.zip ubuntu@YOUR_SERVER_IP:~
   ```
7. Back on the server:
   ```bash
   unzip rushline-webapp.zip && cd rushline
   export RUSHLINE_SECRET="put-a-long-random-password-here"
   export RUSHLINE_DOMAIN="myrushline.duckdns.org"
   sudo -E docker compose -f deploy/docker-compose.yml up -d --build
   ```
8. Open `https://myrushline.duckdns.org`. The HTTPS certificate is set up automatically. Sign up first to become the owner.

---

## Running it on your own PC (like before)

Nothing changed. Follow the same steps as before:

- In the `backend` folder, activate the venv.
- Run `uvicorn app.main:app --host 0.0.0.0 --port 8000`.

## Settings you can change (environment variables)

| Name | What it does | Default |
|---|---|---|
| `RUSHLINE_SECRET` | Keeps logins secure. **Set this on any public site.** | random, saved in the data folder |
| `RUSHLINE_SIGNUPS` | `closed` = only the first (owner) account can be created | `open` |
| `RUSHLINE_DEFAULT_PLAN` | Plan given to new sign-ups | `creator` |
| `RUSHLINE_WHISPER_MODEL` | Speech-to-text size: `base` (faster) or `small` (more accurate) | `small` |
| `RUSHLINE_INPROC_WORKERS` | How many videos process at once | `2` in Docker |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | Optional, for smarter AI | — |
| `RUSHLINE_MAX_UPLOAD_MB` | Largest upload allowed | `4096` |
