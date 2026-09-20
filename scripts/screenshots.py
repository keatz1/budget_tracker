"""Render every main page at phone and laptop widths. Run: uv run python scripts/screenshots.py"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

OUT = Path("tests/screenshots")
PAGES = [
    "/",
    "/transactions",
    "/review",
    "/import",
    "/budgets",
    "/sub-budgets",
    "/rules",
    "/dashboards",
    "/accounts",
    "/settings",
    "/more",
]
WIDTHS = {"phone": (375, 812), "laptop": (1280, 800)}


def _launch(p):
    """Default Chromium, or the one preinstalled under PLAYWRIGHT_BROWSERS_PATH."""
    import glob

    try:
        return p.chromium.launch()
    except Exception:
        root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
        found = sorted(glob.glob(f"{root}/chromium-*/chrome-linux/chrome"))
        if not found:
            raise
        return p.chromium.launch(executable_path=found[-1])


def main() -> int:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp()
    env = {
        **os.environ,
        "BT_DATABASE_PATH": f"{tmp}/s.db",
        "BT_UPLOAD_DIR": f"{tmp}/up",
        "BT_SECRET_KEY": "shots",
    }
    port = "8799"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", port],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                import urllib.request

                urllib.request.urlopen(base + "/health")
                break
            except Exception:
                time.sleep(0.2)
        subprocess.run([sys.executable, "scripts/demo_data.py"], env=env, check=False)
        with sync_playwright() as p:
            browser = _launch(p)
            for name, (w, h) in WIDTHS.items():
                ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1)
                page = ctx.new_page()
                page.goto(base + "/login")
                page.fill("input[name=email]", "demo@example.com")
                page.fill("input[name=password]", "demo-password")
                page.click("button[type=submit]")
                page.wait_for_load_state("networkidle")
                for path in PAGES:
                    page.goto(base + path)
                    page.wait_for_load_state("networkidle")
                    fn = OUT / f"{name}-{path.strip('/').replace('/', '_') or 'home'}.png"
                    page.screenshot(path=str(fn), full_page=True)
                    print("wrote", fn)
                ctx.close()
            browser.close()
    finally:
        proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
