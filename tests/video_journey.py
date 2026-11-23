#!/usr/bin/env python3
"""Open the video player offline with the sky lesson and use it: start, three pause questions, recall, practice, done, replay,
the loader's invalid input, layouts, reduced motion and the keyboard."""
import json
import re
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'templates' / 'video-player.html'
SKY = ROOT / 'examples' / 'video-lesson-sky.json'
# The player links the Google Fonts stylesheet and falls back to system fonts; that one request is allowed (and blocked).
FONTS = re.compile(r'^https://fonts\.(googleapis|gstatic)\.com/')


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print('PASS:', message)


def variant(lesson):
    html = TEMPLATE.read_text()
    block = re.search(r'(<script type="application/json" id="lesson">)(.*?)(</script>)', html, re.S)
    text = json.dumps(lesson).replace('<', '\\u003c')
    html = html[:block.start(2)] + text + html[block.end(2):]
    path = Path(tempfile.mkdtemp(prefix='video-')) / 'video.html'
    path.write_text(html)
    return path.as_uri()


def open_page(browser, url, width=1280, height=860, scheme='light', reduced_motion='no-preference'):
    context = browser.new_context(viewport={'width': width, 'height': height}, color_scheme=scheme, reduced_motion=reduced_motion)
    outside = []

    def handle(route):
        if route.request.url.startswith('file://'):
            route.continue_()
        else:
            outside.append(route.request.url)
            route.abort()

    context.route('**/*', handle)
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(url)
    return page, errors, outside, context


def state(page):
    return page.evaluate('__video.state')


def reach_pause(page, pause):
    # Seek a little before the pause; seek snaps back to that sentence's start, then the player plays into the pause.
    page.evaluate('t => __video.seek(t)', pause['start'] - 0.3)
    page.wait_for_function('__video.state.pauseOpen !== null', timeout=15000)


