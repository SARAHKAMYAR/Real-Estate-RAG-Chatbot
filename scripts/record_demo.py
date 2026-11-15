"""Record a short demo video of the chatbot.

Drives the real chat page in Chrome, one scene per question, and joins the clips into an MP4.
Needs the server running, plus `pip install playwright`, `playwright install ffmpeg` and the
`ffmpeg` command.

    python scripts/record_demo.py --url http://localhost:8010 --out demo.mp4
    python scripts/record_demo.py --only 3          # re-record one scene, then re-join
    python scripts/record_demo.py --only            # rebuild the title cards and re-join

Each scene is recorded separately with a pause in between, so a free-tier rate limit never
shows up as dead air in the video.
"""

import argparse
import subprocess
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

WIDTH, HEIGHT = 1280, 720

SCENES = [
    {
        "caption": "Answers come from the company's own documents",
        "question": "What commission do you charge to sell a home?",
        "open_source": True,
    },
    {
        "caption": "Listings are searched with exact filters",
        "question": "Which homes for sale in Utrecht cost less than €500,000?",
        "open_source": False,
    },
    {
        "caption": "It combines a policy rule with a listing",
        "question": "What gross monthly income do I need to rent NL-2002?",
        "open_source": True,
    },
    {
        "caption": "When the answer is not in the data, it says so",
        "question": "Who is the managing director of Noorderlicht Makelaars?",
        "open_source": False,
    },
    {
        "caption": "Outside questions fall back to web search, clearly labelled",
        "question": "Where can I find official information about buying a home in the Netherlands?",
        "open_source": True,
    },
]

CARD_CSS = """
  * { box-sizing: border-box; }
  body { margin: 0; height: 100vh; display: grid; place-items: center; background: #14211c;
         color: #f3f1ea; font-family: system-ui, -apple-system, 'Segoe UI', sans-serif; }
  main { width: 980px; }
  .eyebrow { font-size: 20px; letter-spacing: 0.14em; text-transform: uppercase;
             color: #6cc3a3; font-weight: 600; }
  h1 { font-size: 68px; line-height: 1.05; margin: 18px 0 22px; letter-spacing: -0.02em; }
  p { font-size: 28px; line-height: 1.4; color: #c5cfc9; margin: 0; max-width: 820px; }
  .row { display: flex; gap: 14px; margin-top: 44px; flex-wrap: wrap; }
  .chip { border: 1px solid #36493f; border-radius: 999px; padding: 10px 20px; font-size: 21px;
          color: #dfe6e1; }
  .score { font-size: 150px; font-weight: 700; letter-spacing: -0.04em; line-height: 1;
           color: #6cc3a3; margin: 14px 0 6px; }
  .score span { color: #f3f1ea; font-size: 64px; font-weight: 600; letter-spacing: -0.02em; }
  table { margin-top: 36px; border-collapse: collapse; font-size: 24px; color: #c5cfc9; }
  td { padding: 6px 40px 6px 0; } td:last-child { color: #f3f1ea; font-weight: 600; }
"""

TITLE_CARD = f"""<style>{CARD_CSS}</style><main>
  <div class="eyebrow">Demo · fictional company and listings</div>
  <h1>Real Estate RAG Chatbot</h1>
  <p>Answers customer questions from a company's own documents and property listings,
     and shows the sources the model cited. Answers can be wrong.</p>
  <div class="row"><span class="chip">FastAPI</span><span class="chip">PostgreSQL + pgvector</span>
    <span class="chip">Hybrid search</span><span class="chip">Tavily web fallback</span></div>
</main>"""

END_CARD = f"""<style>{CARD_CSS}</style><main>
  <div class="eyebrow">Historical baseline · 14 November 2026</div>
  <div class="score">28 <span>of 30</span></div>
  <p>cases passed rule-based regression checks.<br>
     Groq GPT-OSS 120B · Web search off · Before release fixes.</p>
  <table>
    <tr><td>Company documents</td><td>13 of 14</td></tr>
    <tr><td>Listings</td><td>8 of 9</td></tr>
    <tr><td>Multi-step questions</td><td>3 of 3</td></tr>
    <tr><td>Correctly said "not in our data"</td><td>4 of 4</td></tr>
  </table>
</main>"""

# Larger text for video, a caption bar, and a visible pointer (recordings have no cursor).
PAGE_SETUP = """
(caption) => {
  const style = document.createElement('style');
  style.textContent = `
    :root { color-scheme: light; }
    body { zoom: 1.3; }
    main { padding-top: 46px !important; }
    #demo-caption { position: fixed; inset: 0 0 auto 0; z-index: 50; background: #14211c;
      color: #f3f1ea; font: 600 15px system-ui, sans-serif; padding: 11px 22px;
      display: flex; gap: 12px; align-items: center; }
    #demo-caption b { color: #6cc3a3; letter-spacing: 0.08em; text-transform: uppercase;
      font-size: 11.5px; }
    #demo-pointer { position: fixed; z-index: 60; width: 16px; height: 16px; border-radius: 50%;
      background: rgba(31, 95, 74, 0.35); border: 2px solid #1f5f4a; pointer-events: none;
      transform: translate(-50%, -50%); left: -40px; top: -40px;
      transition: left 0.45s ease, top 0.45s ease; }
  `;
  document.head.appendChild(style);
  const bar = document.createElement('div');
  bar.id = 'demo-caption';
  bar.innerHTML = `<b>${caption.step}</b><span>${caption.text}</span>`;
  document.body.appendChild(bar);
  const pointer = document.createElement('div');
  pointer.id = 'demo-pointer';
  document.body.appendChild(pointer);
  document.getElementById('examples')?.remove();
}
"""


