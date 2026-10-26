"""Records an end-to-end workflow video and high-resolution screenshots of the running workbench.

Usage (with the app running on http://localhost:8000):

    pip install -r requirements-dev.txt
    python scripts/capture_media.py [--base-url http://localhost:8000] [--skip-video] [--skip-screenshots]

Outputs land in docs/media/: screenshots/*.png and jev-workbench-demo.mp4 (ffmpeg converts
Playwright's .webm when ffmpeg is on PATH).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "docs" / "media"
SHOTS = MEDIA / "screenshots"
VIEWPORT = {"width": 1440, "height": 900}

# A visible cursor and click ripple, since Playwright videos do not show the pointer.
CURSOR_JS = """
(() => {
  if (window.__demoCursor) return;
  const install = () => {
    const c = document.createElement('div');
    c.id = '__demo-cursor';
    c.style.cssText = 'position:fixed;left:0;top:0;width:22px;height:22px;z-index:2147483647;pointer-events:none;' +
      'transition:transform .55s cubic-bezier(.3,.7,.2,1);transform:translate(720px,450px)';
    c.innerHTML = '<svg width="22" height="22" viewBox="0 0 22 22"><path d="M3 2l14 8-6 1.6L8.6 18z" fill="#fff" stroke="#0f172a" stroke-width="1.5" stroke-linejoin="round"/></svg>';
    document.body.appendChild(c);
    window.__demoCursor = {
      move(x, y) { c.style.transform = `translate(${x - 3}px, ${y - 2}px)`; },
      ripple(x, y) {
        const r = document.createElement('div');
        r.style.cssText = `position:fixed;left:${x - 18}px;top:${y - 18}px;width:36px;height:36px;border-radius:50%;` +
          'border:2px solid #38bdf8;z-index:2147483646;pointer-events:none;transition:transform .45s,opacity .45s;opacity:.9';
        document.body.appendChild(r);
        requestAnimationFrame(() => { r.style.transform = 'scale(1.8)'; r.style.opacity = '0'; });
        setTimeout(() => r.remove(), 500);
      },
    };
  };
  document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', install) : install();
})();
"""


class Demo:
    def __init__(self, page: Page, video: bool):
        self.page = page
        self.video = video

    def pause(self, ms: int) -> None:
        if self.video:
            self.page.wait_for_timeout(ms)

    def point(self, selector: str):
        loc = self.page.locator(selector).first
        loc.scroll_into_view_if_needed()
        box = loc.bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        if self.video:
            self.page.evaluate(f"window.__demoCursor && window.__demoCursor.move({x}, {y})")
            self.page.wait_for_timeout(650)
        return loc, x, y

    def click(self, selector: str) -> None:
        loc, x, y = self.point(selector)
        if self.video:
            self.page.evaluate(f"window.__demoCursor && window.__demoCursor.ripple({x}, {y})")
        loc.click()

    def run(self, selector: str, endpoint: str) -> None:
        """Clicks a submit button and waits for the live decision to come back."""
        with self.page.expect_response(lambda r: endpoint in r.url and r.request.method == "POST", timeout=30_000):
            self.click(selector)
        self.page.wait_for_timeout(500)  # let meters animate

    def select(self, selector: str, label: str) -> None:
        self.point(selector)
        self.page.select_option(selector, label=label)
        self.pause(500)

    def type_into(self, selector: str, text: str) -> None:
        self.click(selector)
        self.page.fill(selector, "")
        if self.video:
            self.page.locator(selector).press_sequentially(text, delay=28)
        else:
            self.page.fill(selector, text)
        self.pause(400)

    def tab(self, name: str) -> None:
        self.click(f'.tab[data-tab="{name}"]')
        self.pause(700)

    def shot(self, name: str, selector: str | None = None) -> None:
        if self.video:
            return
        if selector:
            # Element shots scroll the page; keep the sticky header from painting over them.
            self.page.add_style_tag(content="header { position: static !important; }")
            self.page.locator(selector).first.screenshot(path=str(SHOTS / f"{name}.png"))
        else:
            self.page.evaluate("window.scrollTo(0, 0)")
            self.page.wait_for_timeout(200)
            self.page.screenshot(path=str(SHOTS / f"{name}.png"))
        print(f"  screenshot {name}.png")


def workflow(page: Page, base_url: str, video: bool) -> None:
    d = Demo(page, video)
    page.goto(base_url)
    page.wait_for_function("document.querySelector('#mode-badge').textContent !== 'Checking…'")
    d.pause(1800)
    d.shot("00-workbench-overview")

    # Tab 1: ticket triage across the presets.
    d.run("#triage-form button[type=submit]", "/api/v1/triage")
    d.pause(3200)
    d.shot("01-triage-billing-automated")
    d.shot("01b-triage-billing-result", "#triage-result")

    d.select("#triage-preset", "Cryptic 3-Word Crash Report")
    d.run("#triage-form button[type=submit]", "/api/v1/triage")
    d.pause(3200)
    d.shot("02-triage-cryptic-escalated")

    d.select("#triage-preset", "Urgent Security Breach")
    d.run("#triage-form button[type=submit]", "/api/v1/triage")
    d.pause(3000)
    d.shot("03-triage-security-p1")

    d.select("#triage-preset", "Custom…")
    d.type_into("#triage-subject", "Export to CSV broken since update")
    d.type_into(
        "#triage-text",
        "Since yesterday's update, every CSV export from the Reports page fails with error 504 after 30 seconds. "
        "Our finance team needs the month-end export today.",
    )
    d.run("#triage-form button[type=submit]", "/api/v1/triage")
    d.pause(3200)
    d.shot("04-triage-custom-ticket")

    # Tab 2: task router.
    d.tab("route")
    d.run("#route-form button[type=submit]", "/api/v1/route")
    d.pause(2600)
    d.type_into("#route-title", "Approve exception to vendor payment policy")
    d.type_into(
        "#route-desc",
        "Vendor is asking us to wire a $250k prepayment outside our standard net-60 terms. Needs sign-off before Friday.",
    )
    d.run("#route-form button[type=submit]", "/api/v1/route")
    d.pause(3200)
    d.shot("05-router-human-review")

    # Tab 3: transcript clipper.
    d.tab("clip")
    d.run("#clip-form button[type=submit]", "/api/v1/clip")
    d.pause(3000)
    d.shot("06-clipper-clip-it")
    d.type_into("#clip-segment", "and so, um, like I was saying before about that, yeah, so then we moved on to the next slide.")
    d.run("#clip-form button[type=submit]", "/api/v1/clip")
    d.pause(3000)
    d.shot("07-clipper-skip")

    # Tab 4: custom playground.
    d.tab("custom")
    d.run("#custom-form button[type=submit]", "/api/v1/decide")
    d.pause(3000)
    d.shot("08-playground-result")
    d.click("#custom-result details summary")
    d.pause(600)
    page.locator("#custom-result details").scroll_into_view_if_needed()
    d.pause(2600)
    d.shot("09-playground-raw-answers", "#custom-result")

    # Back to the overview for the closing frame.
    page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
    d.tab("triage")
    d.pause(1500)


def to_mp4(webm: Path, mp4: Path) -> Path:
    if not shutil.which("ffmpeg"):
        return webm
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm), "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-crf", "22", "-preset", "slow", "-movflags", "+faststart", str(mp4)],
        check=True,
    )
    webm.unlink()
    return mp4


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--skip-video", action="store_true")
    parser.add_argument("--skip-screenshots", action="store_true")
    args = parser.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        if not args.skip_video:
            print("Recording workflow video…")
            raw_dir = MEDIA / "_raw"
            ctx = browser.new_context(viewport=VIEWPORT, record_video_dir=str(raw_dir), record_video_size=VIEWPORT)
            ctx.add_init_script(CURSOR_JS)
            page = ctx.new_page()
            workflow(page, args.base_url, video=True)
            webm_path = Path(page.video.path())
            ctx.close()
            final = to_mp4(webm_path, MEDIA / "jev-workbench-demo.mp4")
            if final.suffix == ".webm":
                final = webm_path.rename(MEDIA / "jev-workbench-demo.webm")
            shutil.rmtree(raw_dir, ignore_errors=True)
            print(f"  video {final.relative_to(ROOT)}")
        if not args.skip_screenshots:
            print("Capturing screenshots…")
            ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
            workflow(ctx.new_page(), args.base_url, video=False)
            ctx.close()
        browser.close()


if __name__ == "__main__":
    main()
