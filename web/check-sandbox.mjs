import { chromium } from '@playwright/test'
import { mkdirSync } from 'node:fs'
mkdirSync('verification', { recursive: true })
const browser = await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true,args:['--enable-unsafe-swiftshader']})
const page=await browser.newPage()
const errors=[];page.on('pageerror',e=>errors.push(e.message))
for(const [name,width,height] of [['desktop',1440,960],['mobile',390,844]]){
  await page.setViewportSize({width,height})
  await page.goto('http://127.0.0.1:8766/static/web/index.html')
  await page.locator('canvas').waitFor();await page.waitForTimeout(2000)
  const initial=await page.locator('canvas').evaluate(c=>c.toDataURL())
  if(initial.length<10000)throw Error('Blank canvas')
  await page.getByRole('button',{name:'演示 PM → 架构师'}).click()
  await page.waitForTimeout(2500)
  const moving=await page.locator('canvas').evaluate(c=>c.toDataURL())
  if(initial===moving)throw Error('No movement')
  await page.screenshot({path:`verification/${name}.png`,fullPage:true})
  await page.getByRole('button',{name:'结束演示'}).click()
  await page.getByRole('button',{name:/测试工程师/}).click()
  if(await page.locator('.detail h2').innerText()!=='测试工程师')throw Error('Selection failed')
  console.log(name,'canvas renders, movement and selection passed')
}
await browser.close();if(errors.length)throw Error(errors.join('\n'))