def point_at(page: Page, selector: str) -> None:
    """Glide the on-screen pointer to the centre of an element."""
    page.evaluate(
        """(selector) => {
          const zoom = parseFloat(getComputedStyle(document.body).zoom) || 1;
          const els = document.querySelectorAll(selector);
          const box = els[els.length - 1].getBoundingClientRect();
          const pointer = document.getElementById('demo-pointer');
          pointer.style.left = (box.left + box.width / 2) / zoom + 'px';
          pointer.style.top = (box.top + box.height / 2) / zoom + 'px';
        }""",
        selector,
    )
    page.wait_for_timeout(650)


def record_card(browser, html: str, seconds: float, target: Path) -> None:
    """Render a title card to an image and turn it into a still clip."""
    page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
    page.set_content(f"<!doctype html><meta charset='utf-8'>{html}")
    image = target.with_suffix(".png")
    page.screenshot(path=str(image))
    page.close()
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-t", str(seconds + 0.45),
         "-i", str(image), "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target)],
        check=True,
    )  # fmt: skip
    image.unlink()


def record_scene(browser, url: str, number: int, scene: dict, target: Path) -> float:
    """Record one question. Returns how long the answer took, in seconds."""
    context = browser.new_context(
        viewport={"width": WIDTH, "height": HEIGHT},
        color_scheme="light",
        record_video_dir=str(target.parent),
        record_video_size={"width": WIDTH, "height": HEIGHT},
    )
    page = context.new_page()
    page.goto(url)
    page.evaluate(PAGE_SETUP, {"step": f"{number} of {len(SCENES)}", "text": scene["caption"]})
    page.wait_for_timeout(1600)

    point_at(page, "#input")
    page.click("#input")
    page.keyboard.type(scene["question"], delay=38)
    page.wait_for_timeout(500)
    point_at(page, "#send")
    started = time.perf_counter()
    page.click("#send")
    page.wait_for_selector(".msg.bot .meta, .msg.bot.error", timeout=180_000)
    waited = time.perf_counter() - started
    if page.query_selector(".msg.bot.error"):
        context.close()
        Path(page.video.path()).unlink(missing_ok=True)
        raise RuntimeError(f"scene {number}: the chatbot returned an error")
    page.wait_for_timeout(3800)

    if scene["open_source"] and page.query_selector(".cite"):
        point_at(page, ".msg.bot .cite")
        page.click(".msg.bot .cite >> nth=0")
        page.evaluate("document.getElementById('demo-pointer').style.left = '-40px'")
        page.wait_for_timeout(4200)
    else:
        page.wait_for_timeout(1500)

    context.close()
    Path(page.video.path()).replace(target)
    return waited


def join(clips: list[Path], out: Path) -> None:
    """Trim the blank first frames of each clip, fade each in, and join to H.264 MP4."""
    inputs, filters = [], []
    for i, clip in enumerate(clips):
        inputs += ["-i", str(clip)]
        filters.append(
            f"[{i}:v]trim=start=0.45,setpts=PTS-STARTPTS,fps=30,scale={WIDTH}:{HEIGHT},"
            f"fade=t=in:st=0:d=0.35[v{i}]"
        )
    chain = "".join(f"[v{i}]" for i in range(len(clips)))
    filters.append(f"{chain}concat=n={len(clips)}:v=1:a=0[out]")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters),
         "-map", "[out]", "-c:v", "libx264", "-preset", "slow", "-crf", "20",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
        check=True,
    )  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--out", default="demo.mp4")
    parser.add_argument("--clips", default="demo-clips", help="folder for the per-scene clips")
    parser.add_argument("--only", type=int, nargs="*", help="re-record only these scene numbers")
    parser.add_argument("--pause", type=int, default=45, help="seconds between scenes")
    args = parser.parse_args()

    clips_dir = Path(args.clips)
    clips_dir.mkdir(parents=True, exist_ok=True)
    wanted = set(range(1, len(SCENES) + 1) if args.only is None else args.only)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        if args.only is None or args.only == []:
            record_card(browser, TITLE_CARD, 4.5, clips_dir / "0-title.mp4")
            record_card(browser, END_CARD, 6.5, clips_dir / "9-end.mp4")
        for number, scene in enumerate(SCENES, start=1):
            if number not in wanted:
                continue
            waited = record_scene(browser, args.url, number, scene, clips_dir / f"{number}.webm")
            print(f"scene {number}: answered in {waited:.1f}s", flush=True)
            if number != max(wanted, default=0):
                time.sleep(args.pause)
        browser.close()

    clips = sorted(p for p in clips_dir.iterdir() if p.suffix in {".webm", ".mp4"})
    join(clips, Path(args.out))
    print(f"wrote {args.out} from {len(clips)} clips")


if __name__ == "__main__":
    main()
