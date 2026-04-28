#!/usr/bin/env python3
"""Patch the password reset email template in all WebTiles versions.

Reads SERVER_ABBR / SERVER_URL / DISCORD_INVITE from env and bakes them
into the injected HTML so the email is server-branded on first start.
Idempotent: if the new template (or any previously rendered version) is
already in place, nothing changes.
"""
import os
import re

PATHS = [
    "/app/source/webserver/webtiles/userdb.py",
    "/app/source-trunk/webserver/webtiles/userdb.py",
    "/app/source-0.33/webserver/webtiles/userdb.py",
    "/app/source-0.32/webserver/webtiles/userdb.py",
    "/app/source-0.31/webserver/webtiles/userdb.py",
    "/app/source-0.30/webserver/webtiles/userdb.py",
]

SERVER_ABBR    = os.environ.get("SERVER_ABBR", "MYSRV")
SERVER_URL     = os.environ.get("SERVER_URL",  "https://my-server.example.com")
SERVER_HOST    = SERVER_URL.replace("https://", "").replace("http://", "")
DISCORD_INVITE = os.environ.get("DISCORD_INVITE", "").strip()

# Optional Discord help line — only render if an invite was provided.
discord_block = (
    f'<p style="font-size:12px;opacity:0.5">Need help? Join our '
    f'<a href="https://discord.com/invite/{DISCORD_INVITE}">Discord</a><br>'
    f'<a href="{SERVER_URL}">{SERVER_HOST}</a></p>'
) if DISCORD_INVITE else (
    f'<p style="font-size:12px;opacity:0.5">'
    f'<a href="{SERVER_URL}">{SERVER_HOST}</a></p>'
)

OLD_HTML = '''msg_body_html = """<html>
  <head></head>
  <body>
    <p>Someone (hopefully you) has requested to reset the password for your
       account at %s.<br /><br />
       If you initiated this request, please use this link to reset your
       password:<br /><br />
       &emsp;<a href='%s'>%s</a><br /><br />
       This link will expire in %d hour(s). If you did not ask to reset your
       password, feel free to ignore this email.
    </p>
  </body>
</html>"""'''

NEW_HTML = f'''msg_body_html = """<html>
<head></head>
<body style="margin:0;padding:0;font-family:monospace">
<div style="max-width:500px;margin:20px auto;padding:20px;font-size:15px;line-height:1.7">
<p><b>{SERVER_ABBR}</b> &mdash; {SERVER_HOST}</p>
<p>Someone (hopefully you) has requested to reset the password for your account.</p>
<p>Click the link below to reset your password:</p>
<p style="margin:20px 0"><a href="%s" style="word-break:break-all">Reset Password</a></p>
<p style="font-size:13px;opacity:0.6">This link will expire in %d hour(s). If you did not request this, ignore this email.</p>
<hr style="border:none;border-top:1px solid #ccc;margin:25px 0">
{discord_block}
</div>
</body>
</html>"""'''

OLD_FORMAT = "% (lobby_url, url_text, url_text, config.get('recovery_token_lifetime'))"
NEW_FORMAT = "% (url_text, config.get('recovery_token_lifetime'))"

# Pattern to detect any prior render of NEW_HTML so we can re-skin if env changed.
PRIOR_PATTERN = re.compile(
    r'msg_body_html = """<html>\s*<head></head>\s*<body[^"]*?<p><b>[^<]+</b>',
    re.DOTALL,
)

for path in PATHS:
    if not os.path.exists(path):
        continue
    with open(path) as f:
        content = f.read()

    if OLD_HTML in content:
        content = content.replace(OLD_HTML, NEW_HTML)
        content = content.replace(OLD_FORMAT, NEW_FORMAT)
        action = "patched (first time)"
    elif PRIOR_PATTERN.search(content):
        # Already patched once; re-skin in case SERVER_ABBR / URL changed.
        # Find the existing msg_body_html block and replace the whole assignment.
        new_content, n = re.subn(
            r'msg_body_html = """<html>.*?</html>"""',
            NEW_HTML.split('=', 1)[1].strip(),
            content,
            count=1,
            flags=re.DOTALL,
        )
        if n == 0 or new_content == content:
            continue
        content = new_content
        action = "re-skinned"
    else:
        continue

    with open(path, 'w') as f:
        f.write(content)
    print(f"[email-patch] {action} in {path}")
