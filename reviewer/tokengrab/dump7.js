'use strict'
// 攔遊戲對 jpgs 域的所有流量:WS URL(query?)、HTTP 請求、請求頭
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
      client.on('Network.webSocketCreated', (e) => {
        if (/jpgs|mjgs|gateway/i.test(e.url)) console.log('WS-CREATED', e.url)
      })
      client.on('Network.webSocketWillSendHandshakeRequest', (e) => {
        const u = e.request && e.request.url
        if (u && /jpgs|gateway/i.test(u)) {
          console.log('WS-REQ url=', u)
          console.log('WS-REQ headers=', JSON.stringify(e.request.headers))
        }
      })
      client.on('Network.requestWillBeSent', (e) => {
        const u = e.request && e.request.url
        if (u && /jpgs\.|gateway/i.test(u)) {
          console.log('HTTP-REQ', e.request.method, u)
          const h = e.request.headers || {}
          const interesting = {}
          for (const k of Object.keys(h)) {
            if (/token|version|auth|client|key|sig|param|random|device/i.test(k)) interesting[k] = h[k]
          }
          if (Object.keys(interesting).length) console.log('  HEADERS:', JSON.stringify(interesting))
          if (e.request.postData) console.log('  POST:', e.request.postData.slice(0, 300))
        }
      })
    } catch (e) {}
  }
  browser.on('targetcreated', async (t) => { try { const p = await t.page(); if (p) attach(p) } catch (e) {} })
  const page = await browser.newPage()
  await attach(page)
  await page.goto(PAGE, { waitUntil: 'domcontentloaded', timeout: 180000 }).catch(() => {})
  await new Promise(r => setTimeout(r, 45000))
  console.log('SCAN DONE')
  await browser.close()
})().catch((e) => { console.error('FATAL', e); process.exit(1) })