with sync_playwright() as p:
    browser = p.chromium.launch()
    sky = json.loads(SKY.read_text())
    url = variant(sky)

    # Start card and the first steps.
    page, errors, outside, _ = open_page(browser, url)
    check(page.is_visible('#go'), 'the start card shows its play button')
    check(page.inner_text('#overlay h2') == sky['question'], 'the start card asks the lesson question')
    check(page.locator('#overlay li').count() == len(sky['objectives']), 'the start card lists the objectives')
    duration = page.evaluate('__video.duration')
    check(duration > 60, f'the timeline has a duration ({duration:.1f} s)')
    page.click('#go')
    check(page.is_hidden('#overlay'), 'play hides the start card')
    page.wait_for_function('__video.state.t > 0.3', timeout=5000)
    check(state(page)['playing'], 'the player advances without a voice')
    tl = page.evaluate('__video.timeline()')
    check(all(i['key'] is None or re.fullmatch(r'[0-9a-f]{8}', i['key']) for i in tl if i['kind'] == 'say'), 'every sentence has an 8-digit clip key')
    check(page.evaluate("__video.fnv('hello') === '4f9f2cab'"), "the player's fnv('hello') matches the checker")

    pz = [i for i in tl if i['kind'] == 'pause']
    check(len(pz) == 3, f'the sky lesson has 3 pause questions ({len(pz)})')
    qs = [b['pause'] for s in sky['scenes'] for b in s['beats'] if 'pause' in b]

    # Pause 1: answer wrong with a number key.
    reach_pause(page, pz[0])
    s = state(page)
    check(s['pauseOpen'] and not s['playing'], 'the video stops at the first pause question')
    check(page.inner_text('#pq') == qs[0]['ask'], 'the pause card shows the question')
    wrong_key = next(i for i, c in enumerate(qs[0]['choices']) if c != qs[0]['answer']) + 1
    page.keyboard.press(str(wrong_key))
    v1 = page.inner_text('#pres .verdict')
    check(page.locator('#pres .verdict.no').count() == 1 and 'Not this time' in v1, 'a wrong key press says it is not right')
    check(qs[0]['answer'] in v1 and qs[0]['why'] in v1, 'the verdict shows the answer and why')
    check(page.locator('.choice.wrong').count() == 1 and page.locator('.choice.right').count() == 1, 'the wrong choice and the right one are marked')
    check(page.locator('.choice:not([disabled])').count() == 0, 'the choices lock after an answer')
    page.click('#pgo')
    s = state(page)
    check(s['playing'] and s['pauseOpen'] is None and page.is_hidden('#overlay'), 'Continue closes the card and plays on')
    check(page.locator('.pdot.done').count() == 1, 'the answered pause is marked done on the track')

    # Pause 2: a multiple-choice question, answered right with the key.
    reach_pause(page, pz[1])
    right_key = qs[1]['choices'].index(qs[1]['answer']) + 1
    page.keyboard.press(str(right_key))
    check(page.locator('#pres .verdict.ok').count() == 1 and page.inner_text('#pres .verdict').startswith('Right.'), 'the right key press says Right')
    page.click('#pgo')

    # Pause 3: a typed question; "I don't know yet, show me".
    reach_pause(page, pz[2])
    check(not qs[2].get('choices') and page.is_visible('#pa'), 'the third pause asks for a typed answer')
    page.click('#pcheck')
    check(state(page)['pauseOpen'] is not None and page.inner_text('#pres') == '', 'Check with an empty answer asks for a guess first')
    page.click("text=I don't know yet, show me")
    v3 = page.inner_text('#pres .verdict')
    check('The answer' in v3 and qs[2]['answer'] in v3 and qs[2]['why'] in v3, 'show me reveals the answer and why')
    page.click('#pgo')
    s = state(page)
    check(len(s['answered']) == 3, 'all three pauses are answered')
    ids = [f'p{si}-{bi}' for si, sc in enumerate(sky['scenes']) for bi, b in enumerate(sc['beats']) if 'pause' in b]
    check([s['results'].get(i) for i in ids] == ['wrong', 'right', 'revealed'], f'results are wrong, right, revealed ({s["results"]})')

    # Recall at the end.
    page.evaluate('d => __video.seek(d - 0.2)', duration)
    page.wait_for_selector('#ra', timeout=15000)
    check(page.inner_text('#overlay h2') == sky['recall']['ask'], 'the recall card opens at the end')
    page.click('#rcheck')
    check(page.inner_text('#rres') == '', 'Compare with an empty recall asks for something first')
    page.fill('#ra', 'Air scatters blue light more than red.')
    page.click('#rcheck')
    rres = page.inner_text('#rres')
    check('Key points' in rres and all(pt in rres for pt in sky['recall']['points']), 'compare shows every key point')
    page.click('#rnext')

    # Practice: the hint shows only the first step; checking shows the answer and steps.
    practice = sky['practice']
    check(page.inner_text('#overlay h2') == practice['ask'], 'the practice card opens')
    page.click('#xhint')
    hint = page.inner_text('#xres')
    check('First step' in hint and practice['steps'][0] in hint and not any(x in hint for x in practice['steps'][1:]) and practice['answer'] not in hint,
          'the hint shows only the first step')
    check(page.locator('#xhint').is_disabled(), 'the hint button locks after one use')
    page.fill('#xa', 'Redder, more blue is scattered.')
    page.click('#xshow')
    ans = page.inner_text('#xres')
    check(practice['answer'] in ans and all(x in ans for x in practice['steps']), 'check my answer shows the answer and every step')
    page.click('#xdone')

    # Done card counts what happened.
    done_text = page.inner_text('#overlay .card')
    line = next((ln for ln in done_text.split('\n') if ln.startswith('You answered')), '')
    check('You answered 3 pause questions: 1 matched the answer, 1 you asked to see' in done_text, f'the done card counts 1 right and 1 shown of 3 ({line})')
    page.click('#again')
    s = state(page)
    check(not s['answered'] and not s['results'] and s['t'] < 1.5 and s['playing'] and page.is_hidden('#overlay'), f'Watch again resets and plays from the start (t {s["t"]:.2f})')
    check(page.locator('.pdot.done').count() == 0, 'Watch again clears the done marks')
    check(not errors, f'no page errors: {errors}')
    not_fonts = [u for u in outside if not FONTS.match(u)]
    check(not not_fonts, f'no outside requests besides the Google Fonts stylesheet: {not_fonts}')

    # Invalid input in the loader, then a good paste.
    empty, empty_errors, _, ctx = open_page(browser, TEMPLATE.as_uri() + '#load')
    check(empty.is_visible('#loader') and empty.is_hidden('#main'), 'an empty player shows the loader')
    empty.fill('#paste', '{\n  "format": "myelinate-video/1",\n  "title": "x"\n  "wpm": 145\n}')
    empty.click('#paste-go')
    err = empty.inner_text('#paste-err')
    check(re.search(r'Line \d+, column \d+', err) and 'not valid JSON' in err, f'broken JSON names a line and column ({err.splitlines()[0] if err else ""})')
    empty.fill('#paste', json.dumps({'format': 'myelinate-video/1', 'scenes': []}))
    empty.click('#paste-go')
    check('no "scenes"' in empty.inner_text('#paste-err'), 'a lesson with no scenes is refused by name')
    empty.fill('#paste', '```json\n' + json.dumps(sky, indent=1) + '\n```')
    empty.click('#paste-go')
    check(empty.is_visible('#main') and empty.is_visible('#go') and empty.evaluate('__video.lesson.title') == sky['title'], 'pasting the sky JSON starts the player')
    check(not empty_errors, f'no page errors in the loader: {empty_errors}')
    ctx.close()

    # Layouts.
    for w, h in ((390, 844), (1280, 860)):
        for scheme in ('light', 'dark'):
            v, v_errors, _, ctx = open_page(browser, url, width=w, height=h, scheme=scheme)
            audit = v.evaluate('__video.audit()')
            check(audit['ok'], f'audit ok at {w}x{h} {scheme}: {audit["problems"]}')
            check(v.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'no sideways scroll at {w}x{h} {scheme}')
            check(not v_errors, f'no page errors at {w}x{h} {scheme}: {v_errors}')
            ctx.close()

    # A table fills row by row, bars grow to their share, and tier badges show. A bar fill once drew at zero width
    # (an inline span ignores width), and no other check could see it.
    rich = json.loads(SKY.read_text())
    beats = rich['scenes'][2]['beats']
    beats[0]['show'] = [{'type': 'table', 'title': 'Colors', 'columns': ['Color', 'Wave'], 'rows': [['Blue', 'short']]}]
    beats[1]['show'] = [{'type': 'row', 'cells': ['Red', 'long']}]
    beats[2]['show'] = [{'type': 'bars', 'title': 'Scattering', 'items': [{'label': 'Blue', 'value': 4}, {'label': 'Red', 'value': 1}]}]
    beats[3]['show'] = [{'type': 'label', 'text': 'Shorter wave, more scattering', 'tier': 'memorize'}]
    # A line is timed as spoken ("0.4225" is five words aloud), or to its recorded clip. Counting written words once
    # left number-heavy lines too short, so the voice ran past the picture.
    def fnv(text):
        h = 0x811c9dc5
        for b in text.encode('utf-8'):
            h = ((h ^ b) * 0x01000193) & 0xffffffff
        return f'{h:08x}'
    opening = rich['scenes'][0]['beats']
    opening[0]['say'] = 'It is 0.4225 of 50,000.'
    rich['audio'] = {'clips': {}, 'seconds': {fnv(opening[1]['say']): 9.87}}
    rp, rp_errors, _, ctx = open_page(browser, variant(rich))
    rtl = rp.evaluate('__video.timeline()')
    said = [i for i in rtl if i['kind'] == 'say']
    check(abs(said[0]['dur'] - (11 * 60 / rich['wpm'] + 0.4)) < 0.02, f'a line with numbers is timed by its 11 spoken words ({said[0]["dur"]:.2f} s)')
    check(abs(said[1]['dur'] - 10.27) < 0.02, f'a recorded clip sets its line\'s time ({said[1]["dur"]:.2f} s for a 9.87 s clip)')
    after = next(i for i in rtl if i['kind'] == 'say' and i['text'] == beats[3]['say'])
    t_end = after['start'] + after['dur'] - 0.05
    board = rp.evaluate("""t => { __video.pause(); __video.renderAt(t);
      const q = s => [...document.querySelectorAll('#board ' + s)];
      return {rows: q('.e-table tbody tr').map(r => r.innerText.replace(/\\s+/g, ' ').trim()),
              fills: q('.e-bars .b-fill').map(f => f.getBoundingClientRect().width),
              tracks: q('.e-bars .b-track').map(f => f.getBoundingClientRect().width),
              tiers: q('.tier.memorize').length}; }""", t_end)
    check(board['rows'] == ['Blue short', 'Red long'], f'a row joins the table above it ({board["rows"]})')
    fills, tracks = board['fills'], board['tracks']
    check(len(fills) == 2 and fills[0] > 0.9 * tracks[0] and 0.15 * tracks[1] < fills[1] < 0.35 * tracks[1],
          f'bars grow to their share of the largest ({[round(f) for f in fills]} of {[round(t) for t in tracks]} px)')
    check(board['tiers'] == 1, 'a memorize badge shows on its label')
    check(not rp_errors, f'no page errors with a table, bars and a tier: {rp_errors}')
    ctx.close()

    # Reduced motion still plays, and elements appear without a fade.
    rm, rm_errors, _, ctx = open_page(browser, url, reduced_motion='reduce')
    check(rm.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches"), 'the reduced motion context is on')
    rm.click('#go')
    rm.wait_for_function('__video.state.t > 0.5', timeout=5000)
    check(state(rm)['playing'], 'reduced motion still plays')
    # 0.17 s into the third sentence its question element has just started to enter (it starts 0.12 s in).
    enter = [i for i in tl if i['kind'] == 'say'][2]['start'] + 0.17
    opacities = """t => { __video.pause(); __video.renderAt(t); return [...document.querySelectorAll('#board .el')].map(n => n.style.opacity); }"""
    op = rm.evaluate(opacities, enter)
    check(len(op) == 2 and all(float(o) == 1 for o in op), f'under reduced motion a new element is fully shown at once ({op})')
    normal, _, _, nctx = open_page(browser, url)
    opn = normal.evaluate(opacities, enter)
    check(len(opn) == 2 and 0 < float(opn[1]) < 1, f'with normal motion the same element is mid-fade ({opn})')
    nctx.close()
    check(not rm_errors, f'no page errors under reduced motion: {rm_errors}')
    ctx.close()

    # Keyboard: Space toggles playing, C toggles captions.
    kb, kb_errors, _, ctx = open_page(browser, url)
    kb.keyboard.press('Space')
    check(state(kb)['playing'] and kb.is_hidden('#overlay'), 'Space on the start card starts playing')
    kb.evaluate('document.activeElement && document.activeElement.blur()')
    kb.keyboard.press('Space')
    check(not state(kb)['playing'], 'Space pauses')
    kb.keyboard.press('Space')
    check(state(kb)['playing'], 'Space plays again')
    check(kb.get_attribute('#cc', 'aria-pressed') == 'true', 'captions start on')
    kb.keyboard.press('c')
    check(kb.get_attribute('#cc', 'aria-pressed') == 'false' and kb.evaluate("document.querySelector('#stage').classList.contains('nocap')"), 'C turns captions off')
    kb.keyboard.press('c')
    check(kb.get_attribute('#cc', 'aria-pressed') == 'true' and kb.is_visible('#cap'), 'C turns captions back on')
    check(not kb_errors, f'no page errors with the keyboard: {kb_errors}')
    ctx.close()

    # Regression (review r1b sol-F1): the hash covers the badge, so a promoted level or label reads as changed.
    sys.path.insert(0, str(ROOT / 'scripts'))
    import video_check as vc
    sky = json.loads(SKY.read_text())
    signed = vc.sign(sky, vc.check(sky)[2]['verification'])
    pg, pg_errors, _, ctx = open_page(browser, variant(signed))
    honest = pg.evaluate('__video.verification')
    check(pg.evaluate('__video.hash()') == signed['verification']['sha256'] and honest['signed'],
          f'the player computes the checker\'s hash and accepts its signed badge ({honest["level"]})')
    ctx.close()
    signed['verification'].update(level='checked', label='Checked against its sources: 11 of 11 claims quoted')
    pg, pg_errors, _, ctx = open_page(browser, variant(signed))
    promoted = pg.evaluate('__video.verification')
    check(not promoted['signed'] and promoted['level'] == 'unverified', f'a badge promoted by hand shows Unverified ({promoted["label"]})')
    check(not pg_errors, f'no page errors on a promoted badge: {pg_errors}')
    ctx.close()

    # Regression (review r2 sol-F1): choices were compared with signs and symbols stripped, so "5" passed for "-5".
    for choices, answer, wrong in ((['-5', '5'], '-5', '5'), (['p < 0.05', 'p > 0.05'], 'p > 0.05', 'p < 0.05')):
        sky = json.loads(SKY.read_text())
        first = next(b['pause'] for s in sky['scenes'] for b in s['beats'] if 'pause' in b)
        first.update(choices=choices, answer=answer)
        pg, pg_errors, _, ctx = open_page(browser, variant(sky))
        pg.click('#go')
        reach_pause(pg, [i for i in pg.evaluate('__video.timeline()') if i['kind'] == 'pause'][0])
        pg.keyboard.press(str(choices.index(wrong) + 1))
        check(pg.locator('#pres .verdict.no').count() == 1, f'choosing {wrong!r} when the answer is {answer!r} is wrong')
        marked = pg.locator('.choice.right span').all_inner_texts()
        check(marked == [answer], f'only {answer!r} is marked right ({marked})')
        ctx.close()

    browser.close()
print('All video journey checks passed.')
