'use strict'
// 自動登入雀魂日服並攔截登入響應中的 access_token
// 用法: node grab_token.js
// 會彈出一個 Chrome 窗口(無痕、未登入),自動填帳密登入;
// 若出現驗證碼/人機驗證,請在窗口裡手動完成,攔截會繼續。
const fs = require('fs')
const path = require('path')
const puppeteer = require('puppeteer-core')

// 帳密從環境變數讀取(請勿把真實帳密提交進 repo):
//   $env:MJS_EMAIL / $env:MJS_PASSWORD
const EMAIL = process.env.MJS_EMAIL || 'your_email@example.com'
const PASSWORD = process.env.MJS_PASSWORD || ''
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const BASE = 'https://game.mahjongsoul.com/index.html'
const OUT = path.join(__dirname, 'token.txt')

const sleep = ms => new Promise(r => setTimeout(r, ms))

async function fillAndSubmit(page) {
  for (const frame of page.frames()) {
    try {
      const inputs = await frame.$$('input')
      if (!inputs.length) continue
      let emailBox = null, passBox = null
      for (const el of inputs) {
        const t = await el.evaluate(e => ({
          type: e.type || '', name: e.name || '', id: e.id || '',
          ph: e.placeholder || '', visible: !!(e.offsetWidth || e.offsetHeight),
        }))
        if (!t.visible) continue
        if (t.type === 'password') passBox = el
        else if (t.type === 'email') emailBox = el
        else if (/mail|account|ユーザ|帳號|账号|id/i.test(t.name + t.id + t.ph)) emailBox = el
        else if (/pass/i.test(t.name + t.id + t.ph)) passBox = el
      }
      if (!emailBox || !passBox) continue
      console.log('FOUND LOGIN FORM in frame:', frame.url())
      await emailBox.click({ clickCount: 3 }).catch(() => {})
      await emailBox.type(EMAIL, { delay: 12 }).catch(() => {})
      await passBox.click({ clickCount: 3 }).catch(() => {})
      await passBox.type(PASSWORD, { delay: 12 }).catch(() => {})
      const btns = await frame.$$('button, input[type=submit], [role=button]')
      let submitted = false
      for (const b of btns) {
        const txt = await b.evaluate(e => (e.innerText || e.value || '').trim()).catch(() => '')
        if (/ログイン|ログ イン|LOGIN|登录|登 录|登入|Sign in|SIGN IN|サインイン/i.test(txt)) {
          await b.click().catch(() => {})
          submitted = true
          console.log('CLICKED SUBMIT:', txt)
          break
        }
      }
      if (!submitted) {
        await passBox.press('Enter').catch(() => {})
        console.log('PRESSED ENTER')
      }
      return true
    } catch (e) {
      console.log('frame scan err:', e.message)
    }
  }
  return false
}

;(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: false,
    args: ['--proxy-server=http://127.0.0.1:7897', '--disable-blink-features=AutomationControlled'],
  })

  let finalToken = null
  const hits = []

  const onResp = async resp => {
    try {
      const url = resp.url()
      const body = await resp.text()
      if (!body || !body.includes('access_token')) return
      console.log('HIT>>>', url)
      console.log('BODY>>>', body.slice(0, 2500))
      hits.push({ url, body })
      try {
        const j = JSON.parse(body)
        const tok = j.access_token || (j.data && j.data.access_token) || (j.result && j.result.access_token)
        if (typeof tok === 'string' && tok.length > 20) {
          finalToken = tok
          fs.writeFileSync(OUT, tok + '\n')
          console.log('FINAL_TOKEN>>>', tok)
        }
      } catch (e) { /* not JSON */ }
    } catch (e) { /* body read failed */ }
  }

  browser.on('targetcreated', async target => {
    try {
      const p = await target.page()
      if (p) {
        p.on('response', onResp)
        p.on('console', m => console.log('[page]', m.text()))
      }
    } catch (e) { /* ignore */ }
  })

  const page = await browser.newPage()
  page.on('response', onResp)
  page.on('console', m => console.log('[page]', m.text()))

  console.log('goto', BASE)
  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 90000 }).catch(e => console.log('goto warn:', e.message))
  await sleep(20000)
  console.log('url now:', page.url())

  const deadline = Date.now() + 8 * 60 * 1000
  let didFill = false
  while (Date.now() < deadline && !finalToken) {
    if (!didFill) {
      for (const p of await browser.pages()) {
        if (await fillAndSubmit(p)) { didFill = true; break }
      }
    }
    await sleep(2000)
  }

  console.log('DONE. finalToken:', finalToken ? 'YES (' + finalToken.length + ' chars)' : 'NO')
  console.log('hits:', hits.length)
  await browser.close()
})().catch(e => { console.error('FATAL', e); process.exit(1) })