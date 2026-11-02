const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const artifacts = process.env.ARTIFACT_DIR || path.resolve(root, '../../reply-limit-preview');

(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.BROWSER_CHANNEL ? {channel:process.env.BROWSER_CHANNEL} : {})});
  try {
    const page = await browser.newPage({viewport:{width:1050,height:1100}});
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    const defaults = {chat_percent:20,image_percent:100,bilibili_percent:100,forward_percent:100,heybox_percent:100,reply_limit_per_minute:5,at_only_users:[]};
    const fixture = {default_rules:defaults,group_rules:[
      {group_id:'1',group_name:'一群',reply_limit_per_minute:-1,at_only_mode:'单独设置',at_only_users:['123']},
      {group_id:'2',group_name:'二群',reply_limit_per_minute:0,at_only_mode:'继承默认',at_only_users:[]}],
      groups:[{group_id:'1',group_name:'一群'},{group_id:'2',group_name:'二群'},{group_id:'3',group_name:'三群'}],revision:'1',warning:''};
    await page.evaluate(data => {
      window.fixture=data; window.saves=0;
      window.AstrBotPluginPage={apiGet:async()=>structuredClone(window.fixture),apiPost:async(_url,body)=>{
        window.saves++; window.fixture={...window.fixture,...body,revision:String(window.saves+1)};
        return structuredClone(window.fixture);
      }};
    },fixture);
    await page.setContent(fs.readFileSync(path.join(root,'views/回复规则/index.html'),'utf8'));
    await page.waitForFunction(()=>!document.getElementById('target').disabled);
    const save = async () => {await page.click('#save'); await page.waitForFunction(()=>document.getElementById('notice').textContent==='已保存并生效');};
    assert.equal(await page.inputValue('#replyLimit'),'5');
    assert((await page.locator('.reply-window').textContent()).includes('文字、语音和表情各计一条'));
    assert((await page.locator('#preview').textContent()).includes('5 条/分钟'));
    assert(!(await page.locator('.note').textContent()).match(/定时主动聊天|社区精选/));
    await page.fill('#replyLimit','3'); await save();
    await page.selectOption('#target','1');
    assert(await page.locator('#replyLimitInherit').isChecked());
    assert(await page.locator('#replyLimit').isDisabled());
    assert.equal(await page.inputValue('#replyLimit'),'3');
    await page.uncheck('#replyLimitInherit'); await page.fill('#replyLimit','2'); await save();
    let state=await page.evaluate(()=>window.fixture);
    assert.equal(state.default_rules.reply_limit_per_minute,3);
    assert.equal(state.group_rules.find(r=>r.group_id==='1').reply_limit_per_minute,2);
    assert.deepEqual(state.group_rules.find(r=>r.group_id==='1').at_only_users,['123']);
    await page.selectOption('#target','2');
    assert.equal(await page.inputValue('#replyLimit'),'0');
    await page.fill('#replyLimit','10'); await save();
    await page.selectOption('#target','3'); assert(await page.locator('#replyLimit').isDisabled());
    await page.check('#custom'); await page.uncheck('#replyLimitInherit'); await page.fill('#replyLimit','1'); await save();
    state=await page.evaluate(()=>window.fixture);
    assert.equal(state.group_rules.find(r=>r.group_id==='1').reply_limit_per_minute,2);
    assert.equal(state.group_rules.find(r=>r.group_id==='2').reply_limit_per_minute,10);
    await page.selectOption('#target','1'); await page.check('#replyLimitInherit'); await save();
    await page.selectOption('#target','default'); await page.fill('#replyLimit','7'); await save();
    await page.selectOption('#target','1'); assert.equal(await page.inputValue('#replyLimit'),'7');
    await page.selectOption('#target','default'); await page.fill('#replyLimit','0'); await save();
    assert((await page.locator('#preview').textContent()).includes('自动回复上限：不限制'));
    const before=await page.evaluate(()=>window.saves);
    for(const value of ['1.5','601','']){
      await page.fill('#replyLimit',value); await page.click('#save');
      assert((await page.locator('#notice').textContent()).includes('每分钟回复上限须为'));
      assert.equal(await page.evaluate(()=>window.saves),before);
    }
    await page.fill('#replyLimit','5'); await save();
    fs.mkdirSync(artifacts,{recursive:true});
    await page.screenshot({path:path.join(artifacts,'desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:1050});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.screenshot({path:path.join(artifacts,'mobile.png'),fullPage:true});
    assert.deepEqual(errors,[]);
    console.log('UI passed: default/group limits, inheritance, unlimited, independent saves, validation, footer, desktop/mobile layout.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
