#!/usr/bin/env python3
"""Check a Myelinate video lesson file and print the fixes it needs, in order.

    python3 scripts/video_check.py lesson.json                    # check; exit 1 until clean
    python3 scripts/video_check.py lesson.json --sources notes/   # also find every quote in the learner's files
    python3 scripts/video_check.py lesson.json --final            # also require every claim checked
    python3 scripts/video_check.py lesson.json --build video.html # check, then write the player with the lesson inside
    python3 scripts/video_check.py lesson.json --audio-plan       # list the narration lines and the clip name for each

It checks structure, sources and teaching rules. It cannot tell whether a fact is true:
that is the claim check in the skill's step 6.
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path

FORMAT = 'myelinate-video/1'
ROLES = ('intro', 'names', 'explain', 'example', 'worked', 'faded', 'misconception', 'summary')
SHOW_TYPES = ('title', 'question', 'term', 'label', 'equation', 'step', 'arrow', 'highlight', 'graph',
              'image', 'compare', 'quote')
WPM_MIN, WPM_MAX = 130, 160
SENTENCE_MAX, SENTENCE_WARN = 30, 22
SCENE_MAX_SECONDS = 360
PAUSE_GAP_MAX, PAUSE_GAP_WARN = 120, 90
SCREEN_WORDS_MAX, SCREEN_WORDS_WARN = 40, 30
BEAT_GAP = 0.4  # seconds of silence after each sentence, same as the player
TEMPLATE = Path(__file__).resolve().parent.parent / 'templates' / 'video-player.html'
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
# Words limits for things on screen: the narration carries the sentence, the screen carries a few key words.
LIMITS = {'title.text': 8, 'title.sub': 10, 'question.text': 16, 'term.word': 4, 'term.meaning': 10,
          'label.text': 8, 'step.text': 10, 'arrow.from': 4, 'arrow.to': 4, 'arrow.label': 4,
          'compare.left': 5, 'compare.right': 5, 'compare.item': 6, 'graph.title': 8, 'quote.text': 30}


def fnv1a(text):
    """Clip name for a narration line: FNV-1a 32-bit of its UTF-8 bytes, 8 hex digits. The player uses the same."""
    h = 0x811c9dc5
    for b in text.encode('utf-8'):
        h ^= b
        h = (h * 0x01000193) & 0xffffffff
    return f'{h:08x}'


def words(text):
    return len(str(text).split())


def norm(text):
    text = str(text).lower().replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', text).split())


HOLD_MAX = 30


def hold_of(beat):
    """Extra seconds after a sentence: a number from 0 to HOLD_MAX, or None when it is not one."""
    h = beat.get('hold', 0)
    if h is None:
        return 0.0
    if isinstance(h, bool) or not isinstance(h, (int, float)) or not 0 <= h <= HOLD_MAX:
        return None
    return float(h)


def beat_seconds(beat, wpm):
    if 'say' in beat and isinstance(beat['say'], str):
        return words(beat['say']) * 60.0 / wpm + BEAT_GAP + (hold_of(beat) or 0.0)
    return 0.0


def element_texts(el):
    """Every string an element puts on screen, with its limit key."""
    t = el.get('type')
    out = []
    if t == 'compare':
        out += [('compare.left', el.get('left', '')), ('compare.right', el.get('right', ''))]
        out += [('compare.item', s) for s in (el.get('leftItems') or []) + (el.get('rightItems') or [])]
    elif t == 'graph':
        out += [('graph.title', el.get('title', '')), ('graph.axis', el.get('x', '')), ('graph.axis', el.get('y', ''))]
        if isinstance(el.get('mark'), dict):
            out.append(('graph.axis', el['mark'].get('label', '')))
    elif t == 'image':
        out.append(('image.credit', el.get('credit', '')))
    elif t == 'highlight':
        pass
    else:
        for field in ('text', 'sub', 'word', 'meaning', 'from', 'to', 'label'):
            if field in el:
                out.append((f'{t}.{field}', el[field]))
    return [(k, v) for k, v in out if isinstance(v, str) and v.strip()]


def load_sources(paths):
    """Text of each source file, keyed by file name. HTML is reduced to its text."""
    found = {}
    for raw in paths or []:
        p = Path(raw)
        files = sorted(x for x in p.rglob('*') if x.is_file()) if p.is_dir() else [p]
        for f in files:
            if f.suffix.lower() not in ('.txt', '.md', '.html', '.htm', '.csv', '.json'):
                continue
            text = f.read_text(errors='replace')
            if f.suffix.lower() in ('.html', '.htm'):
                text = re.sub(r'(?is)<(script|style)\b.*?</\1>', ' ', text)
                text = html.unescape(re.sub(r'<[^>]+>', ' ', text))
            found[f.name] = norm(text)
    return found


class Report:
    def __init__(self):
        self.errors, self.warnings = [], []

    def error(self, where, problem, fix):
        self.errors.append((where, problem, fix))

    def warn(self, where, problem, fix):
        self.warnings.append((where, problem, fix))


def check(lesson, sources=None, final=False):
    """Return (errors, warnings, summary). Each error and warning is (where, problem, fix)."""
    r = Report()
    if not isinstance(lesson, dict):
        r.error('The file', 'is not one JSON object.', 'Start the file with { and end it with }, like templates/video-lesson.json.')
        return r.errors, r.warnings, {}
    left = sorted({m for m in re.findall(r'<<(.*?)>>', json.dumps(lesson, ensure_ascii=False))})
    if left:
        r.error('The file', f'still has {len(left)} blank(s) from the template, such as <<{left[0][:60]}>>.',
                'Replace every <<...>> with real content, or delete that line or item.')
    if lesson.get('format') != FORMAT:
        r.error('"format"', 'is missing or wrong.', f'Set "format": "{FORMAT}".')
    for key in ('title', 'question'):
        if not str(lesson.get(key, '')).strip():
            r.error(f'"{key}"', 'is empty.', 'Write it. "question" is the one question the whole video answers.' if key == 'question' else 'Write a short title.')
    if words(lesson.get('title', '')) > 8:
        r.error('"title"', f'has {words(lesson["title"])} words.', 'Use 8 words or fewer.')
    obj = lesson.get('objectives')
    if not isinstance(obj, list) or not 1 <= len([o for o in obj if str(o).strip()]) <= 3:
        r.error('"objectives"', 'must list 1 to 3 goals.', 'Write 1 to 3 short goals, each starting with a verb such as Explain, Solve or Compare.')
    kind = lesson.get('lessonType')
    if kind not in ('concept', 'problem'):
        r.error('"lessonType"', 'is missing.', 'Set "lessonType": "problem" if the learner must solve problems with steps; otherwise "concept".')
    wpm = lesson.get('wpm')
    if not isinstance(wpm, (int, float)) or not WPM_MIN <= wpm <= WPM_MAX:
        r.error('"wpm"', f'is {wpm!r}.', f'Set "wpm" to a number from {WPM_MIN} to {WPM_MAX}. Use 145 if unsure.')
        wpm = 145

    # Who it is for, and what it was checked against.
    learner = lesson.get('learner') if isinstance(lesson.get('learner'), dict) else {}
    if not learner:
        r.error('"learner"', 'is missing.', 'Copy the "learner" block from templates/video-lesson.json and fill it in.')
    lk = learner.get('kind')
    materials = learner.get('materials') if isinstance(learner.get('materials'), list) else None
    if lk == 'course':
        if not str(learner.get('course', '')).strip():
            r.error('learner.course', 'is empty.', 'Write the course name, for example "BIO 110, Dr. Lee".')
        if materials is None:
            r.error('learner.materials', 'is missing.', 'List what the learner gave you (notes, slides, study guide, textbook and edition). Use [] if they gave nothing yet.')
        if learner.get('checked') not in ('not-yet', 'yes'):
            r.error('learner.checked', 'must be "not-yet" or "yes".', 'Use "not-yet" until every course claim was matched to the learner\'s own materials.')
        elif learner.get('checked') == 'yes':
            if not materials:
                r.error('learner.checked', 'says "yes" but no materials are listed.', 'Set "checked": "not-yet". The video will say it is not yet checked against the course.')
            course_claims = [c for c in lesson.get('claims') or [] if isinstance(c, dict) and c.get('from') == 'course']
            if not course_claims:
                r.error('learner.checked', 'says "yes" but no claim comes from the course.', 'Set "checked": "not-yet", or source the claims from the learner\'s materials.')
            if any(c.get('status') not in ('matched', 'conflict') for c in course_claims):
                r.error('learner.checked', 'says "yes" but some course claims are not checked.', 'Finish step 6 for every claim, or set "checked": "not-yet".')
    elif lk == 'self-study':
        for key in ('purpose', 'level'):
            if not str(learner.get(key, '')).strip():
                r.error(f'learner.{key}', 'is empty.', 'Ask the learner, or write what they told you.' if key == 'purpose' else 'Write their level in plain words, for example "high school, no calculus".')
        if learner.get('checked') not in (None, 'not-a-course'):
            r.error('learner.checked', 'must be "not-a-course" for self-study.', 'Set "checked": "not-a-course".')
    elif learner:
        r.error('learner.kind', 'must be "course" or "self-study".', 'Use "course" when this is for a class; otherwise "self-study".')

    # The claims ledger.
    claims = lesson.get('claims')
    ids = {}
    if not isinstance(claims, list) or not claims:
        r.error('"claims"', 'is empty.', 'Before writing narration, list each fact as a claim with id, text, source, where and an exact quote.')
        claims = []
    for i, c in enumerate(claims):
        where = f'Claim {i + 1}'
        if not isinstance(c, dict):
            r.error(where, 'is not an object.', 'Write each claim as {"id": ..., "text": ..., ...}.')
            continue
        cid = str(c.get('id', '')).strip()
        where = f'Claim {cid or i + 1}'
        if not cid:
            r.error(where, 'has no id.', 'Give it "id": "c1", "c2" and so on.')
        elif cid in ids:
            r.error(where, 'uses an id that is already taken.', 'Give every claim its own id.')
        ids[cid] = c
        for key in ('text', 'quote', 'where', 'source'):
            if not str(c.get(key, '')).strip():
                fix = {'text': 'Write the fact in one plain sentence.',
                       'quote': 'Copy the exact words from the source that say this fact. If no line says it, delete the claim and every sentence that uses it.',
                       'where': 'Write where the quote is: page, slide or section for the learner\'s material, or the web address for an outside source.',
                       'source': 'Name the source: the book with its edition, the slide deck, or the website.'}[key]
                r.error(where, f'has no "{key}".', fix)
        if words(c.get('quote', '')) > 40:
            r.error(where, f'has a {words(c["quote"])}-word quote.', 'Keep only the words that state the fact: 40 or fewer.')
        frm = c.get('from')
        if frm == 'course':
            if c.get('where') and not re.search(r'\d', str(c['where'])):
                r.error(where, 'gives no page, slide or section number.', 'Add the number to "where", for example "Lecture 7, slide 12" or "Ch. 4, p. 112".')
        elif frm == 'outside':
            if c.get('where') and not re.match(r'^https?://', str(c['where'])):
                r.error(where, 'is outside the course but "where" is not a web address.', 'Put the full https:// address of the page in "where". Use only a reliable source: a textbook, a university, a government agency or a journal.')
            if not DATE.match(str(c.get('checked', ''))):
                r.error(where, 'has no date checked.', 'Add "checked": "YYYY-MM-DD", the day you read the page.')
        else:
            r.error(where, '"from" must be "course" or "outside".', 'Use "course" for the learner\'s own materials and "outside" for anything else.')
        status = c.get('status', 'unchecked')
        if status not in ('unchecked', 'matched', 'conflict'):
            r.error(where, f'has status {status!r}.', 'Use "unchecked", "matched" or "conflict".')
        if status == 'conflict' and not str(c.get('note', '')).strip():
            r.error(where, 'is marked conflict with no note.', 'In "note", say what the course says, what the reliable source says, and give that source.')
        if final and status == 'unchecked':
            r.error(where, 'is not checked yet.', 'Do step 6: find the quote in the source, confirm it says the claim, then set "status": "matched" (or "conflict" with a note).')
        if c.get('file') is not None and not isinstance(c.get('file'), str):
            r.error(where, '"file" must be one file name.', 'Write the name of one file given to --sources, like "file": "slides.md".')
        elif sources is not None and c.get('quote'):
            q = norm(c['quote'])
            pool = {c['file']: sources[c['file']]} if c.get('file') in sources else sources
            if c.get('file') and c['file'] not in sources:
                r.error(where, f'names file {c["file"]!r}, which was not given to --sources.', 'Give that file to --sources, or fix the file name.')
            elif frm == 'course' and q and not any(q in text for text in pool.values()):
                r.error(where, 'quote was not found in the learner\'s materials.', 'Copy the words exactly from the material. If the material does not say it, delete the claim or change it to "from": "outside" with a reliable web source.')
            elif frm == 'outside' and q and pool and not any(q in text for text in pool.values()):
                r.warn(where, 'quote was not found in the files given to --sources.', 'If you saved that web page, copy the words exactly from it.')
    used = set()

    def need_claims(where, ref_list, required, what):
        if ref_list is None:
            ref_list = []
        if not isinstance(ref_list, list):
            r.error(where, '"claims" must be a list.', 'Write it like "claims": ["c1"].')
            return
        for ref in ref_list:
            if not isinstance(ref, str):
                r.error(where, f'"claims" holds {json.dumps(ref)[:40]}, not an id.', 'List claim ids as text, like "claims": ["c3"].')
                continue
            if ref not in ids:
                r.error(where, f'cites {ref!r}, which is not in "claims".', f'Use an id from "claims", or add a claim {ref!r} with its source and quote first.')
            used.add(ref)
        if required and not ref_list:
            r.error(where, f'{what} has no claim ids.', 'Add the id of the claim that supports it, such as "claims": ["c3"].')

    # Scenes, beats and what is on screen.
    scenes = lesson.get('scenes')
    if not isinstance(scenes, list) or not scenes:
        r.error('"scenes"', 'is empty.', 'Write the scenes: names first, then the explanation, an example, and a summary.')
        scenes = []
    roles, total, gap, pauses, first_terms = [], 0.0, 0.0, 0, False
    gap_from = 'the start'
    for si, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            r.error(f'Scene {si + 1}', 'is not an object.', 'Write each scene as {"id": ..., "title": ..., "role": ..., "beats": [...]}.')
            continue
        sname = f'Scene {si + 1} ({scene.get("title", "untitled")})'
        if not str(scene.get('title', '')).strip():
            r.error(sname, 'has no title.', 'Give it a 2 to 5 word title. It becomes the chapter name.')
        role = scene.get('role')
        if role not in ROLES:
            r.error(sname, f'has role {role!r}.', 'Set "role" to one of: ' + ', '.join(ROLES) + '.')
        roles.append(role)
        beats = scene.get('beats')
        if not isinstance(beats, list) or not beats:
            r.error(sname, 'has no beats.', 'Add beats: each one is a sentence to say, or a pause question.')
            continue
        shown, scene_seconds, scene_words, has_show, scene_pause = [], 0.0, 0, False, False
        for bi, beat in enumerate(beats):
            where = f'{sname}, beat {bi + 1}'
            if not isinstance(beat, dict):
                r.error(where, 'is not an object.', 'Write it as {"say": ..., "claims": [...]} or {"pause": {...}}.')
                continue
            if ('say' in beat) == ('pause' in beat):
                r.error(where, 'needs exactly one of "say" or "pause".', 'Split it into two beats: one with "say", one with "pause".')
                continue
            if 'pause' in beat:
                p = beat['pause'] if isinstance(beat['pause'], dict) else {}
                pauses += 1
                scene_pause = True
                for key in ('ask', 'answer', 'why'):
                    if not str(p.get(key, '')).strip():
                        r.error(where, f'pause has no "{key}".', {'ask': 'Write the question the learner answers before the video goes on.',
                                                                  'answer': 'Write the correct answer.',
                                                                  'why': 'Write one sentence saying why that answer is right.'}[key])
                ch = p.get('choices')
                if ch is not None:
                    if not isinstance(ch, list) or not 2 <= len(ch) <= 5:
                        r.error(where, 'pause "choices" must list 2 to 5 options.', 'List 2 to 5 short options, or remove "choices" so the learner types an answer.')
                    elif p.get('answer') not in ch:
                        r.error(where, 'pause "answer" is not one of its "choices".', 'Make "answer" exactly match one of the choices.')
                need_claims(where, p.get('claims'), True, 'The pause answer')
                gap = 0.0
                gap_from = where
                continue
            say = beat['say']
            if not isinstance(say, str) or not say.strip():
                r.error(where, '"say" is empty.', 'Write one short sentence to say aloud.')
                continue
            if hold_of(beat) is None:
                r.error(where, f'"hold" is {beat.get("hold")!r}.', f'Make "hold" a number of seconds from 0 to {HOLD_MAX}, or delete it.')
            n = words(say)
            if n > SENTENCE_MAX:
                r.error(where, f'says {n} words in one beat.', f'Split it into two beats of under {SENTENCE_WARN} words each.')
            elif n > SENTENCE_WARN:
                r.warn(where, f'says {n} words in one beat.', f'Short sentences are easier to follow; aim for {SENTENCE_WARN} or fewer.')
            if len(re.findall(r'[.!?](\s|$)', say.strip())) > 2:
                r.error(where, 'holds more than two sentences.', 'Put one or two sentences in each beat.')
            if re.search(r'\b\d{1,2}:\d{2}\b', say):
                r.error(where, 'mentions a timestamp.', 'Remove it. The player makes its own chapters.')
            talk = beat.get('talk') is True
            if talk:
                if re.search(r'\d', say):
                    r.error(where, 'is marked "talk" but has a number in it.', 'Numbers are facts: remove "talk": true and add "claims" with the id that supports the number.')
                if beat.get('claims'):
                    need_claims(where, beat.get('claims'), False, 'This sentence')
            else:
                need_claims(where, beat.get('claims'), True,
                            'This sentence (if it is only a question, an instruction or a transition, add "talk": true instead)')
            scene_seconds += beat_seconds(beat, wpm)
            gap += beat_seconds(beat, wpm)
            if gap > PAUSE_GAP_MAX:
                r.error(where, f'comes {gap:.0f} s after {gap_from} with no pause question.', 'Add a pause beat before this one: {"pause": {"ask": ..., "answer": ..., "why": ..., "claims": [...]}}. Aim for one every 60 to 90 s.')
                gap = 0.0
                gap_from = where
            show = beat.get('show', [])
            if not isinstance(show, list):
                r.error(where, '"show" must be a list.', 'Write it as "show": [ {...} ].')
                continue
            for ei, el in enumerate(show):
                ew = f'{where}, show {ei + 1}'
                if not isinstance(el, dict) or el.get('type') not in SHOW_TYPES:
                    r.error(ew, f'has type {el.get("type") if isinstance(el, dict) else el!r}.', 'Use one of: ' + ', '.join(SHOW_TYPES) + '.')
                    continue
                has_show = True
                t = el['type']
                if t == 'term' and si < 2:
                    first_terms = True
                required = {'title': ('text',), 'question': ('text',), 'term': ('word', 'meaning'), 'label': ('text',),
                            'equation': ('text',), 'step': ('text',), 'arrow': ('from', 'to'), 'highlight': ('target',),
                            'graph': ('points', 'x', 'y'), 'image': ('src', 'alt', 'credit', 'license'),
                            'compare': ('left', 'right', 'leftItems', 'rightItems'), 'quote': ('text', 'claim')}[t]
                for key in required:
                    if el.get(key) in (None, '', []):
                        r.error(ew, f'{t} has no "{key}".', f'Add "{key}". A {t} needs: ' + ', '.join(required) + '.')
                for key, text in element_texts(el):
                    limit = LIMITS.get(key)
                    if limit and words(text) > limit:
                        r.error(ew, f'{key.replace(".", " ")} has {words(text)} words on screen.', f'Cut it to {limit} words or fewer. The narration says the sentence; the screen shows key words.')
                    if words(text) >= 5 and norm(text) and norm(text) in norm(say) and t != 'quote':
                        r.error(ew, 'repeats the narration word for word.', 'Show 2 to 6 key words instead of the sentence being spoken.')
                    scene_words += words(text)
                if t == 'compare':
                    for side in ('leftItems', 'rightItems'):
                        if not isinstance(el.get(side), list) or len(el.get(side) or []) > 4:
                            r.error(ew, f'"{side}" must be a list of 1 to 4 short items.', 'Keep 1 to 4 items on each side.')
                if t == 'graph':
                    pts = el.get('points')
                    ok = isinstance(pts, list) and len(pts) >= 2 and all(
                        isinstance(pt, list) and len(pt) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in pt) for pt in pts)
                    if not ok:
                        r.error(ew, 'graph "points" must be [[x, y], ...] with at least 2 number pairs.', 'Write numbers only, like [[0, 1], [1, 3], [2, 9]]. Work each one out; never guess.')
                    need_claims(ew, el.get('claims'), True, 'The graph data')
                if t == 'equation':
                    need_claims(ew, el.get('claims'), False, 'The equation')
                if t == 'image':
                    src = str(el.get('src', ''))
                    if src and not re.match(r'^(https://|data:image/|[\w./-]+$)', src):
                        r.error(ew, 'image "src" is not a usable address.', 'Use an https:// address or a file next to the video.')
                    if not str(el.get('link', '')).strip():
                        r.warn(ew, 'image has no "link".', 'Add the page where the image and its license are shown.')
                if t == 'quote':
                    cid = el.get('claim')
                    if not isinstance(cid, str) or cid not in ids:
                        r.error(ew, f'quote cites {cid!r}, which is not in "claims".', 'Set "claim" to the id whose quote this is.')
                    elif norm(el.get('text', '')) not in norm(ids[cid].get('quote', '')):
                        r.error(ew, 'quote text is not in its claim\'s quote.', 'Copy the words exactly from that claim\'s "quote". Never change a quotation.')
                    if isinstance(cid, str):
                        used.add(cid)
                if t == 'highlight':
                    target = norm(el.get('target', ''))
                    if target and target not in shown:
                        r.error(ew, f'highlights {el.get("target")!r}, which is not on screen in this scene yet.', 'Set "target" to the exact text of something shown earlier in this scene (a term word, label, step, or compare item).')
                for key, text in element_texts(el):
                    shown.append(norm(text))
        if scene_seconds > SCENE_MAX_SECONDS:
            r.error(sname, f'runs {scene_seconds / 60:.1f} minutes.', 'Split it into two scenes of 6 minutes or less.')
        if scene_words > SCREEN_WORDS_MAX:
            r.error(sname, f'puts {scene_words} words on screen.', f'Cut the screen text to {SCREEN_WORDS_MAX} words or fewer: key words only, one idea at a time.')
        elif scene_words > SCREEN_WORDS_WARN:
            r.warn(sname, f'puts {scene_words} words on screen.', f'Aim for {SCREEN_WORDS_WARN} or fewer.')
        if not has_show:
            r.warn(sname, 'shows nothing on screen.', 'Add one visual for this scene: a term, label, step, arrow, graph or compare.')
        if role == 'faded' and not scene_pause:
            r.error(sname, 'is a faded example with no pause.', 'In a faded example the learner does a step: add a pause beat that asks for it.')
        total += scene_seconds
    if gap > PAUSE_GAP_MAX:
        r.error('The last scenes', f'run {gap:.0f} s after {gap_from} with no pause question.', 'Add a pause beat in the last scene.')
    if scenes and not first_terms:
        r.error('Scenes 1 and 2', 'name no terms.', 'Before the explanation, show each new word as a term: {"type": "term", "word": ..., "meaning": ...}. Use the course\'s own words.')
    if pauses == 0 and scenes:
        r.error('The video', 'has no pause questions.', 'Add a pause beat every 60 to 90 seconds that asks the learner to predict or answer.')
    if kind == 'problem':
        if 'worked' not in roles:
            r.error('The video', 'has no worked example.', 'Add a scene with "role": "worked" that solves one problem step by step.')
        if 'faded' not in roles:
            r.error('The video', 'has no faded example.', 'After the worked example, add a scene with "role": "faded": a similar problem where the learner does the next step.')
        elif 'worked' in roles and roles.index('faded') < roles.index('worked'):
            r.error('The video', 'puts the faded example before the worked one.', 'Move the "faded" scene after the "worked" scene.')
    elif kind == 'concept' and 'example' not in roles and 'worked' not in roles:
        r.error('The video', 'has no example scene.', 'Add a scene with "role": "example" that applies the idea to one concrete case.')
    mis = lesson.get('misconception')
    if mis:
        if not isinstance(mis, dict) or not str(mis.get('wrong', '')).strip() or not str(mis.get('right', '')).strip():
            r.error('"misconception"', 'needs "wrong" and "right".', 'Write the mistaken idea in "wrong" and the correction in "right".')
        else:
            need_claims('"misconception"', mis.get('claims'), True, 'The correction')
        if 'misconception' not in roles:
            r.error('"misconception"', 'is never taught.', 'Add a scene with "role": "misconception" that names the mistake and corrects it.')
    else:
        r.warn('"misconception"', 'is missing.', 'If you know a common mistake on this topic (or the learner made one), add it and a scene that corrects it.')
    rec = lesson.get('recall')
    if not isinstance(rec, dict) or not str(rec.get('ask', '')).strip() or not isinstance(rec.get('points'), list) or not 1 <= len(rec['points']) <= 5:
        r.error('"recall"', 'is missing or incomplete.', 'Add "recall": {"ask": "Look away and explain ...", "points": ["...", "..."]} with 1 to 5 points.')
    pr = lesson.get('practice')
    if not isinstance(pr, dict) or not str(pr.get('ask', '')).strip() or not str(pr.get('answer', '')).strip():
        r.error('"practice"', 'is missing or incomplete.', 'Add "practice": {"ask": ..., "answer": ..., "steps": [...], "claims": [...]}: one new problem like the one taught.')
    else:
        need_claims('"practice"', pr.get('claims'), True, 'The practice answer')
        if kind == 'problem' and not pr.get('steps'):
            r.error('"practice"', 'has no steps.', 'List the solution steps in "steps" so the learner can check each one.')
    for cid in ids:
        if cid and cid not in used:
            r.warn(f'Claim {cid}', 'is never used.', 'Use it in a sentence, or delete it.')
    if scenes and total < 45:
        r.warn('The video', f'is only {total:.0f} s of narration.', 'Check that every objective is taught.')
    # Audio clips that no longer match their sentence must not play.
    audio = lesson.get('audio')
    if isinstance(audio, dict) and isinstance(audio.get('clips'), dict):
        keys = {fnv1a(b['say']) for s in scenes if isinstance(s, dict) for b in s.get('beats') or []
                if isinstance(b, dict) and isinstance(b.get('say'), str)}
        stale = sorted(k for k in audio['clips'] if k not in keys)
        if stale:
            r.error('"audio.clips"', f'has {len(stale)} clip(s) for sentences that changed: ' + ', '.join(stale[:5]) + '.', 'Delete those clips and make new ones from --audio-plan.')
        missing = sorted(keys - set(audio['clips']))
        if missing:
            r.warn('"audio.clips"', f'is missing {len(missing)} clip(s).', 'Those sentences use the browser voice until you add clips.')
    summary = {'seconds': round(total), 'pauses': pauses, 'scenes': len(scenes), 'claims': len(ids),
               'claims_checked': sum(1 for c in ids.values() if c.get('status') in ('matched', 'conflict'))}
    return r.errors, r.warnings, summary


def read_lesson(path):
    """Load the lesson, tolerating a ```json fence around it. Returns (lesson, note) or raises SystemExit(2)."""
    text = Path(path).read_text()
    note = None
    fenced = re.match(r'^\s*```[a-zA-Z]*\s*\n(.*?)\n\s*```\s*$', text, re.S)
    if fenced:
        text, note = fenced.group(1), 'The file was wrapped in ``` marks; they were ignored. Save only the JSON next time.'
    try:
        return json.loads(text), note
    except json.JSONDecodeError as exc:
        lines = text.splitlines()
        shown = lines[exc.lineno - 1] if 0 < exc.lineno <= len(lines) else ''
        print(f'NOT VALID JSON: line {exc.lineno}, column {exc.colno}: {exc.msg}.')
        print(f'  That line: {shown.strip()[:160]}')
        print('FIX: look at that line and the one before it. The usual causes:')
        print('  1. A missing comma between two items or two "key": value pairs.')
        print('  2. A comma right before ] or }. Delete it.')
        print('  3. A " inside text. Replace it with \' .')
        print('  4. A comment (// or #). JSON has no comments. Delete it.')
        print('Then run this check again.')
        raise SystemExit(2)


