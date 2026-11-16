// Drive an Odoo build in headless Chromium as a given user, from a small steps script.
// Started by browse.sh, which creates the session and always logs it out afterwards.
//
//   node browse.js <session file> <steps.js> <outdir>
//
// steps.js exports one async function that receives `o`:
//
//   module.exports = async (o) => {
//     await o.goto('/odoo/accounting');
//     o.note('journals', await o.kanbanTitles());
//     await o.shot('dashboard');
//   };
//
// Writes <outdir>/NN_<name>.png and <outdir>/report.json (notes, screenshots, browser console
// errors, page errors, failed requests). Exit 1 when the steps threw or the page raised errors.
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const [sessionFile, stepsFile, outdir] = process.argv.slice(2);
const s = JSON.parse(fs.readFileSync(sessionFile, 'utf8'));
const NAV = { waitUntil: 'domcontentloaded', timeout: 180000 };

(async () => {
  // Pages here run a branch's code: keep Chromium's sandbox. Some Linux setups (Ubuntu's AppArmor rule on
  // unprivileged user namespaces) cannot start it; only then does it run without, and says so.
  let browser;
  try {
    browser = await chromium.launch();
  } catch (error) {
    if (!/sandbox|namespace|zygote/i.test(String(error))) throw error;
    console.error('Chromium sandbox unavailable here; running without it (only staging/dev pages are opened).');
    browser = await chromium.launch({ args: ['--no-sandbox'] });
  }
  const [w, h] = (process.env.BROWSE_VIEWPORT || '1400x900').split('x').map(Number);
  const context = await browser.newContext({
    viewport: { width: w, height: h },
    locale: process.env.BROWSE_LOCALE || undefined,
  });
  await context.addCookies([{ name: 'session_id', value: s.sid, url: s.url }]);
  const page = await context.newPage();
  const report = { url: s.url, db: s.db, uid: s.uid, login: s.login, notes: {}, screenshots: [],
                   console_errors: [], page_errors: [], failed_requests: [], error: null };
  page.on('console', m => { if (m.type() === 'error') report.console_errors.push(m.text().slice(0, 500)); });
  page.on('pageerror', e => report.page_errors.push(e.message.slice(0, 500)));
  page.on('response', r => { if (r.status() >= 500) report.failed_requests.push(`${r.status()} ${r.url()}`); });
  let shots = 0;

  const o = {
    page, context, browser, url: s.url, uid: s.uid, outdir,

    // Wait until Odoo has no request in flight and no blocking overlay.
    async idle(extra = 500) {
      await page.waitForFunction(() => !document.querySelector('.o_blockUI, .o_loading_indicator:not(.d-none)'),
                                 null, { timeout: 120000 }).catch(() => {});
      await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
      await page.waitForTimeout(extra);
    },
    // Path ('/odoo/accounting', '/odoo/action-account.action_account_journal_form',
    // '/odoo/customer-invoices/106862') or full URL. `waitFor` = selector that means "loaded".
    async goto(where, waitFor = '.o_action_manager .o_view_controller, .o_action_manager .o_form_view, .pos, .o_website_preview') {
      await page.goto(where.startsWith('http') ? where : s.url + where, NAV);
      await page.waitForSelector(waitFor, { timeout: 180000 }).catch(() => {});
      await o.idle();
    },
    async shot(name, opts = {}) {
      const file = path.join(outdir, `${String(++shots).padStart(2, '0')}_${name}.png`);
      await page.screenshot({ path: file, fullPage: !!opts.full });
      report.screenshots.push(file);
      return file;
    },
    note(key, value) { report.notes[key] = value; },

    // Form helpers. `name` is the technical field / button name.
    field(name, scope = '') { return page.locator(`${scope} div[name="${name}"]`.trim()).first(); },
    async button(name, scope = '') { await page.locator(`${scope} button[name="${name}"]`.trim()).first().click(); await o.idle(); },
    async fill(name, value, scope = '') {
      const input = o.field(name, scope).locator('input, textarea').first();
      await input.fill(String(value)); await input.press('Tab'); await o.idle();
    },
    // Options a many2one dropdown offers (optionally after typing), then closes it unchanged.
    async m2oOptions(name, typed = null, scope = '') {
      const input = o.field(name, scope).locator('input').first();
      const before = await input.inputValue();
      await input.click(); await o.idle(800);
      if (typed !== null) { await input.fill(typed); await o.idle(800); }
      const items = await page.$$eval('.o-autocomplete--dropdown-menu li', els => els.map(e => e.textContent.trim()));
      await page.keyboard.press('Escape');
      if (typed !== null) { await input.fill(before); await page.keyboard.press('Escape'); }
      return items;
    },
    // Leave the current form WITHOUT saving: Odoo 17+ auto-saves a changed form on navigation,
    // which leaves junk draft records behind. Call before every goto() after touching a form.
    async discard() {
      const btn = page.locator('.o_form_button_cancel, button.o_form_discard').first();
      if (await btn.isVisible().catch(() => false)) { await btn.click(); await o.idle(); }
      const modal = page.locator('.modal .modal-footer button.btn-primary:has-text("Discard"), .modal .modal-footer button:has-text("تجاهل")').first();
      if (await modal.isVisible().catch(() => false)) { await modal.click(); await o.idle(); }
    },
    async closeDialogs() {
      for (let i = 0; i < 5; i++) {
        const close = page.locator('.modal .btn-close, .modal button.o_form_button_cancel').last();
        if (!(await close.isVisible().catch(() => false))) break;
        await close.click(); await o.idle(300);
      }
    },

    // Views
    async pager() { return page.$eval('.o_pager_value, .o_pager_counter', e => e.textContent.trim()).catch(() => null); },
    async listColumn(name, scope = '') {
      return page.$$eval(`${scope} .o_data_row td[name="${name}"]`.trim(), els => els.map(e => e.textContent.trim()));
    },
    async kanbanTitles() {
      return page.$$eval('.o_kanban_record:not(.o_kanban_ghost)', els => els.map(e => {
        const t = e.querySelector('.o_kanban_card_header_title, .o_kanban_record_title, a.text-primary, .o_primary');
        return (t ? t.textContent : e.textContent).trim().split('\n')[0].trim();
      }));
    },

    // JSON-RPC as the logged-in user: o.rpc('account.journal', 'search_read', [[]], { fields: ['code'] })
    async rpc(model, method, args = [], kwargs = {}) {
      return page.evaluate(async ([model, method, args, kwargs]) => {
        const r = await fetch('/web/dataset/call_kw', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: { model, method, args, kwargs } }) });
        const j = await r.json();
        if (j.error) throw new Error(j.error.data ? j.error.data.message : j.error.message);
        return j.result;
      }, [model, method, args, kwargs]);
    },
    // Run JS inside the page (Odoo's own env is at window.odoo / owl).
    async js(fn, arg) { return page.evaluate(fn, arg); },

    // POS: open a session's UI. Opening a POS can OPEN a new pos.session on the build.
    async pos(configId) {
      await page.goto(`${s.url}/pos/ui?config_id=${configId}`, NAV);
      await page.waitForSelector('.pos, .pos-content, .o_pos_main', { timeout: 180000 }).catch(() => {});
      await o.idle(2000);
    },
    // Run an Odoo web tour already registered in the assets (test tours, onboarding tours).
    async tour(name, timeout = 300000) {
      await page.evaluate(n => odoo.startTour(n, { mode: 'auto' }), name);
      await page.waitForFunction(() => !(window.odoo && odoo.isTourReady === false) &&
        !document.querySelector('.o_tour_pointer'), null, { timeout }).catch(() => {});
      await o.idle(1000);
    },
  };

  try {
    const steps = require(path.resolve(stepsFile));
    await steps(o);
  } catch (e) {
    report.error = String(e && e.stack || e).slice(0, 2000);
    await o.shot('error').catch(() => {});
  }
  fs.writeFileSync(path.join(outdir, 'report.json'), JSON.stringify(report, null, 1));
  await browser.close();
  console.log(JSON.stringify({ notes: report.notes, screenshots: report.screenshots,
    page_errors: report.page_errors, console_errors: report.console_errors.length,
    failed_requests: report.failed_requests, error: report.error }, null, 1));
  process.exit(report.error || report.page_errors.length ? 1 : 0);
})();
