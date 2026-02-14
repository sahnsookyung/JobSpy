#!/usr/bin/env python3
import json
import urllib.request
import urllib.error
import ssl
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

INPUT_FILE = Path(__file__).parent / "remote_jobs.json"
OUTPUT_FILE = Path(__file__).parent / "broken_links.txt"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def check_url(entry):
    url = entry["url"]
    company = entry["company"]
    try:
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "Mozilla/5.0")
        with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
            if response.status >= 400:
                return (company, url, response.status)
    except urllib.error.HTTPError as e:
        return (company, url, e.code)
    except Exception as e:
        return (company, url, str(e))
    return None

def main():
    with open(INPUT_FILE) as f:
        entries = json.load(f)

    print(f"Checking {len(entries)} links...")
    broken = []

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(check_url, entry): entry for entry in entries}
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            if result:
                broken.append(result)
                print(f"[{i}/{len(entries)}] BROKEN: {result[0]} -> {result[1]} ({result[2]})")
            else:
                print(f"[{i}/{len(entries)}] OK")

    with open(OUTPUT_FILE, "w") as f:
        for company, url, status in broken:
            f.write(f"{url} | {status}\n")

    print(f"\nFound {len(broken)} broken links. Saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
