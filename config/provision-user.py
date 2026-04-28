#!/usr/bin/env python3
"""Provision a new DCSS WebTiles user from the hub.

Usage: python3 provision-user.py <username> <password>

Creates the user in passwd.db3 and runs init-player.sh to set up directories.
"""
import sys
import os
import sqlite3
import subprocess

import crypt

if len(sys.argv) < 2:
    print(f"Usage: {sys.argv[0]} <username> [password]", file=sys.stderr)
    print(f"  If password is omitted, it is read from stdin.", file=sys.stderr)
    sys.exit(1)

username = sys.argv[1]
password = sys.argv[2] if len(sys.argv) >= 3 else sys.stdin.readline().rstrip('\n')

PASSWD_DB = "/data/passwd.db3"

# Truncate to 20 chars (WebTiles max_passwd_length) then hash with SHA-512 crypt
password = password[:20]
hashed = crypt.crypt(password, crypt.mksalt(crypt.METHOD_SHA512))

conn = sqlite3.connect(PASSWD_DB)
cur = conn.cursor()

# Ensure the table exists (WebTiles creates it on first run, but just in case)
cur.execute("""
    CREATE TABLE IF NOT EXISTS dglusers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        flags INTEGER DEFAULT 0,
        email TEXT DEFAULT ''
    )
""")

# Insert user if not exists
cur.execute("SELECT id FROM dglusers WHERE username = ?", (username,))
if cur.fetchone():
    # Update password to stay in sync with hub credentials
    cur.execute("UPDATE dglusers SET password = ? WHERE username = ?", (hashed, username))
    print(f"User '{username}' password updated")
else:
    cur.execute(
        "INSERT INTO dglusers (username, password, flags, email) VALUES (?, ?, 0, '')",
        (username, hashed),
    )
    print(f"User '{username}' created in passwd.db3")

conn.commit()
conn.close()

# Run init-player.sh to create user directories
init_script = "/app/init-player.sh"
if os.path.exists(init_script):
    subprocess.run(["/bin/bash", init_script, username], check=True)
    print(f"Directories initialized for '{username}'")
