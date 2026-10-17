const { chromium } = require("playwright");

function laterThan(text, asOf) {
  const dates = text.match(/20\d\d-\d\d-\d\d/g) || [];
  return dates.filter((day) => day > asOf);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto("http://127.0.0.1:5280/", { waitUntil: "domcontentloaded", timeout: 60000 });
  const sequence = ["2026-10-17", "2012-01-03", "2020-03-23", "2000-01-01", "2012-01-03", "2026-10-17"];
  for (const asOf of sequence) {
    await page.locator("input[type=date]").fill(asOf);
    await page.waitForFunction(
      (day) => document.querySelector(".page")?.getAttribute("data-committed") === day,
      asOf,
      { timeout: 30000 },
    );
    const blocks = page.locator(".result");
    const count = await blocks.count();
    let text = "";
    for (let index = 0; index < count; index += 1) {
      const block = blocks.nth(index);
      if (await block.isVisible()) text += `\n${await block.innerText()}`;
    }
    const late = laterThan(text, asOf);
    if (late.length) {
      throw new Error(`${asOf} still shows later dates: ${[...new Set(late)].join(",")}`);
    }
    const pageText = await page.locator("body").innerText();
    if (asOf === "2000-01-01" && !pageText.includes("没有可见观测")) {
      throw new Error("empty date did not show the empty state");
    }
    console.log(JSON.stringify({ asOf, ok: true, chars: text.length }));
  }
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});