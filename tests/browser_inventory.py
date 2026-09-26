"""Inventory the standalone browser that generic package catalogers can miss."""

import hashlib
import json
from pathlib import Path
import re
import subprocess


browser = Path("/opt/google/chrome/chrome")
reported = subprocess.check_output([str(browser), "--version"], text=True, timeout=10)
match = re.search(r"\b(\d+\.\d+\.\d+\.\d+)\b", reported)
if not match:
    raise RuntimeError("Chrome did not report a verifiable version")
version = match.group(1)
with browser.open("rb") as stream:
    digest = hashlib.file_digest(stream, "sha256").hexdigest()
print(json.dumps({
    "bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
    "components": [{
        "type": "application", "name": "chrome", "publisher": "Google",
        "version": version, "bom-ref": f"google-chrome-{version}",
        "cpe": f"cpe:2.3:a:google:chrome:{version}:*:*:*:*:*:*:*",
        "purl": f"pkg:generic/google/chrome@{version}",
        "hashes": [{"alg": "SHA-256", "content": digest}],
        "properties": [{"name": "installed-path", "value": str(browser)}],
    }],
}))
