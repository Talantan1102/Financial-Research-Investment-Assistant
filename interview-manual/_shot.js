// 临时:用 frontend 的 Playwright + chromium-1223 给金样分类出图(稳过 Chrome MCP 卡死)
const { chromium } = require('D:/mys/Financial-Research-Investment-Assistant/frontend/node_modules/playwright');
const fs = require('fs');
const path = require('path');

const EXE = 'C:/Users/Administrator/AppData/Local/ms-playwright/chromium-1223/chrome-win64/chrome.exe';
const OUT = path.join(__dirname, '_shots');
const URL = 'http://127.0.0.1:8765/';

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ executablePath: EXE, headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
  await page.goto(URL, { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForTimeout(1200); // 等字体 + highlight.js

  // 1) 顶部 hero + 第一题开头(裁剪一屏)
  await page.screenshot({ path: path.join(OUT, '1-hero.png'), clip: { x: 0, y: 0, width: 1440, height: 900 } });

  // 2) Q1 整张题卡(含 7 facet,可能很长)
  const q1 = page.locator('#loop-q1');
  await q1.scrollIntoViewIfNeeded();
  await q1.screenshot({ path: path.join(OUT, '2-q1-card.png') });

  // 3) Q1 图解 SVG 单独出图
  const dia = page.locator('#loop-q1 .diagram');
  await dia.scrollIntoViewIfNeeded();
  await dia.screenshot({ path: path.join(OUT, '3-q1-diagram.png') });

  // 4) Q1 决策对比表单独出图
  const vs = page.locator('#loop-q1 .block-vs');
  await vs.scrollIntoViewIfNeeded();
  await vs.screenshot({ path: path.join(OUT, '4-q1-vs.png') });

  // 5) Q3 图解(窗口四区,难度 5★)看另一种图
  const d3 = page.locator('#loop-q3 .diagram');
  await d3.scrollIntoViewIfNeeded();
  await d3.screenshot({ path: path.join(OUT, '5-q3-diagram.png') });

  await browser.close();
  const files = fs.readdirSync(OUT).map(f => f + '(' + Math.round(fs.statSync(path.join(OUT, f)).size / 1024) + 'KB)');
  console.log('OK shots:', files.join('  '));
})().catch(e => { console.error('SHOT FAIL:', e.message); process.exit(1); });
