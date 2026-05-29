# Deployment

This walks through the one-time setup to put the tool on a real domain.
Hold off on these steps until the 50-VIN validation run looks good.

## 1. Fly.io (hosts the app)

Sign up at [fly.io](https://fly.io/) (free tier is enough to start) and
install the `flyctl` CLI on your Windows machine.

```powershell
# Install flyctl
iwr https://fly.io/install.ps1 -useb | iex

# Sign in
fly auth login

# Pick a unique app name (edit fly.toml's `app = "..."` line first)
fly launch --no-deploy --copy-config

# Create the persistent volume the SQLite DB lives on
fly volumes create lbt1_data --region ord --size 1

# Set secrets (not stored in fly.toml). Replace with your real values:
fly secrets set `
    LBT1_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" `
    LBT1_BASE_URL="https://yourdomain.com" `
    SMTP_HOST="smtp.resend.com" `
    SMTP_PORT="587" `
    SMTP_USER="resend" `
    SMTP_PASS="re_xxxxxxxxxx" `
    EMAIL_FROM="Locksmith Brain <noreply@yourdomain.com>"

# Deploy
fly deploy
```

After deploy, your app is at `https://<your-app-name>.fly.dev`. Verify it
loads, then hook up the real domain.

## 2. GoDaddy → Fly.io custom domain

1. **On Fly.io**, register the custom hostname and get the IPv4/IPv6:
   ```powershell
   fly certs create yourdomain.com
   fly certs create www.yourdomain.com
   fly ips list
   ```
   Note the `v4` and `v6` shared IPs (or allocate a dedicated v4 if you want).

2. **On GoDaddy DNS** (`Domain → DNS Management`):
   - Delete the default "parked" A record and any CNAME for `@` or `www`.
   - Add an **A record**:
     - Type: `A`
     - Name: `@`
     - Value: the Fly v4 IP from step 1
     - TTL: 600 seconds (10 min) — easy to revert if needed
   - Add an **AAAA record**:
     - Type: `AAAA`
     - Name: `@`
     - Value: the Fly v6 IP from step 1
   - Add a **CNAME**:
     - Type: `CNAME`
     - Name: `www`
     - Value: `yourdomain.com` (so `www.yourdomain.com` resolves to the same place)

3. **Wait for DNS propagation** (5–30 min). Test:
   ```powershell
   nslookup yourdomain.com
   ```

4. **Fly will auto-issue an SSL certificate** once it sees the A/AAAA pointing
   at it. Confirm with:
   ```powershell
   fly certs show yourdomain.com
   ```
   When `status` reads `Ready`, open `https://yourdomain.com` in a browser —
   you should see the sign-in page.

## 3. Email (optional but recommended)

The app sends three kinds of email if SMTP is configured: signup welcome,
password reset, newsletter confirmation. If SMTP is *not* configured, signup
still works — users just don't receive emails.

Easiest free-tier provider for transactional email:

- **Resend.com** — 100 emails/day free, 5-minute setup. Get an API key, set:
  ```
  SMTP_HOST=smtp.resend.com
  SMTP_PORT=587
  SMTP_USER=resend
  SMTP_PASS=<your-resend-api-key>
  EMAIL_FROM=Locksmith Brain <noreply@yourdomain.com>
  ```
  Then verify your sending domain in the Resend dashboard.

Alternatives: SendGrid (free tier 100/day), AWS SES (~$0.10/1000 emails),
Postmark, Mailgun.

## 4. Operational notes

- **VIN retention**: lookups are auto-purged after `LBT1_VIN_RETENTION_DAYS`
  days (default 60). The purge runs on app startup; for a long-running
  machine, add a daily cron later.
- **SQLite backups**: the DB lives in `/data/lbt1.db` on the Fly volume. Take
  periodic snapshots with `fly ssh sftp shell` → `get /data/lbt1.db`.
- **Logs**: `fly logs` streams stdout from the running machine. Errors from
  the scraper (Cloudflare blocks, no PNs found) show up there.
- **Rolling restarts**: `fly deploy` does a blue/green by default. If a
  request is in-flight (35–45 second VIN lookup), Fly waits for it to finish.
