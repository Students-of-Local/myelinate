#!/usr/bin/env python3
"""Browser journey for templates/inline-widgets.html: every view, phone and desktop, light and dark, offline.

usage: python3 tests/inline_journey.py [--shots DIR]
"""
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / 'templates' / 'inline-widgets.html').read_text()
SHOTS = Path(sys.argv[sys.argv.index('--shots') + 1]) if '--shots' in sys.argv else None
if SHOTS:
    SHOTS.mkdir(parents=True, exist_ok=True)

CASES = {
    'practice': {'view': 'practice', 'title': 'Enzyme kinetics', 'ask_confidence': True, 'questions': [
        {'prompt': 'What does a competitive inhibitor do to apparent Km?', 'hints': ['What is it competing for?', 'Can more substrate win?'], 'source': 'Lecture 7, section 7.4'},
        {'prompt': 'Write the Michaelis-Menten equation from memory.'}]},
    'flashcards': {'view': 'flashcards', 'title': 'Wrist bones', 'cards': [
        {'front': 'Which carpal bone is most often fractured?', 'back': 'The scaphoid.', 'source': 'Ch. 8'},
        {'front': 'Which bone sits at the base of the thumb?', 'back': 'The trapezium.'}]},
    'steps': {'view': 'steps', 'title': 'Across a synapse', 'question': 'Why does the signal only go one way?', 'steps': [
        {'text': 'The action potential reaches the terminal.', 'svg': '<svg viewBox="0 0 200 60" onload="window.__pwned=1"><script>window.__pwned=1</script><rect x="10" y="10" width="60" height="40" fill="none" stroke="currentColor" onclick="window.__pwned=1"/><a href="https://evil.test"><text x="80" y="35">terminal</text></a></svg>', 'alt': 'A presynaptic terminal'},
        {'predict': 'What opens next?', 'text': 'Voltage-gated calcium channels open.'}]},
    'graph': {'view': 'graph', 'title': 'Sine wave', 'expression': 'a*sin(b*x)', 'x_range': [0, 6.28], 'y_range': [-3, 3], 'x_label': 'x', 'y_label': 'y', 'parameters': [
        {'name': 'a', 'label': 'amplitude', 'min': 0, 'max': 3, 'value': 1, 'step': 0.1}, {'name': 'b', 'label': 'frequency', 'min': 1, 'max': 5, 'value': 1, 'step': 1}],
        'predict': 'What happens when amplitude doubles?', 'question': 'What stayed the same?'},
    'graph_tiny': {'view': 'graph', 'title': 'Photon energy', 'expression': 'h*x', 'x_range': [0, 1e-19], 'x_label': 'E (J)', 'y_label': 'y', 'parameters': [
        {'name': 'h', 'label': 'scale', 'min': 1, 'max': 3, 'value': 1, 'step': 1}]},
    'video': {'view': 'video', 'status': 'ok', 'id': 'dQw4w9WgXcQ', 'title': 'SN1 vs SN2', 'channel': "Chad's Prep", 'thumbnail': 'https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg', 'watch_url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'start': 30, 'watch_for': 'What decides between the two paths?', 'pause_points': [{'at': 60, 'ask': 'Predict the rate law.'}, {'at': 200, 'ask': 'Which substrate favors SN1?'}], 'recall_prompt': 'What decides SN1 or SN2?'},
    'video_segments': {'view': 'video', 'status': 'ok', 'id': 'dQw4w9WgXcQ', 'title': 'E2 geometry', 'channel': "Chad's Prep", 'watch_url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'watch_for': 'Which hydrogen leaves, and why that one?', 'segments': [{'start': 250, 'end': 570, 'label': 'Anti-periplanar H'}, {'start': 600, 'end': 660, 'label': 'A worked example'}], 'pause_points': [{'at': 610, 'ask': 'Which H leaves?'}], 'recall_prompt': 'Why must the H be anti-periplanar?'},
    'video_end': {'view': 'video', 'status': 'ok', 'id': 'dQw4w9WgXcQ', 'title': 'SN1 in a minute', 'watch_url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'start': 30, 'end': 90},
    'video_blocked': {'view': 'video', 'status': 'blocked', 'id': 'privatevid1', 'watch_url': 'https://www.youtube.com/watch?v=privatevid1', 'note': 'Its owner turned off embedding.'},
    'rtl': {'view': 'flashcards', 'title': 'חוק אוהם', 'cards': [{'front': 'מהו המתח לפי חוק אוהם?', 'back': 'V = IR'}]},
}


def ok(cond, what):
    if not cond:
        raise SystemExit(f'FAIL: {what}')
    print(f'PASS: {what}')


def open_case(browser, case, width=800, scheme='light', can_send=True):
    ctx = browser.new_context(viewport={'width': width, 'height': 900}, color_scheme=scheme)
    page = ctx.new_page()
    errors, requests = [], []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('request', lambda r: requests.append(r.url))
    if can_send:
        page.add_init_script('window.sent = []; window.sendPrompt = t => { window.sent.push(t); };')
    blob = json.dumps(CASES[case], ensure_ascii=False).replace('<', '\\u003c')
    html = re.sub(r'(<script type="application/json" id="data">).*?(</script>)', lambda m: m.group(1) + blob + m.group(2), SRC, count=1, flags=re.S)
    page.route('**/*', lambda route: route.fulfill(content_type='text/html', body=html) if 'stub.test' in route.request.url else route.abort())
    page.goto('https://stub.test/')
    page.wait_for_selector('h1')
    return ctx, page, errors, requests


ok('"answer"' not in SRC.split('<!-- Other shapes')[0].split('id="data"')[1], 'the practice sample holds no answer')
ok(not re.search(r'<script[^>]+src=|\beval\(|new Function', SRC), 'no outside scripts and no eval')

with sync_playwright() as p:
    b = p.chromium.launch()

    ctx, page, errs, _ = open_case(b, 'practice')
    ok(page.locator('.count').inner_text() == 'Question 1 of 2', 'practice shows one question at a time')
    ok(page.get_by_text('From: Lecture 7, section 7.4').count() == 1, 'practice names the source passage')
    ok(page.get_by_role('button', name='Next question').is_disabled(), 'practice needs an answer before moving on')
    page.get_by_role('button', name='Hint', exact=True).click()
    ok(page.locator('.hint').count() == 1, 'first hint appears')
    page.locator('#answer').fill('It raises it')
    page.get_by_role('button', name='Sure', exact=True).click()
    ok(page.locator('#answer').input_value() == 'It raises it', 'an answer survives a redraw')
    page.get_by_role('button', name='Next question').click()
    page.locator('#answer').fill('Vmax[S]/(Km+[S])')
    page.get_by_role('button', name='Review answers').click()
    page.get_by_role('button', name='Send my answers').click()
    page.wait_for_function('window.sent.length === 1')
    msg = page.evaluate('window.sent[0]')
    ok('It raises it' in msg and 'used 1 hint' in msg and 'sure' in msg and 'no hints' in msg, 'sent answers report hints and confidence honestly')
    ok(not errs, f'practice: no page errors {errs}')
    ctx.close()

    ctx, page, errs, _ = open_case(b, 'practice', can_send=False)
    page.locator('#answer').fill('x')
    page.get_by_role('button', name='Next question').click()
    page.locator('#answer').fill('y')
    page.get_by_role('button', name='Review answers').click()
    page.get_by_role('button', name='Send my answers').click()
    page.get_by_label('Text to paste').wait_for(timeout=5000)
    ok('My answer: x' in page.get_by_label('Text to paste').input_value(), 'with no send route, the learner gets text to paste')
    ctx.close()

    ctx, page, errs, _ = open_case(b, 'flashcards')
    ok(page.locator('.back').count() == 0, 'flashcards hide the back before the reveal')
    page.get_by_role('button', name='Show answer').click()
    ok(page.locator('.back').inner_text() == 'The scaphoid.', 'reveal shows the back')
    ok(page.get_by_text('From: Ch. 8').count() == 1, 'cards name their source')
    page.get_by_role('button', name='Again').click()
    ok(page.locator('.count').inner_text() == '0 of 2 cleared', 'Again does not clear a card')
    page.get_by_role('button', name='Show answer').click()
    page.get_by_role('button', name='Good').click()
    page.get_by_role('button', name='Show answer').click()
    ok(page.locator('.back').inner_text() == 'The scaphoid.', 'a missed card comes back')
    page.get_by_role('button', name='Good').click()
    ok('All 2 cleared' in page.locator('.count').inner_text(), 'the session ends when all are cleared')
    page.get_by_role('button', name='Send results').click()
    page.wait_for_function('window.sent.length === 1')
    ok('carpal' in page.evaluate('window.sent[0]'), 'results name the missed card')
    ctx.close()

    ctx, page, errs, _ = open_case(b, 'steps')
    ok(page.locator('.figure svg').count() == 1 and page.locator('.figure svg rect').count() == 1, 'safe drawing parts render')
    ok(page.locator('.figure svg script, .figure svg a').count() == 0 and page.evaluate('window.__pwned') is None, 'scripts, handlers and links are stripped from an SVG')
    ok(page.locator('.figure svg').get_attribute('aria-label') == 'A presynaptic terminal', 'the drawing has alt text')
    page.get_by_role('button', name='Next step').click()
    ok(page.get_by_text('Voltage-gated').count() == 0, 'the next step stays hidden until they predict')
    ok(page.get_by_role('button', name='Show this step').is_disabled(), 'a prediction is required')
    page.locator('#guess').fill('calcium channels')
    page.get_by_role('button', name='Show this step').click()
    ok(page.get_by_text('Voltage-gated').count() == 1, 'the prediction reveals the step')
    page.locator('#final').fill('Receptors are only on one side')
    page.get_by_role('button', name='Send my answer').click()
    page.wait_for_function('window.sent.length === 1')
    ok('calcium channels' in page.evaluate('window.sent[0]'), 'the prediction goes back with the answer')
    ctx.close()

    ctx, page, errs, _ = open_case(b, 'graph')
    ok(page.locator('input[type=range]').first.is_disabled(), 'sliders stay locked until they predict')
    curve = 'svg.plot path[stroke="var(--accent)"]'
    path0 = page.locator(curve).get_attribute('d')
    ok(len(path0) > 500 and path0.count('L') > 100, 'the curve is really drawn')
    page.locator('#predict').fill('taller')
    page.get_by_role('button', name='Lock in and unlock sliders').click()
    page.locator('input[type=range]').first.evaluate("e => { e.value = 2; e.dispatchEvent(new Event('input', {bubbles: true})); }")
    ok(page.locator(curve).get_attribute('d') != path0, 'moving a slider redraws the curve')
    ok(page.locator('svg.plot path[stroke-dasharray]').count() == 1, 'the starting curve stays as a dashed ghost')
    ok('a = 2' in page.locator('svg.plot').get_attribute('aria-label'), 'the graph label reports slider values')
    ctx.close()

    ctx, page, errs, _ = open_case(b, 'graph_tiny')
    page.wait_for_selector('svg.plot', timeout=5000)
    gridlines = page.locator('svg.plot line').count()
    ok(4 <= gridlines <= 30 and not errs, f'a 0 to 1e-19 range draws a handful of gridlines ({gridlines}), not millions')
    ctx.close()

    ctx, page, errs, reqs = open_case(b, 'video')
    ok(page.locator('iframe').count() == 0 and not any('youtube-nocookie' in r for r in reqs), "YouTube's player does not load before play")
    ok(page.get_by_text('Before you press play').count() == 1, 'it says what to watch for')
    ok(page.get_by_role('link', name='Open on YouTube').get_attribute('href').endswith('&t=30s'), 'the outside link keeps the start time')
    page.get_by_role('button', name='Play SN1 vs SN2').click()
    src = page.locator('iframe').get_attribute('src')
    ok(src.startswith('https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?') and 'start=30' in src, 'play loads the privacy-mode player at the start time')
    ok(page.locator('iframe').get_attribute('referrerpolicy') == 'strict-origin-when-cross-origin', 'the player gets a referrer (YouTube error 153 without one)')
    ctx.close()
    # A stand-in player records the commands it gets; the test posts YouTube's infoDelivery from inside it.
    stub_player = '<!doctype html><script>window.got = []; addEventListener("message", e => got.push(JSON.parse(e.data)));</script>'
    tell = "t => parent.postMessage(JSON.stringify({event: 'infoDelivery', id: 1, info: {currentTime: t}}), '*')"
    pauses = "got.filter(c => c.func === 'pauseVideo').length"
    over = 'Segment over. Answer the question below before moving on.'

    def player(page):
        frame = page.locator('iframe').element_handle().content_frame()
        frame.wait_for_function('window.got && got.some(c => c.event === "listening")')
        return frame

    ctx, page, errs, reqs = open_case(b, 'video_segments')
    page.route(re.compile(r'^https://www\.youtube-nocookie\.com/'), lambda route: route.fulfill(content_type='text/html', body=stub_player))
    early = [r for r in reqs if 'youtube' in r or 'ytimg' in r]
    ok(not early and page.locator('iframe, script[src]').count() == 0, f'segments: nothing loads from YouTube before play {early}')
    segs = page.locator('button.seg')
    ok(segs.count() == 2 and segs.first.inner_text().replace('\n', ' ') == '4:10 to 9:30 Anti-periplanar H (about 5 min)', 'a segment button shows its range, label and minutes')
    ok(page.get_by_text('Watch these parts in order, about 6 min in all').count() == 1, 'the segment list gives the total minutes')
    segs.first.click()
    src = page.locator('iframe').get_attribute('src')
    ok('start=250' in src and 'end=570' in src, 'a segment starts the player at its start and ends it at its end')
    frame = player(page)
    frame.evaluate(tell, 400)
    page.wait_for_timeout(300)
    ok(page.get_by_text(over).count() == 0 and frame.evaluate(pauses) == 0, 'mid-segment, nothing stops')
    frame.evaluate(tell, 570)
    page.get_by_text(over).wait_for(timeout=5000)
    frame.evaluate(tell, 575)
    page.wait_for_timeout(300)
    ok(frame.evaluate(pauses) == 1, 'reaching the end pauses once and shows the note')
    segs.nth(1).click()
    frame.wait_for_function("got.some(c => c.func === 'loadVideoById')")
    ok(frame.evaluate("got.find(c => c.func === 'loadVideoById').args[0]") == {'videoId': 'dQw4w9WgXcQ', 'startSeconds': 600, 'endSeconds': 660} and page.get_by_text(over).count() == 0, 'the next segment loads at its own range and clears the note')
    frame.evaluate(tell, 630)
    frame.evaluate(tell, 660)
    page.get_by_text(over).wait_for(timeout=5000)
    segs.first.click()
    frame.evaluate(tell, 660)  # a stale report from the segment that just ended
    page.wait_for_timeout(300)
    ok(page.get_by_text(over).count() == 0 and frame.evaluate(pauses) == 2, 'a stale time from the last segment does not stop the new one')
    frame.evaluate(tell, 300)
    frame.evaluate(tell, 570)
    page.get_by_text(over).wait_for(timeout=5000)
    ok(frame.evaluate(pauses) == 3, 'the new segment still stops at its own end')
    ok(not errs, f'segments: no page errors {errs}')
    ctx.close()

    ctx, page, errs, reqs = open_case(b, 'video_segments')
    page.route(re.compile(r'^https://www\.youtube-nocookie\.com/'), lambda route: route.fulfill(content_type='text/html', body=stub_player))
    page.get_by_role('button', name='Play E2 geometry').click()
    src = page.locator('iframe').get_attribute('src')
    ok('start=250' in src and 'end=570' in src and 'on' in (page.locator('button.seg').first.get_attribute('class') or ''), 'Play starts the first segment and marks it')
    ctx.close()

    # Played with its first report already at the end (video_end below) or jumped into from a pause point,
    # a range still stops at its end.
    ctx, page, errs, reqs = open_case(b, 'video_segments')
    page.route(re.compile(r'^https://www\.youtube-nocookie\.com/'), lambda route: route.fulfill(content_type='text/html', body=stub_player))
    page.locator('button.pause:not(.seg)').first.click()
    src = page.locator('iframe').get_attribute('src')
    ok('start=610' in src and 'end=660' in src, 'a pause point inside a segment keeps that segment\'s end')
    frame = player(page)
    frame.evaluate(tell, 660)
    page.get_by_text(over).wait_for(timeout=5000)
    ctx.close()

    ctx, page, errs, reqs = open_case(b, 'video_end')
    page.route(re.compile(r'^https://www\.youtube-nocookie\.com/'), lambda route: route.fulfill(content_type='text/html', body=stub_player))
    ok(not [r for r in reqs if 'youtube' in r or 'ytimg' in r], 'end: nothing loads from YouTube before play')
    page.get_by_role('button', name='Play SN1 in a minute').click()
    src = page.locator('iframe').get_attribute('src')
    ok('start=30' in src and 'end=90' in src, 'a plain end goes to the player')
    frame = player(page)
    frame.evaluate(tell, 90)
    page.get_by_text(over).wait_for(timeout=5000)
    frame.evaluate(tell, 91)
    page.wait_for_timeout(300)
    ok(frame.evaluate(pauses) == 1, 'a plain end stops playback once and shows the note')
    ctx.close()

    ctx, page, errs, reqs = open_case(b, 'video_blocked')
    ok(page.locator('iframe, .video-frame').count() == 0 and page.get_by_role('link', name='Open on YouTube').count() == 1, 'a video that blocks embedding gets a link, not a dead player')
    ctx.close()

    ctx, page, errs, _ = open_case(b, 'rtl', width=390)
    ok(page.evaluate("getComputedStyle(document.querySelector('.prompt')).direction") == 'rtl', 'Hebrew text runs right to left')
    ctx.close()

    for case in CASES:
        for width, scheme in ((390, 'light'), (390, 'dark'), (800, 'light'), (800, 'dark')):
            ctx, page, errs, _ = open_case(b, case, width, scheme)
            ok(page.evaluate('document.documentElement.scrollWidth - document.documentElement.clientWidth') <= 0, f'{case} {width} {scheme}: no sideways scroll')
            ok(page.evaluate("[...document.querySelectorAll('button')].filter(b => b.offsetParent && b.getBoundingClientRect().height < 40).length") == 0, f'{case} {width} {scheme}: buttons are tap sized')
            color = page.evaluate("getComputedStyle(document.querySelector('h1')).color")
            ok((scheme == 'dark') == (color == 'rgb(236, 230, 216)'), f'{case} {width} {scheme}: theme follows the system')
            ok(not errs, f'{case} {width} {scheme}: no page errors {errs}')
            if SHOTS:
                page.screenshot(path=str(SHOTS / f'{case}-{width}-{scheme}.png'), full_page=True)
            ctx.close()
    b.close()
print('All inline widget checks passed.')
