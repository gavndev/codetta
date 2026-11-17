"""Docker HEALTHCHECK: is Coda answering on its port?"""

import os
import sys
import urllib.request

port = os.environ.get("CODA_PORT", "8111")
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=4) as res:
        sys.exit(0 if res.status == 200 else 1)
except Exception:  # noqa: BLE001
    sys.exit(1)
