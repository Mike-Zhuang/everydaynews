import re
import subprocess
from pathlib import Path


def test_tracked_files_contain_no_secrets_or_private_ids():
    files = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"], text=True
    ).splitlines()
    pattern = re.compile(
        r"(-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
        r"(?:secret_|ntn_|sk_live_|gh[pousr]_|xox[baprs]-)[A-Za-z0-9_-]{8,}|"
        r"Bearer\s+(?!YOUR_|<|\$)[A-Za-z0-9._~-]{16,}|"
        r"NOTION_TOKEN\s*[=:]\s*['\"]?(?!YOUR_|<|\$)[^\s'\"]+)"
    )
    for name in files:
        path = Path(name)
        if path.is_file() and path.name != "uv.lock":
            assert not pattern.search(path.read_text(encoding="utf-8", errors="ignore")), name
