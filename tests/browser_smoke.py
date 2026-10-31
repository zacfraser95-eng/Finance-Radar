from pathlib import Path
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parents[1]
server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=str(root)))
Thread(target=server.serve_forever,daemon=True).start()
try:
    with sync_playwright() as play:
        browser=play.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1420,'height':930})
        errors=[]
        page.on('pageerror',lambda err:errors.append(str(err)))
        page.set_content((root/'index.html').read_text().replace('<script src="./data/live.js"></script>',''),wait_until='load')
        assert 'RADAR' in page.title()
        assert page.locator('.event').count()>=3
        assert page.locator('#topstatus').inner_text().lower()=='reviewed snapshot'
        page.locator('.event [data-open]').first.click()
        assert 'show' in page.locator('#modal').get_attribute('class')
        page.locator('#closemodal').click()
        page.locator('.event [data-save]').first.click()
        assert page.locator('#savedcount').inner_text().startswith('1 saved')
        page.locator('[data-page="calendar"]').click()
        assert page.locator('.calday').count()>28
        page.locator('[data-page="discover"]').click()
        page.locator('[data-filter="investment"]').click()
        assert page.locator('.event').count()>=1
        page.locator('[data-filter="all"]').click()
        page.screenshot(path=str(root.parent/'finance-radar-deploy-desktop.png'),full_page=True)
        mobile=browser.new_page(viewport={'width':390,'height':844},device_scale_factor=1)
        mobile.on('pageerror',lambda err:errors.append(str(err)))
        mobile.set_content((root/'index.html').read_text().replace('<script src="./data/live.js"></script>',''),wait_until='load')
        assert mobile.evaluate('document.documentElement.scrollWidth')<=mobile.evaluate('window.innerWidth')
        mobile.screenshot(path=str(root.parent/'finance-radar-deploy-mobile.png'),full_page=True)
        assert not errors,errors
        print('Browser test passed. Initial events:',page.locator('.event').count(),'JS errors:',len(errors),'mobile width:',mobile.evaluate('window.innerWidth'))
        browser.close()
finally:
    server.shutdown()
