#!/usr/bin/env python3
"""Patch userdb.py to transparently upgrade weak password hashes to SHA-512 on login."""
import os

PATHS = [
    "/app/source/webserver/webtiles/userdb.py",
    "/app/source-trunk/webserver/webtiles/userdb.py",
    "/app/source-0.33/webserver/webtiles/userdb.py",
    "/app/source-0.32/webserver/webtiles/userdb.py",
    "/app/source-0.31/webserver/webtiles/userdb.py",
    "/app/source-0.30/webserver/webtiles/userdb.py",
]

MARKER = "# DCSS-INSTALL-REHASH-PATCH"

OLD = """    elif result and crypt.crypt(passwd, result[1]) == result[1]:
        return True, result[0], None"""

NEW = """    elif result and crypt.crypt(passwd, result[1]) == result[1]:
        """ + MARKER + """
        if not result[1].startswith('$6$'):
            new_hash = encrypt_pw(passwd)
            with user_db as db:
                db.execute("UPDATE dglusers SET password=? WHERE username=? COLLATE NOCASE",
                           (new_hash, result[0]))
            logging.info("[Auth] Upgraded password hash for %s to SHA-512", result[0])
        return True, result[0], None"""

for path in PATHS:
    if not os.path.exists(path):
        continue
    with open(path) as f:
        content = f.read()
    if MARKER in content:
        print(f"[rehash-patch] Already patched {path}, skipping.")
        continue
    if OLD not in content:
        print(f"[rehash-patch] WARNING: Could not find target in {path}, skipping.")
        continue
    content = content.replace(OLD, NEW)
    with open(path, 'w') as f:
        f.write(content)
    print(f"[rehash-patch] Patched {path} — weak hashes will upgrade to SHA-512 on login.")