def embed(lesson, template=TEMPLATE):
    page = Path(template).read_text()
    data = json.dumps(lesson, ensure_ascii=False, indent=1).replace('<', '\\u003c')
    new, n = re.subn(r'(<script type="application/json" id="lesson">)(.*?)(</script>)',
                     lambda m: m.group(1) + '\n' + data + '\n' + m.group(3), page, count=1, flags=re.S)
    if n != 1:
        raise SystemExit(f'{template}: no lesson block to fill.')
    return new


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('lesson')
    ap.add_argument('--sources', action='append', help="the learner's materials as text, a file or a folder (repeatable)")
    ap.add_argument('--final', action='store_true', help='also require every claim to be checked')
    ap.add_argument('--build', metavar='OUT.html', help='write the player with this lesson inside, only if the check passes')
    ap.add_argument('--audio-plan', action='store_true', help='print each narration line with its clip name, as JSON')
    ap.add_argument('--json', action='store_true', help='print the result as JSON')
    a = ap.parse_args(argv)
    lesson, note = read_lesson(a.lesson)
    if a.audio_plan:
        scenes = lesson.get('scenes') if isinstance(lesson, dict) else None
        lines = [{'clip': fnv1a(b['say']) + '.mp3', 'text': b['say']} for s in (scenes if isinstance(scenes, list) else [])
                 if isinstance(s, dict) for b in (s.get('beats') if isinstance(s.get('beats'), list) else [])
                 if isinstance(b, dict) and isinstance(b.get('say'), str)]
        print(json.dumps(lines, indent=1, ensure_ascii=False))
        return 0
    errors, warnings, summary = check(lesson, load_sources(a.sources) if a.sources else None, a.final)
    if a.json:
        print(json.dumps({'errors': errors, 'warnings': warnings, 'summary': summary}, indent=1))
        return 1 if errors else 0
    if note:
        print('NOTE: ' + note)
    if errors:
        print(f'NOT READY: {len(errors)} problem(s). Fix them in this order, then run the check again.')
        for i, (where, problem, fix) in enumerate(errors, 1):
            print(f'{i}. {where} {problem}\n   Fix: {fix}')
    if warnings:
        print(f'WORTH FIXING ({len(warnings)}), not required:')
        for where, problem, fix in warnings:
            print(f'- {where} {problem} {fix}')
    m, s = divmod(summary.get('seconds', 0), 60)
    print(f'Video: {m}:{s:02d} of narration, {summary.get("scenes", 0)} chapters, {summary.get("pauses", 0)} pause questions, '
          f'{summary.get("claims", 0)} claims ({summary.get("claims_checked", 0)} checked).')
    if errors:
        return 1
    if a.sources:
        print('Every course quote was found in the files given to --sources.')
    if a.build:
        Path(a.build).write_text(embed(lesson))
        print(f'READY. Wrote {a.build}. Open it and watch the first minute before you share it.')
    else:
        print('READY. This checks structure, sources and teaching rules, not whether each fact is true.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
