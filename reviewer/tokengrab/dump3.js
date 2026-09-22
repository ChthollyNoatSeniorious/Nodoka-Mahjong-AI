'use strict'
// 用伺服器下發的 liqi 解遊戲登入鏈每幀的完整內容(發送+接收)
if (!process.env.https_proxy && !process.env.HTTPS_PROXY) {
  process.env.https_proxy = 'http://127.0.0.1:7897'
}
const fs = require('fs')
const path = require('path')
const puppeteer = require('puppeteer-core')
const pb = require('protobufjs')
const ServerConfig = require(path.join(__dirname, '..', 'tensoul-main', 'server_config.js'))

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const PROFILE = path.join(__dirname, 'profile')
const BASE = 'https://game.mahjongsoul.com'
const PAGE = BASE + '/index.html'

;(async () => {
  const sc = new ServerConfig({ mjsoul: { base: BASE, timeout: 20000 }, userAgent: 'Mozilla/5.0' })
  let scfg = null
  for (let i = 0; i < 8 && !scfg; i++) {
    try {
      scfg = await sc.getServerConfig(BASE, 20000)
    } catch (e) {
      console.error('server config attempt', i + 1, 'failed:', e.message || e)
      await new Promise(r => setTimeout(r, 3000))
    }
  }
  if (!scfg) throw new Error('could not fetch server config')
  console.error('server version:', scfg.version)
  const root = pb.Root.fromJSON(scfg.liqi)

  function dump(b64, dir) {
    const buf = Buffer.from(b64, 'base64')
    if (!buf.length) return
    let payload = null
    if (buf[0] === 1) payload = buf.slice(1)
    else if (buf[0] === 2) payload = buf.slice(3)
    else if (buf[0] === 3) payload = buf.slice(3)
    else return
    let wr
    try { wr = root.lookupType('Wrapper').decode(payload) } catch (e) { return }
    const name = wr.name || ''
    if (!/oauth2|login|connection|prepare|heartbeat|fetchConnection/i.test(name)) return
    console.log('=== ' + dir + ' ' + name)
    try {
      const svc = root.lookup(name).toJSON()
      const t = root.lookupType(svc.requestType)
      const msg = t.decode(wr.data)
      console.log(JSON.stringify(msg, (k, v) => (typeof v === 'bigint' ? v.toString() : v), 1))
    } catch (e) {
      console.log('(decode failed:', e.message + ')')
    }
  }

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
      client.on('Network.webSocketFrameSent', (e) => {
        const p = e.response && e.response.payloadData
        if (p) dump(p, 'SENT')
      })
      client.on('Network.webSocketFrameReceived', (e) => {
        const p = e.response && e.response.payloadData
        if (p) dump(p, 'RECV')
      })
    } catch (e) {}
  }
  browser.on('targetcreated', async (t) => { try { const p = await t.page(); if (p) attach(p) } catch (e) {} })
  const page = await browser.newPage()
  await attach(page)
  await page.goto(PAGE, { waitUntil: 'domcontentloaded', timeout: 180000 }).catch(() => {})
  await new Promise(r => setTimeout(r, 60000))
  try {
    const ls = await page.evaluate(() => {
      const out = {}
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i)
        const v = localStorage.getItem(k)
        if (/token|uid|account|region|key/i.test(k) && typeof v === 'string') {
          out[k] = v.length > 200 ? v.slice(0, 200) + '...' : v
        }
      }
      return out
    })
    console.log('LOCALSTORAGE:', JSON.stringify(ls, null, 1))
  } catch (e) { console.log('ls read failed:', e.message) }
  console.log('SCAN DONE')
  await browser.close()
})().catch((e) => { console.error('FATAL', e); process.exit(1) })