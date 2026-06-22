// Assembles sections/*.html fragments into index.html with generated sidebar nav.
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const SEC = path.join(ROOT, 'sections');

const header = fs.readFileSync(path.join(__dirname, 'template_header.html'), 'utf8');
const footer = fs.readFileSync(path.join(__dirname, 'template_footer.html'), 'utf8');

const files = fs.readdirSync(SEC).filter(f => f.endsWith('.html')).sort();
if (files.length === 0) { console.error('No fragments found in sections/'); process.exit(1); }

const REQUIRED_BLOCKS = ['block-exam', 'block-theory', 'block-example', 'block-vs', 'block-diagram', 'block-summary'];
const stripTags = s => s.replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();

let navHtml = '';
let content = '';
let nQs = 0, nCats = 0, warnings = [];

for (const f of files) {
  const frag = fs.readFileSync(path.join(SEC, f), 'utf8');
  const secM = frag.match(/<section class="category" id="(cat-[\w-]+)"[^>]*data-icon="([^"]*)"[^>]*data-title="([^"]*)"/);
  if (!secM) { warnings.push(`${f}: missing <section class="category"> root with data attrs`); continue; }
  const [, catId, icon, title] = secM;
  nCats++;

  // collect questions
  const qRe = /<article class="question-card" id="([^"]+)"[\s\S]*?<h3 class="q-title">([\s\S]*?)<\/h3>/g;
  let m, items = '';
  let count = 0;
  while ((m = qRe.exec(frag)) !== null) {
    count++; nQs++;
    items += `      <li><a href="#${m[1]}">${stripTags(m[2])}</a></li>\n`;
  }
  if (count === 0) warnings.push(`${f}: no question cards found`);

  // per-article block validation
  const articles = frag.split('<article class="question-card"').slice(1);
  articles.forEach((a, i) => {
    for (const b of REQUIRED_BLOCKS) if (!a.includes(b)) warnings.push(`${f} article#${i + 1}: missing ${b}`);
    if (!a.includes('<svg')) warnings.push(`${f} article#${i + 1}: missing svg diagram`);
  });

  navHtml += `    <div class="nav-cat">\n      <a href="#${catId}"><span class="caret" aria-hidden="true">▸</span><span class="ico">${icon}</span>${title}<span class="cnt">${count}</span></a>\n      <ul>\n${items}      </ul>\n    </div>\n`;
  content += '\n' + frag.trim() + '\n';
}

const date = new Date().toISOString().slice(0, 10);
let out = header.replace('<!--NAV-->', navHtml).replace('<!--CONTENT-->', content) + footer;
out = out.replaceAll('{{N_CATS}}', String(nCats)).replaceAll('{{N_QS}}', String(nQs)).replaceAll('{{DATE}}', date);

fs.writeFileSync(path.join(ROOT, 'index.html'), out, 'utf8');
console.log(`OK: index.html built — ${nCats} categories, ${nQs} questions, ${(out.length / 1024).toFixed(0)} KB`);
if (warnings.length) { console.log('WARNINGS:'); warnings.forEach(w => console.log('  - ' + w)); process.exitCode = 2; }
