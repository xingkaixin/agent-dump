import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import sharp from "sharp";

const root = new URL("../", import.meta.url);
const dataUrl = async (path, mime) =>
  `data:${mime};base64,${(await readFile(new URL(path, root))).toString("base64")}`;
const sans = await dataUrl("node_modules/@fontsource-variable/montserrat/files/montserrat-latin-wght-normal.woff2", "font/woff2");
const mono = await dataUrl("node_modules/@fontsource/ibm-plex-mono/files/ibm-plex-mono-latin-400-normal.woff2", "font/woff2");
const logo = await dataUrl("../assets/logo.svg", "image/svg+xml");
const browser = await chromium.launch();

try {
  for (const target of [
    { width: 1200, height: 631, path: "public/assets/og-image.png", label: "agent-dump.xingkaixin.me" },
    { width: 1280, height: 640, path: "../assets/github-og.png", label: "github.com/xingkaixin/agent-dump" },
  ]) {
    const page = await browser.newPage({ viewport: { width: target.width, height: target.height }, deviceScaleFactor: 1 });
    await page.setContent(`<!doctype html><html lang="en"><head><style>
      @font-face { font-family: Montserrat; src: url('${sans}'); font-weight: 100 900; }
      @font-face { font-family: Mono; src: url('${mono}'); }
      * { box-sizing: border-box; }
      body { margin: 0; color: #171a19; background: #fcfdfc; font-family: Montserrat, sans-serif; }
      main { height: ${target.height}px; padding: 44px 56px 36px; position: relative; background-image: radial-gradient(#171a1917 1px, transparent 1px); background-size: 18px 18px; }
      header { display: flex; align-items: center; gap: 12px; font-weight: 750; font-size: 27px; letter-spacing: -1px; }
      header img { width: 54px; height: 54px; }
      .tag { margin-left: auto; font: 13px Mono; letter-spacing: 1px; color: #52615a; }
      .hero { display: grid; grid-template-columns: 1fr 470px; gap: 36px; align-items: center; height: 400px; }
      .eyebrow { font: 12px Mono; color: #166534; letter-spacing: 1.3px; margin: 0 0 20px; }
      h1 { font-size: 58px; line-height: 1.09; letter-spacing: -3.4px; font-weight: 800; margin: 0 0 25px; }
      h1 span { background: linear-gradient(transparent 57%, #4ade8059 57%, #4ade8059 94%, transparent 94%); }
      .lede { font-size: 19px; line-height: 1.65; font-weight: 500; margin: 0; max-width: 490px; color: #52615a; }
      .visual { position: relative; padding-bottom: 55px; }
      .terminal { background: #101513; color: #dbe3df; border-radius: 12px; border: 1px solid #26302c; box-shadow: 0 24px 40px -24px #10201a66; overflow: hidden; font: 14px/1.8 Mono; }
      .bar { background: #161d1a; border-bottom: 1px solid #26302c; padding: 12px 20px; color: #8b9893; display: flex; justify-content: space-between; font-size: 12px; }
      .green { color: #4ade80; }
      .shell { padding: 22px 24px 28px; }
      .output { color: #8b9893; padding: 5px 0 20px; }
      .command { white-space: nowrap; }
      .paper { position: absolute; right: 22px; bottom: -30px; width: 267px; background: white; border: 1px solid #d2d9d6; border-radius: 5px; padding: 17px 21px; transform: rotate(-4deg); box-shadow: 0 5px 12px #10201a0d; }
      .paper small { font: 10px Mono; letter-spacing: 1.3px; color: #6b7370; }
      .paper p { margin: 8px 0 12px; font: 16px Mono; }
      .paper i { display: block; height: 5px; background: #e4e8e6; margin-top: 6px; width: 85%; }
      .paper i:last-child { width: 62%; background: #b6f2cb; }
      footer { position: absolute; left: 56px; right: 56px; bottom: 34px; border-top: 1px solid #d2d9d6; padding-top: 20px; display: flex; justify-content: space-between; align-items: center; font: 12px Mono; color: #52615a; }
      footer strong { color: #166534; font-weight: 400; }
    </style></head><body><main>
      <header><img src="${logo}" alt=""><span>Agent Dump</span><span class="tag">LOCAL AI SESSION CLI</span></header>
      <section class="hero"><div>
        <p class="eyebrow">FIND / READ / EXPORT / REUSE</p>
        <h1>Your sessions.<br><span>Still useful.</span></h1>
        <p class="lede">Your AI coding history, ready for<br>the next agent.</p>
      </div><div class="visual">
        <div class="terminal"><div class="bar"><span><span class="green">&gt;_</span> agent-dump</span><span>zsh</span></div>
        <div class="shell"><div class="command"><span class="green">$</span> agent-dump search 'auth timeout'</div>
        <div class="output"><span class="green">›</span> claude://7f3c91 · msg 14<br><span class="green">›</span> codex://019a7c2e · msg 3<br><span class="green">›</span> cursor://b21e04 · msg 1</div>
        <div class="command"><span class="green">$</span> agent-dump export codex://019a7c2e</div>
        <div class="green">ok · source untouched</div></div></div>
        <div class="paper"><small>MARKDOWN · READY TO REUSE</small><p>session.md</p><i></i><i></i></div>
      </div></section>
      <footer><span>Codex · Claude Code · Cursor <strong>+ 7 more</strong></span><span>${target.label}</span></footer>
    </main></body></html>`);
    await page.evaluate(() => document.fonts.ready);
    const png = await page.screenshot();
    const output = fileURLToPath(new URL(target.path, root));
    await sharp(png).png({ compressionLevel: 9 }).toFile(output);
    console.log(`${output} (${target.width} × ${target.height})`);
    await page.close();
  }
} finally {
  await browser.close();
}
