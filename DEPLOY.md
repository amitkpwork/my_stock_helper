# Hosting my_stock_helper on Streamlit Community Cloud (free) and using it on Android

## 1. Put the code on GitHub
1. Create a free account at github.com and make a **new repository** named `my_stock_helper` (choose **Private**).
2. Click **Add file > Upload files** and upload everything in this folder:
   `app.py, signals.py, categories.py, briefing.py, storage.py, requirements.txt, .gitignore`
   (do NOT upload `watchlist.json`, `settings.json` or any real secrets).
3. Click **Commit changes**.

## 2. Create a private Gist to remember your watchlist
Free hosts forget local files on restart, so the watchlist is kept in a Gist.
1. Go to gist.github.com. Filename: `watchlist.json`. Content: `["RELIANCE","TCS","HDFCBANK","INFY","ITC"]`
2. Click **Create secret gist**. Copy the ID from the URL (the long string after your username).

## 3. Create a token that can edit that Gist
GitHub > Settings > Developer settings > Personal access tokens > **Tokens (classic)** > Generate new token.
Tick **only** the `gist` scope. Copy the token (you only see it once).

## 4. Deploy
1. Go to share.streamlit.io and sign in with GitHub.
2. Click **Create app** > "Yup, I have an app".
3. Pick your repo, branch `main`, main file `app.py`.
4. Open **Advanced settings** and paste into **Secrets** (use your own values):

```
APP_PASSWORD = "choose-a-password"
GITHUB_TOKEN = "ghp_xxxxxxxxxxxx"
GIST_ID = "your_gist_id"
ANTHROPIC_API_KEY = "sk-ant-xxxx"   # optional, only for the AI-written brief
```
5. Click **Deploy**. The first build takes a few minutes.

## 5. Install on your Android phone
Open your app link (`https://<name>.streamlit.app`) in Chrome > menu (three dots) > **Add to Home screen** or **Install app**.

## Good to know
- Free apps go to sleep if nobody opens them for a while. Tap the wake-up button and wait a minute.
- You re-enter the password each time you open the app in a fresh tab.
- Yahoo Finance sometimes blocks or rate-limits cloud servers. If prices fail to load, reload after a minute.
- Streamlit allows only one private app on a free workspace.
- If you ever leak the token, delete it in GitHub settings and create a new one.
- Updating the app: upload the changed files to the repo; the app redeploys itself.
- Educational tool, not investment advice.
