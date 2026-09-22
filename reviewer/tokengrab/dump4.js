'use strict'
// 攔遊戲 WS 握手請求頭 + 解登入流程的接收幀
if (!process.env.https_proxy && !process.env.HTTPS_PROXY) {
  process.env.https_proxy = 'http://127.0.0.1:7897'
}
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
    try { scfg = await sc.getServerConfig(BASE, 20000) }
    catch (e) { console.error('cfg attempt', i + 1, 'failed:', e.message); await new Promise(r => setTimeout(r, 2500)) }
  }
  if (!scfg) throw new Error('no server config')
  console.error('server version:', scfg.version)
  const root = pb.Root.fromJSON(scfg.liqi)

  let recvSeen = 0
  function dump(b64, dir) {
    const buf = Buffer.from(b64, 'base64')
    if (!buf.length) return
    let payload = null
    if (buf[0] === 1) payload = buf.slice(1)
    else if (buf[0] === 2) payload = buf.slice(3)
    else if (buf[0] === 3) payload = buf.slice(3)
    else {
      if (dir === 'RECV' && recvSeen < 6) {
        recvSeen++
        console.log('RECV-ODD first=', buf[0], 'len=', buf.length, 'hex=', buf.toString('hex').slice(0, 80))
      }
      return
    }
    let wr
    try { wr = root.lookupType('Wrapper').decode(payload) } catch (e) {
      if (dir === 'RECV' && recvSeen < 6) {
        recvSeen++
        console.log('RECV-UNDECODABLE first=', buf[0], 'len=', buf.length, 'hex=', buf.toString('hex').slice(0, 80))
      }
      return
    }
    const name = wr.name || ''
    if (!/oauth2|login|connection|heartbeat|prepare/i.test(name)) return
    console.log('=== ' + dir + ' ' + name)
    try {
      const svc = root.lookup(name).toJSON()
      const t = root.lookupType(svc.requestType)
      const msg = t.decode(wr.data)
      console.log(JSON.stringify(msg, (k, v) => (typeof v === 'bigint' ? v.toString() : v), 1))
    } catch (e) {
      // 響應幀的 name 可能是響應類型名(如 ResOauth2Auth),嘗試直接 lookupType
      try {
        const t = root.lookupType(name)
        const msg = t.decode(wr.data)
        console.log(JSON.stringify(msg, (k, v) => (typeof v === 'bigint' ? v.toString() : v), 1))
      } catch (e2) {
        console.log('(decode failed:', e.message, '/', e2.message + ')')
      }
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
      client.on('Network.webSocketWillSendHandshakeRequest', (e) => {
        console.log('WS-HANDSHAKE-REQUEST url=', e.request.url)
        console.log('WS-HANDSHAKE-REQUEST headers=', JSON.stringify(e.request.headers, null, 1))
      })
      client.on('Network.webSocketHandshakeResponseReceived', (e) => {
        console.log('WS-HANDSHAKE-RESPONSE status=', e.response.status, 'headers=', JSON.stringify(e.response.headers, null, 1))
      })
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
  await new Promise(r => setTimeout(r, 50000))
  console.log('SCAN DONE')
  await browser.close()
})().catch((e) => { console.error('FATAL', e); process.exit(1) })