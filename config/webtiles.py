"""
WebTiles server configuration — injected at Docker build time.
"""
import os

# ── Network ────────────────────────────────────────────────────────────────
bind_nonsecure = True
bind_address   = ""
bind_port      = 8080
http_xheaders  = True          # trust X-Real-IP / X-Forwarded-For from nginx

# ── Paths ──────────────────────────────────────────────────────────────────
_here = os.path.dirname(os.path.abspath(__file__))

password_db      = "/data/passwd.db3"
settings_db      = "/data/user_settings.db3"
static_path      = os.path.join(_here, "static")
template_path    = os.path.join(_here, "templates")
games_config_dir = os.path.join(_here, "games.d")

# ── Logging ────────────────────────────────────────────────────────────────
logging_config = {
    "filename": "/data/logs/webtiles.log",
    "level":    "INFO",
}

# ── Lobby / meta ───────────────────────────────────────────────────────────
server_id          = os.environ.get("SERVER_ABBR", "MYSRV").lower()
server_announce    = True
game_data_no_cache = False

# ── Required by validate() ────────────────────────────────────────────
dgl_status_file    = "/data/dgl-status"
init_player_program = "/app/init-player.sh"

# ── Password Reset / Email ────────────────────────────────────────────────
lobby_url            = "https://my-server.example.com/"
recovery_token_lifetime = 12  # hours
smtp_host            = os.environ.get("SMTP_HOST", "email-smtp.us-east-1.amazonaws.com")
smtp_port            = int(os.environ.get("SMTP_PORT", "587"))
smtp_from_addr       = os.environ.get("SMTP_FROM", "DCSS WebTiles <admin@my-server.example.com>")
smtp_user            = os.environ.get("SMTP_USER", "")
smtp_password        = os.environ.get("SMTP_PASSWORD", "")
allow_password_reset = True

# ── Password hashing ─────────────────────────────────────────────────────
# Without these, upstream defaults to crypt_algorithm="broken" which uses the
# password itself as the salt — producing weak DES hashes or *0 (broken).
crypt_algorithm     = "6"       # SHA-512 ($6$ prefix)
crypt_salt_length   = 16
max_passwd_length   = 20

# ── Timeouts ──────────────────────────────────────────────────────────────
max_connections     = 500
connection_timeout  = 600      # seconds — lobby idle disconnect
max_idle_time       = 18000    # seconds — max idle while playing (5 hours, upstream default)
