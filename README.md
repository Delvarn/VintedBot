# Vinted Watcher

Checks your saved Vinted searches on a schedule and pings you on Telegram
the moment a new matching item is listed.

## How it works

- `searches.json` — your list of saved searches (keyword, max price, etc.)
- `watcher.py` — fetches results from Vinted, compares against `seen_items.json`,
  and sends a Telegram message for anything new
- `.github/workflows/watch.yml` — runs `watcher.py` automatically every
  10 minutes using GitHub Actions (free on a public repo)

## One-time setup

### 1. Create the GitHub repo
1. Create a **new repository** on GitHub (public, so Actions minutes are free/unlimited)
2. Upload all these files to it, keeping the folder structure
   (the `.github/workflows/watch.yml` file must stay at that exact path)

### 2. Add your Telegram credentials as secrets
Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**,
and add two secrets:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | your bot token from BotFather |
| `TELEGRAM_CHAT_ID` | your chat id (the number you got from `getUpdates`) |

These are encrypted by GitHub and never appear in the code or logs.

### 3. Turn on Actions
Go to the **Actions** tab of your repo → you should see "Vinted Watcher" listed →
click **Enable workflow** if prompted.

### 4. Test it manually
In the **Actions** tab, click **Vinted Watcher** → **Run workflow** → **Run workflow**
(the green button). After ~30–60 seconds, check the run's logs, and check Telegram —
you should get a message for every current PS1 listing under £30 the first time it runs
(since nothing has been marked "seen" yet). After that first run, you'll only be notified
about genuinely new listings.

## Adding more searches

Edit `searches.json` and add another entry, e.g.:

```json
[
  {
    "name": "PS1",
    "keyword": "PS1",
    "max_price": 30
  },
  {
    "name": "Nike Air Max 90 - size 9",
    "keyword": "Nike Air Max 90",
    "max_price": 40,
    "size_ids": [207]
  }
]
```

Commit the change and the next scheduled run will pick it up automatically.
(Size/brand IDs are Vinted's internal numeric IDs — ask if you want help finding
the right ones for a specific size or brand.)

## Changing how often it checks

Edit the `cron` line in `.github/workflows/watch.yml`. Some examples:

- Every 5 minutes: `*/5 * * * *`
- Every 15 minutes: `*/15 * * * *`
- Every hour: `0 * * * *`

Cron times are in UTC and GitHub may add a few minutes of delay during busy periods.

## Important notes

- This uses Vinted's internal (unofficial) API — the same one their own
  website calls. Vinted could change it at any time without notice, which
  would cause the script to start failing. If that happens, the fix is
  usually just updating a URL or parameter in `watcher.py`.
- Keep the repo's polling interval reasonable (5+ minutes) to avoid being
  rate-limited or blocked by Vinted.
- The Telegram bot token secret should never be pasted into `searches.json`,
  commit messages, or anywhere public — only into the GitHub repo secrets.
- No purchasing is automated — you'll always buy manually via the link in
  the Telegram message.
