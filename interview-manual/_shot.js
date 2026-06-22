// 临时:Playwright getBBox 自检 + 出图(金样 v2)
const { chromium } = require('D:/mys/Financial-Research-Investment-Assistant/frontend/node_modules/playwright');
const fs = require('fs');
const path = require('path');

const EXE = 'C:/Users/Administrator/AppData/Local/ms-playwright/chromium-1223/chrome-win64/chrome.exe';
const OUT = path.join(__dirname, '_shots');
const URL = 'http://127.0.0.1:8765/?v=2';

(async () => {
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ executablePath: EXE, headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForTimeout(1200);

  // ---- getBBox 溢出 + 计数自检 ----
  const audit = await page.evaluate(() => {
    const bad = [];
    document.querySelectorAll('.diagram svg').forEach(svg => {
      const vb = svg.viewBox.baseVal; const card = svg.closest('.question-card'); const id = card ? card.id : '?';
      svg.querySelectorAll('text,tspan').forEach(t => {
        let b; try { b = t.getBBox(); } catch { return; }
        if (b.width && (b.x < vb.x-2 || b.x+b.width > vb.x+vb.width+2 || b.y < vb.y-2 || b.y+b.height > vb.y+vb.height+2))
          bad.push(id + ': "' + t.textContent.slice(0,18) + '"');
      });
    });
    return {
      overflows: bad, overflowCount: bad.length,
      horizontalOverflowPx: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      questionCards: document.querySelectorAll('.question-card').length,
      svgs: document.querySelectorAll('.diagram svg').length,
      vsTables: document.querySelectorAll('.vs-table').length,
      pres: document.querySelectorAll('.block-example pre').length,
    };
  });
  console.log('AUDIT', JSON.stringify(audit));

  const shot = async (sel, name) => {
    const el = page.locator(sel);
    await el.scrollIntoViewIfNeeded();
    await el.screenshot({ path: path.join(OUT, name) });
  };
  await page.screenshot({ path: path.join(OUT, '1-hero.png'), clip: { x: 0, y: 0, width: 1440, height: 900 } });
  await shot('#loop-q1', '2-q1-basics-card.png');          // 基础题整卡(看是否够浅)
  await shot('#loop-q1 .block-example', '3-q1-pseudocode.png'); // 伪代码示例
  await shot('#loop-q2 .diagram', '4-q2-anatomy-diagram.png');  // 循环解剖图
  await shot('#loop-q5 .diagram', '5-q5-window-diagram.png');   // 窗口四区(难)
  await shot('#loop-q8 .block-example', '6-q8-pseudocode.png'); // function calling 坑的伪代码

  await browser.close();
  console.log('OK shots:', fs.readdirSync(OUT).join('  '));
})().catch(e => { console.error('SHOT FAIL:', e.message); process.exit(1); });
