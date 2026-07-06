import { chromium } from 'playwright';
import { execSync } from 'child_process';
import fs from 'fs';

const OUT = '/tmp/all_option_buying_advices.json';
const STATE = '/tmp/stratzy_storage_state.json';

function getCookies() {
  try {
    return JSON.parse(execSync('python3 /tmp/export_cookies.py', { encoding: 'utf8' }));
  } catch {
    return [];
  }
}

function toIso(dateStr) {
  const [d, m, y] = dateStr.split('/');
  return `${y}-${m.padStart(2, '0')}-${d.padStart(2, '0')}`;
}

function isOptionBuying(a) {
  const cat = (a.displayCategory || a.category || '').toLowerCase();
  return cat === 'option buying';
}

async function waitForLogin(page) {
  for (let i = 0; i < 60; i++) {
    const resp = await page.request.get('https://stratzy.in/api/mobile/profile', {
      headers: { Accept: 'application/json' },
    });
    if (resp.ok()) {
      const body = await resp.json();
      if (body?.data?.name || body?.name) {
        console.log('LOGGED_IN:', body?.data?.name || body?.name);
        return true;
      }
    }
    await page.waitForTimeout(2000);
  }
  console.log('Proceeding without confirmed login...');
  return false;
}

async function main() {
  const algoList = JSON.parse(
    execSync("curl -s 'https://stratzy.in/api/web/algo/list'", { encoding: 'utf8' })
  );
  const optionBuying = algoList.data.filter(isOptionBuying);
  console.log(`Found ${optionBuying.length} Option Buying algos`);

  const cookies = getCookies();
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext();
  if (fs.existsSync(STATE)) {
    try {
      await context.addCookies(JSON.parse(fs.readFileSync(STATE, 'utf8')).cookies || getCookies());
    } catch {
      if (cookies.length) await context.addCookies(cookies);
    }
  } else if (cookies.length) {
    await context.addCookies(cookies);
  }

  const page = await context.newPage();
  await page.goto('https://stratzy.in/explore', { waitUntil: 'domcontentloaded', timeout: 120000 });
  await waitForLogin(page);

  const all = {};
  for (let i = 0; i < optionBuying.length; i++) {
    const algo = optionBuying[i];
    const perf = algo.performance || {};
    const dates = Object.keys(perf).sort((a, b) => toIso(a).localeCompare(toIso(b)));
    const trades = [];
    let ok = 0;
    let fail = 0;
    for (const d of dates) {
      const iso = toIso(d);
      const url = `https://stratzy.in/api/web/pastAdvices?advisorId=${algo._id}&date=${iso}`;
      const resp = await page.request.get(url, { headers: { Accept: 'application/json' } });
      if (!resp.ok()) {
        fail++;
        continue;
      }
      const body = await resp.json();
      const items = body?.pastAdvices || [];
      if (items.length) {
        trades.push({ date: d, iso, items });
        ok++;
      }
    }
    const tradeCount = trades.reduce((n, t) => n + t.items.length, 0);
    all[algo.name] = { algo, trades, ok, fail, dates: dates.length, tradeCount };
    console.log(`[${i + 1}/${optionBuying.length}] ${algo.name} — ${tradeCount} signals, ${fail} errors`);
  }

  fs.writeFileSync(OUT, JSON.stringify(all, null, 2));
  console.log(`DONE: ${OUT}`);
  await browser.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});