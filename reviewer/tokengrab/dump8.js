'use strict'
// 攔 jpgs clientgate/routes 的響應體 + 遊戲全部 /api/ 請求
if (!process.env.https_proxy && !process.env.HTTPS_PROXY) {
  process.env.https_proxy = 'http://127.0.0.1:7897'
}
const path = require('path')
const puppeteer = require('puppeteer-core')

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const PROFILE = path.join(__dirname, 'profile')
const BASE = 'https://game.mahjongsoul.com'
const PAGE = BASE + '/index.html'

;(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    userDataDir: PROFILE,
    args: ['--proxy-server=http://127.0.0.1:7897', '--disable-blink-features=AutomationControlled'],
  })
  const attach = async (page) => {
    try {
      const client = await page.createCDPSession()
      await client.send('Network.enable')
      client.on('Network.responseReceived', async (e) => {
        const u = e.response && e.response.url
        if (!u) return
        if (/api\//.test(u) && !/logstores|aliyuncs/.test(u)) {
          console.log('API-RESP', e.response.status, u)
          try {
            const { body } = await client.send('Network.getResponseBody', { requestId: e.requestId })
            console.log('  BODY:', (body || '').slice(0, 2000))
          } catch (err) {
            console.log('  (no body:', err.message + ')')
          }
        }
      })
    } catch (e) {}
  }
  browser.on('targetcreated', async (t) => { try { const p = await t.page(); if (p) attach(p) } catch (e) {} })
  const page = await browser.newPage()
  await attach(page)
  await page.goto(PAGE, { waitUntil: 'domcontentloaded', timeout: 180000 }).catch(() => {})
  await new Promise(r => setTimeout(r, 40000))
  console.log('SCAN DONE')
  await browser.close()
})().catch((e) => { console.error('FATAL', e); process.exit(1) })