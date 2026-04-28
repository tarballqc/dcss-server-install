# Forgot Password (SMTP + STARTTLS)

WebTiles' built-in "Forgot Password" link emails a one-time reset link to the player's registered address. To enable it, set the SMTP variables in `.env`.

## Required `.env`

```env
SMTP_HOST=email-smtp.us-east-1.amazonaws.com   # any STARTTLS provider
SMTP_PORT=587
SMTP_USER=AKIAxxxxxxxxxxxxxx
SMTP_PASSWORD=BL...redacted...
SMTP_FROM="DCSS WebTiles <admin@your-host>"
```

After saving, `./run.sh banner` and the form's "Forgot Password" link appears in the lobby login form.

## What gets patched

This installer makes three changes to the upstream WebTiles code at startup (`config/patch-sound.sh` + `config/patch-email-template.py`):

1. **STARTTLS before login** — upstream WebTiles calls `email_server.login()` directly. SES (and most modern SMTP) requires `email_server.starttls()` first. We `sed` it in.
2. **HTML email body** — upstream sends a plain ASCII reminder. We replace it with a server-branded HTML body (your `SERVER_ABBR`, host, optional Discord invite).
3. **Transparent rehash on login** — old DES-hashed passwords (from imports) get rehashed to SHA-512 the next time the user logs in successfully.

All three are idempotent — applied once, skipped on subsequent restarts.

## Required: `crypt_algorithm = "6"`

`config/webtiles.py` already sets `crypt_algorithm = "6"` (SHA-512). If you change it, make sure the runtime image has `libcrypt-dev` installed (`Dockerfile.game` does); otherwise `crypt.crypt()` returns `*0` and every login silently fails.

## Common SMTP providers

| Provider | `SMTP_HOST` | Notes |
|---|---|---|
| AWS SES | `email-smtp.<region>.amazonaws.com` | Verify the From domain or address. Sandbox until you ask out. |
| Mailgun | `smtp.mailgun.org` | Use the Mailgun-provided SMTP credentials. |
| SendGrid | `smtp.sendgrid.net` | User is literally `apikey`, password is the API key. |
| Postmark | `smtp.postmarkapp.com` | User and password are the API token. |
| Self-hosted (postfix) | your own | Make sure STARTTLS is enabled on 587. |

All on port 587, all STARTTLS.

## Testing

Trigger a reset from the lobby ("Forgot Password" link after a failed login attempt). Check the game-container logs:

```
docker compose logs -f game | grep -i smtp
```

If you see "SMTPException" or "starttls", the config or credentials are wrong. If you see "sent" with no error, check the recipient's spam folder.

## Disabling

Leave `SMTP_HOST` blank in `.env`. The "Forgot Password" link disappears.
