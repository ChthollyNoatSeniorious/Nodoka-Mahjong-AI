'use strict'
// 用 CDP 攔截 WebSocket 幀,解出 oauth2Login 請求裡的 access_token
// 前提: profile/ 目錄裡有已登入的 Chrome profile(自動重登,無需人工)
const fs = require('fs')
const path = require('path')
const puppeteer = require('puppeteer-core')
const pb = require('protobufjs')

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const PROFILE = path.join(__dirname, 'profile')
const BASE = 'https://game.mahjongsoul.com/index.html'
const OUT = path.join(__dirname, 'token.txt')
const LIQI = path.join(__dirname, '..', 'tensoul-main', 'node_modules', 'mjsoul', 'liqi.json')

let root = null
try {
  root = pb.Root.fromJSON(JSON.parse(fs.readFileSync(LIQI, 'utf8')))
} catch (e) {
  console.log('liqi load failed:', e.message)
}

function tryDecode(b64, url) {
  const buf = Buffer.from(b64, 'base64')
  if (!buf.length || buf[0] !== 2) return null
  let wr = null
  if (root) {
    try { wr = root.lookupType('Wrapper').decode(buf.slice(3)) } catch (e) { wr = null }
  }
  if (!wr) {
    // no proto: raw scan for token-shaped substrings
    const s = buf.toString('utf8')
    const m = s.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g)
    if (m) { console.log('RAW-TOKEN-CANDIDATE from', url, ':', m) }
    return null
  }
  const name = wr.name || ''
  console.log('REQ-FRAME>', url, name)
  if (!/oauth2/i.test(name) && !/login/i.test(name)) return null
  try {
    const svc = root.lookup(name).toJSON()
    const reqType = root.lookupType(svc.requestType)
    const msg = reqType.decode(wr.data)
    const keys = Object.keys(msg)
    console.log('LOGIN-MSG keys:', JSON.stringify(keys))
    for (const k of keys) {
      const v = msg[k]
      if (typeof v === 'string' && v.length > 20) console.log('LOGIN-MSG', k, '=', v)
    }
    const tok =
      msg.access_token ||
      (msg.account && (msg.account.access_token || msg.account.token)) ||
      (msg.data && msg.data.access_token)
    return typeof tok === 'string' && tok.length > 10 ? tok : null
  } catch (e) {
    console.log('decode err:', e.message)
    return null
  }
}

;(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    userDataDir: PROFILE,
    args: ['--proxy-server=http://127.0.0.1:7897', '--disable-blink-features=AutomationControlled'],
  })
  let found = false
  let firstUrl = null

  const attach = async (page) => {
    try {
      const client = await page.createCDPSession()
      await client.send('Network.enable')
      client.on('Network.webSocketCreated', (e) => { if (!firstUrl) firstUrl = e.url })
      client.on('Network.webSocketFrameSent', (e) => {
        const p = e.response && e.response.payloadData
        if (!p) return
        const tok = tryDecode(p, (e.response.opcode === 2 ? 'bin' : 'txt') + ' ' + (firstUrl || ''))
        if (tok) {
          found = true
          fs.writeFileSync(OUT, tok + '\n')
          console.log('FINAL_TOKEN>>>', tok)
        }
      })
    } catch (e) { console.log('attach err:', e.message) }
  }

  browser.on('targetcreated', async (t) => {
    try { const p = await t.page(); if (p) attach(p) } catch (e) {}
  })

  const page = await browser.newPage()
  await attach(page)
  console.log('goto', BASE)
  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 180000 }).catch(e => console.log('goto warn:', e.message))

  const deadline = Date.now() + 7 * 60 * 1000
  while (Date.now() < deadline && !found) {
    await new Promise(r => setTimeout(r, 4000))
  }
  console.log('DONE found=', found)
  await browser.close()
})().catch(e => { console.error('FATAL', e); process.exit(1) })