'use strict'
// dump 所有 WS 幀名(REQ/RECV),超長掃描 240s
const fs = require('fs')
const path = require('path')
const puppeteer = require('puppeteer-core')
const pb = require('protobufjs')

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const PROFILE = path.join(__dirname, 'profile')
const BASE = 'https://game.mahjongsoul.com/index.html'
const LIQI = path.join(__dirname, '..', 'tensoul-main', 'node_modules', 'mjsoul', 'liqi.json')
const root = pb.Root.fromJSON(JSON.parse(fs.readFileSync(LIQI, 'utf8')))

let frameCount = 0
function dump(b64, dir) {
  const buf = Buffer.from(b64, 'base64')
  if (!buf.length) return
  frameCount++
  let payload = null
  if (buf[0] === 1) payload = buf.slice(1)
  else if (buf[0] === 2) payload = buf.slice(3)
  else if (buf[0] === 3) payload = buf.slice(3)
  else return
  let wr
  try { wr = root.lookupType('Wrapper').decode(payload) } catch (e) {
    console.log('#', dir, 'undecodable', buf.toString('hex').slice(0, 120))
    return
  }
  const name = wr.name || '(no name)'
  console.log('#', dir, name)
  if (!/oauth2|login|connection/i.test(name)) return
  console.log('=== ' + dir + ' ' + name)
  try {
    const t = root.lookupType(name)
    const msg = t.decode(wr.data)
    console.log(JSON.stringify(msg, (k, v) => typeof v === 'bigint' ? v.toString() : v, 1))
  } catch (e) {
    console.log('(decode failed:', e.message + ')')
  }
}

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
      client.on('Network.webSocketCreated', (e) => console.log('WS-CREATED', e.url))
      client.on('Network.webSocketFrameSent', (e) => {
        const p = e.response && e.response.payloadData
        if (p) dump(p, 'SENT')
      })
      client.on('Network.webSocketFrameReceived', (e) => {
        const p = e.response && e.response.payloadData
        if (p) dump(p, 'RECV')
      })
    } catch (e) { console.log('attach err:', e.message) }
  }
  browser.on('targetcreated', async (t) => { try { const p = await t.page(); if (p) attach(p) } catch (e) {} })
  const page = await browser.newPage()
  await attach(page)
  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 180000 }).catch(e => console.log('goto warn:', e.message))
  for (let i = 0; i < 8; i++) {
    await new Promise(r => setTimeout(r, 30000))
    console.log('T+', (i + 1) * 30, 's frames:', frameCount)
  }
  console.log('SCAN DONE frames=', frameCount)
  await browser.close()
})().catch(e => { console.error('FATAL', e); process.exit(1) })