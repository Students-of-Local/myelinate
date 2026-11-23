#!/usr/bin/env python3
"""Check a Myelinate video lesson file and print the fixes it needs, in order.

    python3 scripts/video_check.py lesson.json                    # check; exit 1 until clean
    python3 scripts/video_check.py lesson.json --sources notes/   # also match every quote in the files it names
    python3 scripts/video_check.py lesson.json --sources notes/ --final   # also require a recorded review
    python3 scripts/video_check.py lesson.json --sources notes/ --build video.html   # check, sign, write the player
    python3 scripts/video_check.py lesson.json --audio-plan       # list the narration lines and the clip name for each

A model cannot be trusted to judge truth, so this script judges what code can:
  * every quote is found in the file the claim names (--sources);
  * every calculation is recomputed with a safe arithmetic evaluator;
  * every number said or shown is backed by a cited quote or calculation;
  * every cited claim shares key words with the sentence that cites it;
  * a sentence in the sources that says the opposite of a claim is a conflict the video must flag;
  * a timestamp in "where" is within 20 seconds of the quote in a timed transcript.
It writes the "verification" block (the badge the learner sees). A lesson cannot set it itself.
Reasoning and explanations need a second reader: that is the "review" block (skill step 6).
"""
import argparse
import ast
import collections
import datetime
import difflib
import hashlib
import html
import json
import math
import operator
import re
import sys
import unicodedata
from pathlib import Path

FORMAT = 'myelinate-video/1'
VERSION = '3.2.0'
ROLES = ('intro', 'names', 'explain', 'example', 'worked', 'faded', 'misconception', 'summary')
SHOW_TYPES = ('title', 'question', 'term', 'label', 'equation', 'step', 'arrow', 'highlight', 'graph',
              'image', 'compare', 'quote', 'table', 'row', 'bars')
TIERS = ('memorize', 'given')
SHOW_MAX = 12  # problems printed per run: a long list swamps a small model, and fixing the first ones often clears the rest
# The player puts these on the left of a two-column screen and words and steps on the right.
BOARD_VISUAL = {'title', 'question', 'equation', 'arrow', 'compare', 'quote', 'image', 'graph', 'table', 'row', 'bars'}
WPM_MIN, WPM_MAX = 130, 160
SENTENCE_MAX, SENTENCE_WARN = 30, 22
SCENE_MAX_SECONDS = 360
VIDEO_MAX_SECONDS, VIDEO_WARN_SECONDS = 390, 360
PAUSE_GAP_MAX, PAUSE_GAP_WARN = 120, 90
SCREEN_WORDS_MAX, SCREEN_WORDS_WARN = 40, 30
STALE_DAYS = 365
TIME_WINDOW = 20  # seconds either side of a transcript timestamp
BEAT_GAP = 0.4  # seconds of silence after each sentence, same as the player
CLIP_WPM_MAX = 260  # no recorded sentence is faster than this; a shorter length was not measured
TEMPLATE = Path(__file__).resolve().parent.parent / 'templates' / 'video-player.html'
EXAMPLE = Path(__file__).resolve().parent.parent / 'examples' / 'video-lesson-sky.json'
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
CALC_ID = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,15}$')
# Word limits for things on screen: the narration carries the sentence, the screen carries a few key words.
LIMITS = {'title.text': 8, 'title.sub': 10, 'question.text': 16, 'term.word': 4, 'term.meaning': 10,
          'label.text': 8, 'step.text': 10, 'arrow.from': 4, 'arrow.to': 4, 'arrow.label': 4,
          'compare.left': 5, 'compare.right': 5, 'compare.item': 6, 'graph.title': 8, 'quote.text': 30,
          'table.column': 4, 'table.cell': 4, 'bars.title': 8, 'bars.label': 3, 'equation.text': 14}


def fnv1a(text):
    """Clip name for a narration line: FNV-1a 32-bit of its UTF-8 bytes, 8 hex digits. The player uses the same."""
    h = 0x811c9dc5
    for b in text.encode('utf-8'):
        h ^= b
        h = (h * 0x01000193) & 0xffffffff
    return f'{h:08x}'


def words(text):
    return len(str(text).split())


SPOKEN_NUMBER = re.compile(r'(\d[\d,]*)(?:\.(\d+))?(%?)|\.(\d+)(%?)')


def _number_words(n):
    """How many words a whole number takes aloud: 7 -> 1, 42 -> 2, 990 -> 4, 50000 -> 2."""
    if n < 20:
        return 1
    if n < 100:
        return 1 if n % 10 == 0 else 2
    for value in (10 ** 9, 10 ** 6, 1000, 100):
        if n >= value:
            head, rest = divmod(n, value)
            return _number_words(head) + 1 + (_number_words(rest) if rest else 0)
    return 1


def _spoken_number(m):
    if m.group(1) is not None:
        whole, frac, pct = m.group(1).replace(',', ''), m.group(2), m.group(3)
        k = _number_words(int(whole or 0))
    else:
        frac, pct, k = m.group(4), m.group(5), 1
    k += (1 + len(frac) if frac else 0) + (1 if pct else 0)
    return ' ' + 'w ' * k


def spoken_words(text):
    """Words as said aloud, which sets how long a line takes: "0.4225" is five ("zero point four two two five").
    The player counts the same way."""
    return len([w for w in SPOKEN_NUMBER.sub(_spoken_number, str(text)).split() if re.search(r'\w', w)])


def screen_words(text):
    """Words a learner reads on screen. Bare numbers are glanced at, not read, so they do not count."""
    return len([w for w in str(text).split() if re.search(r'[^\d.,%=+\-*/()^]', w)])


def norm(text):
    """Lowercase letters and digits only, with ligatures, accents, quote marks and PDF line-break hyphens undone."""
    text = unicodedata.normalize('NFKC', str(text)).replace('\u00ad', '')
    text = re.sub(r'(\w)-[ \t]*\r?\n\s*(\w)', r'\1\2', text)
    text = ''.join(ch for ch in unicodedata.normalize('NFKD', text) if not unicodedata.combining(ch))
    text = text.lower().replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', text).split())


def has(haystack, needle):
    """needle appears in haystack as whole words (both already normalized)."""
    return bool(needle) and f' {needle} ' in f' {haystack} '


HOLD_MAX = 30


def hold_of(beat):
    """Extra seconds after a sentence: a number from 0 to HOLD_MAX, or None when it is not one."""
    h = beat.get('hold', 0)
    if h is None:
        return 0.0
    if isinstance(h, bool) or not isinstance(h, (int, float)) or not 0 <= h <= HOLD_MAX:
        return None
    return float(h)


def beat_seconds(beat, wpm, clip_seconds=None):
    """A sentence's time on the timeline: its recorded clip's length when there is one, like the player."""
    if 'say' in beat and isinstance(beat['say'], str):
        speak = (clip_seconds or {}).get(fnv1a(beat['say'])) or spoken_words(beat['say']) * 60.0 / wpm
        return speak + BEAT_GAP + (hold_of(beat) or 0.0)
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
    elif t == 'table':
        out += [('table.column', c) for c in (el.get('columns') or []) if isinstance(c, (str, int, float))]
        for row in el.get('rows') or []:
            if isinstance(row, list):
                out += [('table.cell', c) for c in row]
    elif t == 'row':
        out += [('table.cell', c) for c in (el.get('cells') or [])]
    elif t == 'bars':
        out.append(('bars.title', el.get('title', '')))
        for it in el.get('items') or []:
            if isinstance(it, dict):
                out += [('bars.label', it.get('label', '')), ('bars.value', it.get('value', ''))]
    elif t == 'highlight':
        pass
    else:
        for field in ('text', 'sub', 'word', 'meaning', 'from', 'to', 'label'):
            if field in el:
                out.append((f'{t}.{field}', el[field]))
    out = [(k, str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v) for k, v in out]
    return [(k, v) for k, v in out if isinstance(v, str) and v.strip()]


# ---------------------------------------------------------------- numbers

ORDINAL_WORDS = r'(?:step|steps|part|chapter|scene|problem|question|example|exam|slide|slides|page|pages|lecture|figure|fig|table|unit|week|module|section|ch|p|pp|lab|quiz|homework|hw|beat|claim|item|choice|option|version|edition|ed|level)'
NUM = re.compile(r'(?<![\w.^_])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)(?![\w])(\s?%| percent)?', re.I)
ORDINAL_BEFORE = re.compile(r'(?<![A-Za-z])' + ORDINAL_WORDS + r'\.?\s*$', re.I)  # whole words: "dropped 37" is a number
APPROX_BEFORE = re.compile(r'(?:about|around|roughly|nearly|almost|approximately|some|~|≈)\s*$', re.I)
UNITS = {w: i for i, w in enumerate('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split())}
TENS = {w: 10 * i for i, w in enumerate('_ _ twenty thirty forty fifty sixty seventy eighty ninety'.split()) if w != '_'}
SCALES = {'hundred': 100, 'thousand': 1000, 'million': 1000000}


def numbers_in(text, approx_ok=False):
    """Numbers stated in a piece of text: [(value, decimals, is_percent, approximate, shown)].

    Digits are read as written. Spelled-out numbers are read too when they could carry a fact: 11 or more,
    anything with "point", "percent", "hundred", "thousand" or "million". Ordinal labels such as
    "Step 2" or "slide 5", exponents (x^2) and subscripts (v_0) are not numbers.
    """
    text = str(text)
    out = []
    for m in NUM.finditer(text):
        raw, pct = m.group(1), bool(m.group(2))
        before = text[max(0, m.start() - 16):m.start()]
        if ORDINAL_BEFORE.search(before) and '.' not in raw:
            continue
        if re.search(r'[A-Za-z]$', before) and not before.endswith(' '):
            continue
        if re.match(r'\s*(?:st|nd|rd|th)\b', text[m.end():]):
            continue
        val = float(raw.replace(',', ''))
        dec = len(raw.split('.')[1]) if '.' in raw else 0
        out.append((val, dec, pct, bool(APPROX_BEFORE.search(before)), raw + ('%' if pct else '')))
    toks = re.findall(r"[a-z]+|\d+", text.lower().replace('-', ' '))
    i = 0
    while i < len(toks):
        if toks[i] not in UNITS and toks[i] not in TENS:
            i += 1
            continue
        j, total, cur, dec_digits, seen_point, big = i, 0, 0, '', False, False
        while j < len(toks):
            w = toks[j]
            if seen_point and w in UNITS and UNITS[w] < 10:
                dec_digits += str(UNITS[w])
            elif not seen_point and w in UNITS:
                cur += UNITS[w]
            elif not seen_point and w in TENS:
                cur += TENS[w]
            elif not seen_point and w in SCALES and (cur or total):
                big = True
                if w == 'hundred':
                    cur = (cur or 1) * 100
                else:
                    total += (cur or 1) * SCALES[w]
                    cur = 0
            elif w == 'point' and not seen_point and j + 1 < len(toks) and toks[j + 1] in UNITS:
                seen_point = True
            elif w == 'and' and not seen_point and j + 1 < len(toks) and (toks[j + 1] in UNITS or toks[j + 1] in TENS) and big:
                pass
            else:
                break
            j += 1
        value = total + cur + (float('0.' + dec_digits) if dec_digits else 0)
        pct = j < len(toks) and toks[j] == 'percent'
        before = ' '.join(toks[max(0, i - 2):i])
        if (value >= 11 or seen_point or pct or big) and not ORDINAL_BEFORE.search(before):
            out.append((float(value), len(dec_digits), pct, bool(APPROX_BEFORE.search(before)), ' '.join(toks[i:j])))
        i = max(j, i + 1)
    return out


def backs(stated, pool):
    """Is a stated number backed by any number in pool? pool holds floats, at full precision where computed.

    Each reading of the stated number keeps its own precision: "0.8%" is 0.8 to one place or 0.008 to three,
    so 0.009 does not back it. A whole number may round a computed value (989.9 said as 990) only from 10 up."""
    val, dec, pct, approx, _ = stated
    targets = [(val, dec)] + ([(val / 100, dec + 2)] if pct else []) + ([(val * 100, max(0, dec - 2))] if not pct and val <= 1 else [])
    for b in pool:
        for t, d in targets:
            if abs(b - t) < 1e-9:
                return True
            if approx and abs(b - t) <= max(0.5 * 10 ** (-d), abs(b) * 0.02):
                return True
            if d > 0 and abs(round(b, d) - t) < 10 ** (-d) / 2 + 1e-9:
                return True
            if d == 0 and abs(b) >= 10 and abs(b - t) < 0.5:
                return True
    return False


# ---------------------------------------------------------------- safe arithmetic

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow}


def safe_eval(expr, names):
    """Evaluate + - * / ** ( ) sqrt() abs() on numbers and earlier calc ids. Nothing else is allowed. Never eval()."""
    src = str(expr).replace('^', '**').replace('×', '*').replace('·', '*').replace('÷', '/').replace('−', '-')
    if len(src) > 240:
        raise ValueError('it is longer than 240 characters')
    try:
        tree = ast.parse(src, mode='eval')
    except SyntaxError:
        raise ValueError('it is not arithmetic Python can read')

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return float(n.value)
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and (abs(b) > 12 or abs(a) > 1e9):
                raise ValueError('a power is too large')
            return _OPS[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.Name):
            if n.id in names:
                return names[n.id]
            raise ValueError(f'it uses {n.id!r}, which is not an earlier calc id')
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ('sqrt', 'abs') and len(n.args) == 1 and not n.keywords:
            v = ev(n.args[0])
            return math.sqrt(v) if n.func.id == 'sqrt' else abs(v)
        raise ValueError('it uses something other than numbers, + - * / ^, brackets, sqrt() and earlier calc ids')
    try:
        v = ev(tree)
    except ZeroDivisionError:
        raise ValueError('it divides by zero')
    if not math.isfinite(v):
        raise ValueError('its result is not a finite number')
    return v


# ---------------------------------------------------------------- sources

class Sources(dict):
    """Normalized text of each source file by name, plus the raw text (.raw) for sentences and timestamps."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.raw = {}


TS = re.compile(r'(?:^|\[|\(|\s)(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:[.,]\d+)?(?:\]|\)|\s|$)')


def seconds_of(text):
    m = re.search(r'(?<!\d)(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?!\d)', str(text))
    if not m:
        return None
    return int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))


def timed_segments(raw):
    """[(start_seconds, normalized text)] for a transcript whose lines start with a timestamp, else []."""
    segs = []
    for line in raw.splitlines():
        m = re.match(r'^\s*\[?((?:\d{1,2}:)?\d{1,2}:\d{2})(?:[.,]\d+)?\]?\s*(?:-->\s*\S+\s*)?(.*)$', line)
        if m:
            segs.append([seconds_of(m.group(1)), norm(m.group(2))])
        elif segs and line.strip() and not re.match(r'^\s*(WEBVTT|\d+\s*$)', line):
            segs[-1][1] = (segs[-1][1] + ' ' + norm(line)).strip()
    return [tuple(s) for s in segs] if len(segs) >= 3 else []


def quote_near(raw, quote_n, t):
    """Is the normalized quote said within TIME_WINDOW seconds of t in a timed transcript? None if not timed.

    The quote is found in the joined text; the line it starts in sets its time span, from that line's
    timestamp to the next one. The "where" timestamp must fall inside that span, give or take TIME_WINDOW."""
    segs = timed_segments(raw)
    if not segs or not quote_n:
        return None
    joined, starts = '', []
    for _, text in segs:
        starts.append(len(joined))
        joined += (' ' if joined else '') + text
    hay = f' {joined} '
    pos, found = hay.find(f' {quote_n} '), False
    while pos != -1:
        found = True
        i = max(k for k, st in enumerate(starts) if st <= pos)
        begin = segs[i][0]
        end = segs[i + 1][0] if i + 1 < len(segs) else begin + 30
        if begin - TIME_WINDOW <= t <= end + TIME_WINDOW:
            return True
        pos = hay.find(f' {quote_n} ', pos + 1)
    return False if found else None


def clean_vtt(text):
    """A WebVTT file as plain timed lines: no word-timing or style tags, cue settings or header lines."""
    text = re.sub(r'<(?:\d+:)?\d+:\d+(?:[.,]\d+)?>', '', text)
    text = re.sub(r'</?(?:c|v|i|b|u|lang|ruby|rt)(?:[.\s][^>]*)?>', '', text)
    text = re.sub(r'(-->[ \t]*\S+)[ \t]+[^\n]*', r'\1', text)
    return re.sub(r'(?m)^(?:WEBVTT|Kind:|Language:|NOTE\b|STYLE\b|REGION\b).*$', '', text)


def load_sources(paths):
    """Text of each source file, keyed by file name. HTML is reduced to its text."""
    found = Sources()
    for raw in paths or []:
        p = Path(raw)
        files = sorted(x for x in p.rglob('*') if x.is_file()) if p.is_dir() else [p]
        for f in files:
            if f.suffix.lower() not in ('.txt', '.md', '.html', '.htm', '.csv', '.json', '.vtt', '.srt'):
                continue
            text = f.read_text(errors='replace')
            if f.suffix.lower() == '.vtt' or text.lstrip().startswith('WEBVTT'):
                text = clean_vtt(text)
            if f.suffix.lower() in ('.html', '.htm'):
                text = re.sub(r'(?is)<(script|style)\b.*?</\1>', ' ', text)
                text = html.unescape(re.sub(r'<[^>]+>', ' ', text))
            # A timed transcript is matched without its timestamps, so a quote may run across two lines.
            segs = timed_segments(text)
            found[f.name] = ' '.join(t for _, t in segs) if segs else norm(text)
            found.raw[f.name] = text
    return found


# ---------------------------------------------------------------- meaning (coverage and conflicts)

STOP = set('''a an the and or but if then so of to in on at by for with from as is are was were be been being it its this that these those
there here they them their we you your our i he she his her not no nor do does did done can could will would should may might must
have has had than into onto over under about after before also very more most less such each every any some all one two which who
whom whose what when where why how just only even same other another many much because while during between both either neither
per out up down off again once like say says said see shows show called call let lets get gets got make makes made use uses used
way ways thing things now new first second next last well yes'''.split())
DIRECTION_UP = {'gain', 'swell', 'increas', 'rise', 'grow', 'enter', 'expand', 'absorb'}
DIRECTION_DOWN = {'los', 'shrink', 'shrivel', 'decreas', 'fall', 'drop', 'leav', 'contract', 'releas'}
POLAR = [('hypertonic', 'hypotonic'), ('north', 'south'), ('northern', 'southern'), ('east', 'west'), ('dominant', 'recessive'), ('positive', 'negative'), ('true', 'false'), ('accept', 'reject'),
         ('above', 'below'), ('before', 'after'), ('heterozygot', 'homozygot'), ('acid', 'base'), ('endotherm', 'exotherm'),
         ('oxid', 'reduc'), ('summer', 'winter'), ('closer', 'farther'), ('closest', 'farthest'), ('perihelion', 'aphelion'), ('toward', 'away'), ('inside', 'outside'),
         ('maximum', 'minimum'), ('direct', 'invers'), ('even', 'odd')]
NEGATION = {'not', 'no', 'never', 'cannot', 'none', 'neither', 'nor', "n't", 'without'}


def stem(w):
    w = w.lower()
    for suf in ('ations', 'ation', 'ions', 'ion', 'ings', 'ing', 'edly', 'ies', 'ied', 'es', 'ed', 'ly', 's', 'e'):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def stems(text):
    return {stem(w) for w in re.findall(r"[a-z][a-z']+", norm_keep(text)) if w not in STOP and len(w) > 2}


def norm_keep(text):
    return unicodedata.normalize('NFKC', str(text)).lower().replace('’', "'")


def _flags(text):
    toks = re.findall(r"[a-z]+(?:n't)?", norm_keep(text))
    st = [stem(t) for t in toks]
    up = sum(1 for s in st for d in DIRECTION_UP if s.startswith(d))
    down = sum(1 for s in st for d in DIRECTION_DOWN if s.startswith(d))
    polar = {}
    for a, b in POLAR:
        ha = any(s == a or (len(a) > 6 and s.startswith(a)) for s in st)
        hb = any(s == b or (len(b) > 6 and s.startswith(b)) for s in st)
        if ha != hb:
            polar[a] = 0 if ha else 1
    neg = sum(1 for t in toks if t in NEGATION or t.endswith("n't")) % 2
    return (up > down) - (down > up), polar, neg


def _topic(text):
    """Content stems with the direction, polar and negation words taken out: what the sentence is about."""
    drop = set()
    for s in stems(text):
        if any(s.startswith(d) for d in DIRECTION_UP | DIRECTION_DOWN) or any(s in pair or (len(s) > 6 and any(s.startswith(x) for x in pair)) for pair in POLAR):
            drop.add(s)
    return stems(text) - drop


def disagrees(a, b):
    """Two statements about the same thing that point opposite ways. A heuristic tuned to miss rather than cry wolf:
    the sentences must share most of their topic words, and the direction, polar and negation flips between them
    must not cancel out (hypertonic-loses and hypotonic-gains agree; hypertonic-loses and hypertonic-gains do not)."""
    ta, tb = _topic(a), _topic(b)
    shared = ta & tb
    if len(shared) < 2 or len(shared) / max(1, len(ta | tb)) < 0.5:
        return False
    da, pa, na = _flags(a)
    db, pb, nb = _flags(b)
    flips = sum(1 for k in pa if k in pb and pa[k] != pb[k])
    direction_flip = da != 0 and db != 0 and da != db
    if flips and (da == 0 or db == 0):
        return False  # different conditions and no outcome to compare
    if not (direction_flip or flips or na != nb):
        return False
    return (direction_flip + flips + (na != nb)) % 2 == 1


def sentences(raw):
    raw = re.sub(r'(\w)-[ \t]*\r?\n\s*(\w)', r'\1\2', raw)
    parts = re.split(r'(?<=[.!?])\s+|\n\s*\n|\n(?=\s*[-*#\d])', raw)
    return [re.sub(r'\s+', ' ', p).strip(' -*#\t') for p in parts if len(p.split()) >= 4]


# ---------------------------------------------------------------- the check

_EXAMPLE_RUNS = None


def _runs(text, n=4):
    """Every run of n words in the text that holds at least two words that are not stop words."""
    w = re.findall(r"[a-z0-9']+", str(text).lower())
    return {' '.join(w[i:i + n]) for i in range(len(w) - n + 1) if sum(x not in STOP for x in w[i:i + n]) >= 2}


def example_runs():
    """(runs, source files, topic words) of the worked example, or empty sets when it is not next to this script.
    Topic words are the ones the example says three or more times and its own source also uses: sky, blue, scatter."""
    global _EXAMPLE_RUNS
    if _EXAMPLE_RUNS is None:
        try:
            ex = json.loads(EXAMPLE.read_text())
            texts = []
            for sc in ex.get('scenes', []):
                for b in sc.get('beats', []):
                    texts.append(b.get('say', ''))
                    if isinstance(b.get('pause'), dict):
                        texts += [str(b['pause'].get(k, '')) for k in ('ask', 'answer', 'why')]
                    for el in b.get('show', []) if isinstance(b.get('show'), list) else []:
                        texts += [t for _, t in element_texts(el)]
            files = {c.get('file') for c in ex.get('claims', []) if isinstance(c, dict)}
            src = set(re.findall(r"[a-z0-9']+", (EXAMPLE.parent / 'video-lesson-sky-source.md').read_text().lower()))
            count = collections.Counter(w for t in texts for w in re.findall(r"[a-z0-9']+", str(t).lower()) if w not in STOP)
            topic = {w for w, n in count.items() if n >= 3 and w in src}
            _EXAMPLE_RUNS = (set().union(*map(_runs, texts)), files, topic)
        except (OSError, ValueError, AttributeError):
            _EXAMPLE_RUNS = (set(), set(), set())
    return _EXAMPLE_RUNS


def canonical(lesson):
    """The bytes the verification hash covers: the lesson without its verification block, keys sorted, whole floats as ints."""
    def fix(v):
        if isinstance(v, float) and v.is_integer() and abs(v) < 2 ** 53:
            return int(v)
        if isinstance(v, dict):
            return {k: fix(x) for k, x in v.items()}
        if isinstance(v, list):
            return [fix(x) for x in v]
        return v
    body = {k: v for k, v in lesson.items() if k != 'verification'}
    return json.dumps(fix(body), sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def sha256_of(lesson):
    return hashlib.sha256(canonical(lesson).encode('utf-8')).hexdigest()


class Report:
    def __init__(self):
        self.errors, self.warnings = [], []

    def error(self, where, problem, fix):
        self.errors.append((where, problem, fix))

    def warn(self, where, problem, fix):
        self.warnings.append((where, problem, fix))


def check(lesson, sources=None, final=False, today=None):
    """Return (errors, warnings, summary). Each error and warning is (where, problem, fix).

    summary['verification'] is the block --build and --write sign into the lesson.
    """
    r = Report()
    today = today or datetime.date.today()
    if not isinstance(lesson, dict):
        r.error('The file', 'is not one JSON object.', 'Start the file with { and end it with }, like templates/video-lesson.json.')
        return r.errors, r.warnings, {}
    if sources is not None and not isinstance(sources, Sources):
        s = Sources({k: norm(v) for k, v in sources.items()})
        s.raw = dict(sources)
        sources = s
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
        r.error('"lessonType"', 'is missing.' if kind is None else f'is {kind!r}; it must be "concept" or "problem".', 'Set "lessonType": "problem" if the learner must solve problems with steps; otherwise "concept".')
    wpm = lesson.get('wpm')
    if not isinstance(wpm, (int, float)) or isinstance(wpm, bool) or not WPM_MIN <= wpm <= WPM_MAX:
        r.error('"wpm"', f'is {wpm!r}.', f'Set "wpm" to a number from {WPM_MIN} to {WPM_MAX}. Use 145 if unsure.')
        wpm = 145
    # Recorded clip lengths, written by video_voice.py. A length far shorter than the words could be said in is
    # refused, so a lesson cannot shrink its own running time.
    clip_seconds = {}
    audio = lesson.get('audio')
    if isinstance(audio, dict) and audio.get('seconds') is not None:
        said = {fnv1a(b['say']): b['say'] for sc in (lesson.get('scenes') if isinstance(lesson.get('scenes'), list) else [])
                if isinstance(sc, dict) for b in (sc.get('beats') if isinstance(sc.get('beats'), list) else [])
                if isinstance(b, dict) and isinstance(b.get('say'), str)}
        secs = audio['seconds']
        bad = [k for k, v in secs.items() if k in said and (isinstance(v, bool) or not isinstance(v, (int, float))
               or not spoken_words(said[k]) * 60.0 / CLIP_WPM_MAX <= v <= 120)] if isinstance(secs, dict) else ['all']
        if bad:
            r.error('"audio.seconds"', f'has {len(bad)} length(s) that do not fit their sentence: ' + ', '.join(map(str, bad[:5])) + '.',
                    'Do not write "audio.seconds" by hand. Run scripts/video_voice.py again; it measures every clip.')
        else:
            clip_seconds = {k: float(v) for k, v in secs.items() if k in said}
    if 'verification' in lesson:
        v = lesson['verification']
        if not isinstance(v, dict) or v.get('sha256') != sha256_of(lesson) or v.get('by') != 'video_check.py':
            r.error('"verification"', 'was not written by the checker for this exact file.',
                    'Delete the whole "verification" block. Only scripts/video_check.py writes it, with --build or --write.')
    part = lesson.get('part')
    if part is not None:
        ok = isinstance(part, dict) and isinstance(part.get('n'), int) and isinstance(part.get('of'), int) and 1 <= part['n'] <= part['of'] <= 12
        if not ok:
            r.error('"part"', 'must be {"n": 1, "of": 2, "series": "..."}.', 'Use whole numbers: "n" is this part, "of" is how many parts, and "series" names the whole topic.')
    pron = lesson.get('pronounce')
    if pron is not None:
        if not isinstance(pron, dict) or not all(isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip() for k, v in pron.items()):
            r.error('"pronounce"', 'must map words to respellings.', 'Write it like "pronounce": {"heterozygote": "hetero zygote", "allele": "a leel"}.')

    # Who it is for.
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
    elif lk == 'self-study':
        for key in ('purpose', 'level'):
            if not str(learner.get(key, '')).strip():
                r.error(f'learner.{key}', 'is empty.', 'Ask the learner, or write what they told you.' if key == 'purpose' else 'Write their level in plain words, for example "high school, no calculus".')
    elif learner:
        r.error('learner.kind', 'must be "course" or "self-study".', 'Use "course" when this is for a class; otherwise "self-study".')
    if words(learner.get('tag', '')) > 3:
        r.error('learner.tag', 'is more than 3 words.', 'Use a short tag such as "EXAM 4" or "MIDTERM".')
    if learner.get('checked') == 'yes':
        r.error('learner.checked', 'says "yes", but a lesson cannot mark itself checked.',
                'Delete "checked". The checker decides what was checked and writes it in "verification" when you run it with --sources.')

    # Calculations: every one recomputed here.
    calcs, calc_pool, calc_vals = {}, {}, {}
    raw_calc = lesson.get('calc')
    if raw_calc is not None and not isinstance(raw_calc, list):
        r.error('"calc"', 'must be a list.', 'Write "calc": [{"id": "k1", "expr": "2*90 + 80", "value": 260}].')
        raw_calc = []
    for i, k in enumerate(raw_calc or []):
        where = f'Calc {i + 1}'
        if not isinstance(k, dict):
            r.error(where, 'is not an object.', 'Write it as {"id": "k1", "expr": "...", "value": ...}.')
            continue
        kid = k.get('id')
        where = f'Calc {kid}' if isinstance(kid, str) else where
        if not isinstance(kid, str) or not CALC_ID.match(kid):
            r.error(where, 'needs an id of letters and digits that starts with a letter.', 'Use "id": "k1", "k2" and so on.')
            continue
        if kid in calcs:
            r.error(where, 'uses an id that is already taken.', 'Give every calc its own id.')
            continue
        expr, value = k.get('expr'), k.get('value')
        if not isinstance(expr, str) or not expr.strip():
            r.error(where, 'has no "expr".', 'Write the arithmetic, like "expr": "(2*90 + 80) / 400".')
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            r.error(where, 'has no number in "value".', 'Write the result as a number, like "value": 0.65.')
            continue
        if not re.search(r'[-+*/^×÷−]|sqrt|abs|[A-Za-z]', expr.strip().lstrip('-')):
            r.error(where, 'only restates a number.', 'A calc must compute something. A number taken from a source belongs in a claim\'s quote.')
            continue
        try:
            got = safe_eval(expr, calc_vals)
        except ValueError as exc:
            r.error(where, f'"expr" cannot be computed: {exc}.', 'Use only numbers, + - * / ^, brackets, sqrt() and ids of earlier calcs.')
            continue
        rd = k.get('round')
        if rd is not None and (not isinstance(rd, int) or isinstance(rd, bool) or not 0 <= rd <= 8):
            r.error(where, '"round" must be a whole number of decimal places from 0 to 8.', 'Write "round": 3 for three decimal places, or delete it.')
            rd = None
        if rd is None:
            s = repr(float(value))
            rd = len(s.split('.')[1]) if '.' in s and not s.endswith('.0') else 0
        if abs(round(got, rd) - value) > 10 ** (-rd) / 2 + 1e-9:
            shown = f'{round(got, rd):.{rd}f}' if rd else f'{round(got):d}'
            r.error(where, f'says {value}, but {expr} = {shown}.',
                    f'Set "value": {shown}, then change every sentence, pause and screen item that uses {value}.')
            got = value  # report the slip once; downstream numbers are checked against the stated value
        calcs[kid] = k
        calc_vals[kid] = got
        inputs = [n[0] for n in numbers_in(expr.replace('**', ' ').replace('^', ' '))]
        inputs += [calc_vals[n] for n in re.findall(r'[A-Za-z][A-Za-z0-9_]*', expr) if n in calc_vals]
        calc_pool[kid] = {'value': got, 'stated': float(value), 'inputs': inputs}

    # The claims ledger.
    claims = lesson.get('claims')
    ids = {}
    if not isinstance(claims, list) or not claims:
        r.error('"claims"', 'is empty.', 'Before writing narration, list each fact as a claim with id, text, source, where, file and an exact quote.')
        claims = []
    quoted, outside_n, course_n, conflicts, dismissed, stale = {}, 0, 0, set(), 0, 0
    for i, c in enumerate(claims):
        where = f'Claim {i + 1}'
        if not isinstance(c, dict):
            r.error(where, 'is not an object.', 'Write each claim as {"id": ..., "text": ..., ...}.')
            continue
        cid = str(c.get('id', '')).strip()
        where = f'Claim {cid or i + 1}'
        if not cid:
            r.error(where, 'has no id.', 'Give it "id": "c1", "c2" and so on.')
        elif cid in ids or cid in calcs:
            r.error(where, 'uses an id that is already taken.', 'Give every claim and calc its own id.')
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
            course_n += 1
            if c.get('where') and not re.search(r'\d', str(c['where'])):
                r.error(where, 'gives no page, slide or section number.', 'Add the number to "where", for example "Lecture 7, slide 12" or "Ch. 4, p. 112".')
        elif frm == 'outside':
            outside_n += 1
            if c.get('where') and not re.match(r'^https?://', str(c['where'])):
                r.error(where, 'is outside the course but "where" is not a web address.', 'Put the full https:// address of the page in "where". Use only a reliable source: a textbook, a university, a government agency or a journal.')
            if not DATE.match(str(c.get('checked', ''))):
                r.error(where, 'has no date checked.', 'Add "checked": "YYYY-MM-DD", the day you read the page.')
        elif isinstance(frm, str) and re.search(r'\.\w{1,5}$|^https?://', frm.strip()):
            r.error(where, f'"from" is {frm!r}, a file or address.',
                    'Write "from": "course" when it is one of the learner\'s files, or "from": "outside" for anything else. The file name goes in "file".')
        else:
            r.error(where, '"from" must be "course" or "outside".', 'Use "course" for the learner\'s own materials and "outside" for anything else.')
        if c.get('changes') is True or DATE.match(str(c.get('checked', ''))):
            if c.get('changes') is True and not (DATE.match(str(c.get('checked', ''))) and re.match(r'^https?://', str(c.get('where', '')))):
                r.error(where, 'changes over time but has no web address and date.', 'Give the https:// address in "where" and the day you read it in "checked".')
            elif DATE.match(str(c.get('checked', ''))):
                try:
                    age = (today - datetime.date.fromisoformat(c['checked'])).days
                except ValueError:
                    age = None
                    r.error(where, f'"checked" {c["checked"]!r} is not a real date.', 'Write the day you read the page as YYYY-MM-DD.')
                if age is not None and age > STALE_DAYS:
                    stale += 1
                    r.warn(where, f'was read {age} days ago.', 'Open the page again, confirm the quote is still there, and update "checked".')
                if age is not None and age < -1:
                    r.error(where, f'"checked" {c["checked"]} is in the future.', 'Write the day you actually read it.')
        status = c.get('status', 'unchecked')
        if status not in ('unchecked', 'matched', 'conflict'):
            r.error(where, f'has status {status!r}.', 'Use "unchecked", or "conflict" when two sources disagree.')
        nc = c.get('notConflict')
        if nc is not None:
            short = [x for x in (nc if isinstance(nc, list) else [nc]) if not isinstance(x, str) or len(norm(x).split()) < 5]
            if short:
                r.error(where, f'"notConflict" has {len(short)} entr{"y" if len(short) == 1 else "ies"} under 5 words.', 'Copy at least 5 words in a row from the flagged sentence, or delete the entry.')
        if status == 'conflict':
            conflicts.add(cid)
            if not str(c.get('note', '')).strip():
                r.error(where, 'is marked conflict with no note.', 'In "note", say what each source says and which one the course uses.')
            if not isinstance(c.get('other'), str):
                r.error(where, 'is marked conflict but does not name the other claim.', 'Add the other source\'s sentence as its own claim and set "other": "<its id>" here.')
        rv = c.get('review')
        if rv is not None:
            res = rv.get('result') if isinstance(rv, dict) else rv
            if res not in ('pass', 'fail'):
                r.error(where, '"review" must be "pass" or "fail".', 'Write what the second reader found: "review": "pass", or {"result": "fail", "note": "..."}.')
            elif res == 'fail':
                r.error(where, 'failed its independent review.', 'Fix the claim and every sentence that uses it, or delete them, then have it reviewed again.')
        if c.get('file') is not None and not isinstance(c.get('file'), str):
            r.error(where, '"file" must be one file name.', 'Write the name of one file given to --sources, like "file": "slides.md".')
        elif sources is not None and c.get('quote'):
            q = norm(c['quote'])
            fname = c.get('file')
            if not fname:
                r.error(where, 'does not name its file.', 'Add "file": the name of the source file the quote comes from (one of: ' + ', '.join(sorted(sources)[:6]) + ').')
            elif fname not in sources:
                r.error(where, f'names file {fname!r}, which was not given to --sources.', 'Give that file to --sources, or fix the file name.')
            elif not has(sources[fname], q):
                r.error(where, f'quote not found in {fname}.', f'Copy the exact sentence from {fname}, or delete the claim and every sentence that uses it.')
            elif len(q.split()) < 4:
                r.error(where, f'quote is only {len(q.split())} word(s), too short to show the source states the claim.', f'Copy the whole sentence from {fname} that states the claim: at least 4 words.')
            elif str(c.get('text', '')).strip() and not (stems(c['text']) & stems(c['quote'])):
                r.error(where, 'quote shares no key word with the claim\'s "text", so it does not state it.', 'Copy the sentence that says what "text" says, or rewrite "text" to say only what the quote says.')
            else:
                t = seconds_of(c.get('where', '')) if re.search(r'\d:\d\d', str(c.get('where', ''))) else None
                near = quote_near(sources.raw.get(fname, ''), q, t) if t is not None else None
                if near is False:
                    r.error(where, f'quote is not within {TIME_WINDOW} s of {c["where"]} in {fname}.', 'Find the quote in the transcript and copy the timestamp of the line where it is said.')
                else:
                    quoted[cid] = fname
            if cid in quoted and frm == 'course':
                pass
    # Conflict sweep: a sentence in the sources that says the opposite of a quoted claim must be flagged.
    flagged = {}
    if sources is not None and getattr(sources, 'raw', None):
        pool = []
        for name, raw in sources.raw.items():
            if timed_segments(raw):  # drop the timestamps, so a sentence can run across two lines
                raw = ' '.join(re.sub(r'^\s*\[?(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d+)?\]?\s*(?:-->\s*\S+\s*)?', '', ln) for ln in raw.splitlines())
            ss = sentences(raw)
            pool += [(name, s, (s,)) for s in ss] + [(name, a + ' ' + b, (a, b)) for a, b in zip(ss, ss[1:])]
        for cid, fname in quoted.items():
            c = ids[cid]
            if c.get('status') == 'conflict' or any(o.get('other') == cid for o in ids.values() if isinstance(o, dict)):
                continue
            nc = c.get('notConflict') or []
            dismiss = [d for d in (norm(x) for x in (nc if isinstance(nc, list) else [nc]) if isinstance(x, str)) if len(d.split()) >= 5]
            qn = norm(c['quote'])
            for name, s, parts in pool:
                # A sentence that is part of the quote itself (or holds all of it) is the claim's own source.
                if has(norm(s), qn) or all(has(qn, norm(x)) for x in parts):
                    continue
                if not disagrees(c['quote'] + ' ' + str(c.get('text', '')), s):
                    continue
                if any(has(norm(s), d) for d in dismiss):
                    dismissed += 1
                    continue
                flagged.setdefault(cid, (name, s))
        for cid, (name, s) in flagged.items():
            r.error(f'Claim {cid}', f'is contradicted by {name}: "{s[:160]}".',
                    f'Add that sentence as its own claim (exact quote, "file": "{name}"), set "status": "conflict", "other": "{cid}" and a "note" on it, '
                    'and add a beat that cites both ids and says which one the course uses, for example "Your slides say X. Your notes say Y. Ask your professor which the exam uses."')
    for cid in conflicts:
        o = ids[cid].get('other')
        if isinstance(o, str) and o not in ids:
            r.error(f'Claim {cid}', f'"other" names {o!r}, which is not a claim.', 'Set "other" to the id of the claim it disagrees with.')

    used = set()
    cited_pairs = []

    def need_claims(where, ref_list, required, what):
        """Check a list of claim and calc ids; return the valid ones."""
        if ref_list is None:
            ref_list = []
        if not isinstance(ref_list, list):
            r.error(where, '"claims" must be a list.', 'Write it like "claims": ["c1"].')
            return []
        good = []
        for ref in ref_list:
            if not isinstance(ref, str):
                r.error(where, f'"claims" holds {json.dumps(ref)[:40]}, not an id.', 'List claim ids as text, like "claims": ["c3"].')
                continue
            if ref not in ids and ref not in calcs:
                r.error(where, f'cites {ref!r}, which is not in "claims" or "calc".', f'Use an id from "claims" or "calc", or add {ref!r} with its source and quote first.')
                continue
            used.add(ref)
            good.append(ref)
        if required and not ref_list:
            r.error(where, f'{what} has no claim ids.', 'Add the id of the claim or calc that supports it, such as "claims": ["c3"].')
        return good

    def backing(refs):
        pool = []
        for ref in refs:
            if ref in ids:
                q = str(ids[ref].get('quote', ''))
                pool += [n[0] for n in numbers_in(q)]
                pool += [n[0] / 100 for n in numbers_in(q) if n[2]]
                pool += [float(m) for m in re.findall(r'(?<![\w.])(\d+(?:\.\d+)?)(?=[A-Za-z])', q)]  # "2pq" backs 2
            elif ref in calc_pool:
                k = calc_pool[ref]
                pool += [k['value'], k['stated']] + k['inputs']
        return pool

    taken_ids = set(calcs) | set(ids)

    def new_calc_id():
        n = 1
        while f'k{n}' in taken_ids:
            n += 1
        taken_ids.add(f'k{n}')
        return f'k{n}'

    def numbers_ok(where, text, refs, what):
        """One problem per text, listing every number nothing backs, with calc lines to paste where
        two of the text's own numbers (or a cited source's) give it by + - * /."""
        pool = backing(refs)
        nums = numbers_in(text)
        bad = [n for n in nums if not backs(n, pool)]
        if not bad:
            return
        cands = list(dict.fromkeys([n[0] for n in nums] + [n[0] / 100 for n in nums if n[2]] + pool))[:30]
        covered, lines, kids, left = list(pool), [], [], []
        for n in bad:
            if backs(n, covered):
                continue
            hit = None
            for a in cands:
                for b in cands:
                    for sym, f in (('+', operator.add), ('-', operator.sub), ('*', operator.mul), ('/', operator.truediv)):
                        if (sym in '*/' and b in (0, 1)) or (sym in '+-' and b == 0) or backs(n, [a]) or backs(n, [b]):
                            continue
                        v = f(a, b)
                        if backs(n, [v]):
                            hit = (a, sym, b, v)
                            break
                    if hit:
                        break
                if hit:
                    break
            if hit:
                a, sym, b, v = hit
                kid = new_calc_id()
                kids.append(f'"{kid}"')
                num = lambda x: f'{x:g}'
                lines.append(f'{{"id": "{kid}", "expr": "{num(a)} {sym} {num(b)}", "value": {num(round(v, 6))}}}')
                covered += [a, b, v]
            else:
                left.append(n[4])
        shown = ', '.join(repr(n[4]) for n in bad)
        fix = []
        if lines:
            fix.append('Add to "calc": ' + ', '.join(lines) + '. Then add ' + ', '.join(kids) + ' to its "claims".')
        if left:
            fix.append(f'For {", ".join(map(repr, left))}: cite the claim whose quote has it. If it is a number you chose for an example, '
                       'put it in a calc that works the example, like {"id": "k9", "expr": "2*6 + 7", "value": 19}, and cite that. If it is wrong, fix it.')
        r.error(where, f'{what} states {shown}, which no cited quote or calc gives.', ' '.join(fix))

    ex_runs, ex_files, ex_topic = example_runs()
    copy_check = bool(sources) and ex_runs and not (set(sources) & ex_files)
    src_runs_text = [' ' + ' '.join(re.findall(r"[a-z0-9']+", str(getattr(sources, 'raw', {}).get(k, v)).lower())) + ' '
                     for k, v in (sources or {}).items()] if copy_check else []
    src_words = set(' '.join(src_runs_text).split())

    def copied(where, text):
        """A small model copies the worked example's sentences into other topics. Flag a run of words
        from the example that the learner's materials never use."""
        if not copy_check:
            return
        hit = next((run for run in sorted(_runs(text) & ex_runs)
                    if set(run.split()) & ex_topic - src_words and not any(f' {run} ' in src for src in src_runs_text)), None)
        if hit:
            r.error(where, f'copies the worked example about the sky ("{hit}"), and your materials never say it.',
                    'Delete it. Write only about your own topic, from the learner\'s files.')

    def coverage(where, text, refs):
        st = stems(text)
        nums = numbers_in(text)
        for ref in refs:
            if ref in ids:
                c = ids[ref]
                key = stems(c.get('quote', '')) | stems(c.get('text', ''))
                cn = backing([ref])
                if not (st & key) and not any(backs(n, cn) for n in nums):
                    sample = ', '.join(sorted(key)[:4]) or '?'
                    r.error(where, f'cites {ref}, but shares no key word with it ({sample}).',
                            f'Cite the claim this sentence actually states, or say the fact in the claim\'s own words.')
            elif ref in calc_pool:
                if not any(backs(n, backing([ref])) for n in nums):
                    r.error(where, f'cites calc {ref}, but says none of its numbers.', 'Say the result or an input of that calc in this sentence, or cite the calc it uses.')

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
        shown, scene_seconds, scene_words, has_show, scene_pause, table_cols = [], 0.0, 0, False, False, None
        cols_at = {}  # the beat where each half of a two-column screen first gets something
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
                refs = need_claims(where, p.get('claims'), True, 'The pause answer')
                ptext = ' '.join(str(p.get(k, '')) for k in ('ask', 'answer', 'why')) + ' ' + ' '.join(map(str, ch if isinstance(ch, list) else []))
                numbers_ok(where, ptext, refs, 'The pause')
                coverage(where, ptext, refs)
                copied(where, ptext)
                ans = norm(p.get('answer', ''))
                if ans and (re.search(r'\d', ans) or len(ans.split()) >= 2 or len(ans) >= 4):
                    if any(has(s, ans) for s in shown):
                        r.error(where, f'asks for "{p.get("answer")}", which is already on screen in this scene.',
                                'Move the pause before the beat that shows the answer (ask the learner to predict), or show that item after the pause.')
                if len(conflicts & set(refs)) and not any(ids[x].get('other') in refs for x in conflicts & set(refs)):
                    pass
                cited_pairs.append(set(refs))
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
            sym = re.search(r'[\^_=<>≥≤±√∑×÷/*]|\b[a-z]\d\b|\(\s*[a-z]\s*\)', say)
            if sym:
                r.error(where, f'asks the voice to read the symbol {sym.group(0)!r}.',
                        'Write it the way you would say it: "p squared", "equals", "divided by", "v sub zero". Put the symbols on screen in an "equation".')
            copied(where, say)
            talk = beat.get('talk') is True
            refs = []
            if talk:
                if numbers_in(say):
                    r.error(where, 'is marked "talk" but has a number in it.', 'Numbers are facts: remove "talk": true and add "claims" with the id that supports the number.')
                if beat.get('claims'):
                    refs = need_claims(where, beat.get('claims'), False, 'This sentence')
            else:
                refs = need_claims(where, beat.get('claims'), True,
                                   'This sentence (if it is only a question, an instruction or a transition, add "talk": true instead)')
                numbers_ok(where, say, refs, 'The sentence')
                coverage(where, say, refs)
            cited_pairs.append(set(refs))
            scene_seconds += beat_seconds(beat, wpm, clip_seconds)
            gap += beat_seconds(beat, wpm, clip_seconds)
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
                if t not in ('row', 'highlight'):
                    cols_at.setdefault(t in BOARD_VISUAL, bi)
                if t == 'term' and si < 2:
                    first_terms = True
                required = {'title': ('text',), 'question': ('text',), 'term': ('word', 'meaning'), 'label': ('text',),
                            'equation': ('text',), 'step': ('text',), 'arrow': ('from', 'to'), 'highlight': ('target',),
                            'graph': ('points', 'x', 'y'), 'image': ('src', 'alt', 'credit', 'license'),
                            'compare': ('left', 'right', 'leftItems', 'rightItems'), 'quote': ('text', 'claim'),
                            'table': ('columns', 'rows'), 'row': ('cells',), 'bars': ('items',)}[t]
                for key in required:
                    if el.get(key) in (None, '', []) and not (t == 'table' and key == 'rows' and el.get(key) == []):
                        r.error(ew, f'{t} has no "{key}".', f'Add "{key}". A {t} needs: ' + ', '.join(required) + '.')
                if 'tier' in el:
                    if t not in ('term', 'equation', 'label', 'step'):
                        r.error(ew, f'a {t} cannot have "tier".', 'Put "tier" only on a term, equation, label or step.')
                    elif el['tier'] not in TIERS:
                        r.error(ew, f'"tier" is {el["tier"]!r}.', 'Use "memorize" (not given on the exam) or "given" (on the formula sheet), or delete it.')
                el_refs = refs + (need_claims(ew, el.get('claims'), False, 'This item') if t in ('equation', 'graph', 'table', 'bars', 'row') else [])
                if t == 'graph':
                    need_claims(ew, el.get('claims'), True, 'The graph data')
                for key, text in element_texts(el):
                    limit = LIMITS.get(key)
                    if limit and screen_words(text) > limit:
                        r.error(ew, f'{key.replace(".", " ")} has {screen_words(text)} words on screen.', f'Cut it to {limit} words or fewer. The narration says the sentence; the screen shows key words.')
                    if words(text) >= 5 and norm(text) and norm(text) in norm(say) and t != 'quote':
                        r.error(ew, 'repeats the narration word for word.', 'Show 2 to 6 key words instead of the sentence being spoken.')
                    scene_words += screen_words(text)
                    copied(ew, text)
                    if t not in ('quote', 'image'):
                        numbers_ok(ew, text if key != 'bars.value' else text, el_refs, 'The screen')
                if t == 'compare':
                    for side in ('leftItems', 'rightItems'):
                        if not isinstance(el.get(side), list) or len(el.get(side) or []) > 4:
                            r.error(ew, f'"{side}" must be a list of 1 to 4 short items.', 'Keep 1 to 4 items on each side.')
                if t == 'table':
                    cols, rows = el.get('columns'), el.get('rows')
                    if not isinstance(cols, list) or not 2 <= len(cols) <= 5:
                        r.error(ew, 'table "columns" must list 2 to 5 headings.', 'Write 2 to 5 short column headings.')
                        table_cols = None
                    else:
                        table_cols = len(cols)
                        if not isinstance(rows, list) or len(rows) > 6 or any(not isinstance(x, list) or len(x) != len(cols) for x in rows):
                            r.error(ew, f'table "rows" must be up to 6 rows of {len(cols)} cells each.', f'Write each row as a list of {len(cols)} cells. Add rows one beat at a time with {{"type": "row", "cells": [...]}}.')
                if t == 'row':
                    cells = el.get('cells')
                    if table_cols is None:
                        r.error(ew, 'adds a row, but no table is on screen in this scene.', 'Show a {"type": "table", "columns": [...], "rows": []} in an earlier beat of this scene.')
                    elif not isinstance(cells, list) or len(cells) != table_cols:
                        r.error(ew, f'row must have {table_cols} cells, one per column.', f'Write "cells" with exactly {table_cols} items.')
                if t == 'bars':
                    items = el.get('items')
                    if not isinstance(items, list) or not 2 <= len(items) <= 6 or any(
                            not isinstance(it, dict) or not str(it.get('label', '')).strip() or not isinstance(it.get('value'), (int, float)) or isinstance(it.get('value'), bool) or it.get('value') < 0
                            for it in items):
                        r.error(ew, 'bars "items" must be 2 to 6 {"label": ..., "value": number} entries.', 'Write each bar as {"label": "red", "value": 49}. Values are numbers of zero or more.')
                    need_claims(ew, el.get('claims'), not refs, 'The bar values')
                if t == 'graph':
                    pts = el.get('points')
                    ok = isinstance(pts, list) and len(pts) >= 2 and all(
                        isinstance(pt, list) and len(pt) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in pt) for pt in pts)
                    if not ok:
                        r.error(ew, 'graph "points" must be [[x, y], ...] with at least 2 number pairs.', 'Write numbers only, like [[0, 1], [1, 3], [2, 9]]. Work each one out; never guess.')
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
                    elif not has(norm(ids[cid].get('quote', '')), norm(el.get('text', ''))):
                        r.error(ew, 'quote text is not in its claim\'s quote.', 'Copy the words exactly from that claim\'s "quote". Never change a quotation.')
                    if isinstance(cid, str):
                        used.add(cid)
                if t == 'highlight':
                    target = norm(el.get('target', ''))
                    if target and target not in shown:
                        r.error(ew, f'highlights {el.get("target")!r}, which is not on screen in this scene yet.', 'Set "target" to the exact text of something shown earlier in this scene (a term word, label, step, or compare item).')
                for key, text in element_texts(el):
                    shown.append(norm(text))
        if len(cols_at) == 2 and len(beats) >= 4 and not all(isinstance(b, dict) and all(isinstance(e, dict) and e.get('type') in ('title', 'question') for e in (b.get('show') or [])) for b in beats):
            late = max(cols_at.values())
            if late >= len(beats) / 2:
                what = 'chart, table or equation' if cols_at[True] == late else 'word or step'
                r.warn(sname, f'leaves half the screen empty until beat {late + 1} of {len(beats)}, when its first {what} appears.',
                       f'Show that {what} earlier, or move it and its sentences into a scene of their own.')
        if scene_seconds > SCENE_MAX_SECONDS:
            r.error(sname, f'runs {scene_seconds / 60:.1f} minutes.', 'Split it into two scenes of 6 minutes or less.')
        if scene_words > SCREEN_WORDS_MAX:
            r.error(sname, f'puts {scene_words} words on screen.', f'Cut the screen text to {SCREEN_WORDS_MAX} words or fewer: key words only, one idea at a time.')
        elif scene_words > SCREEN_WORDS_WARN:
            r.warn(sname, f'puts {scene_words} words on screen.', f'Aim for {SCREEN_WORDS_WARN} or fewer.')
        if not has_show:
            r.warn(sname, 'shows nothing on screen.', 'Add one visual for this scene: a term, label, step, table, bars, arrow, graph or compare.')
        if role == 'faded' and not scene_pause:
            r.error(sname, 'is a faded example with no pause.', 'In a faded example the learner does a step: add a pause beat that asks for it.')
        total += scene_seconds
    if gap > PAUSE_GAP_MAX:
        r.error('The last scenes', f'run {gap:.0f} s after {gap_from} with no pause question.', 'Add a pause beat in the last scene.')
    if total > VIDEO_MAX_SECONDS:
        r.error('The video', f'runs {total / 60:.1f} minutes of narration.',
                'Split it into parts of 6 minutes or less: move the later scenes into a second lesson file, and set "part": {"n": 1, "of": 2, "series": "<topic>"} in each.')
    elif total > VIDEO_WARN_SECONDS:
        r.warn('The video', f'runs {total / 60:.1f} minutes of narration.', 'Six minutes or less holds attention best. Consider splitting it into parts.')
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
            refs = need_claims('"misconception"', mis.get('claims'), True, 'The correction')
            numbers_ok('"misconception"', str(mis.get('right', '')), refs, 'The correction')
        if 'misconception' not in roles:
            r.error('"misconception"', 'is never taught.', 'Add a scene with "role": "misconception" that names the mistake and corrects it.')
    else:
        r.warn('"misconception"', 'is missing.', 'If you know a common mistake on this topic (or the learner made one), add it and a scene that corrects it.')
    rec = lesson.get('recall')
    if not isinstance(rec, dict) or not str(rec.get('ask', '')).strip() or not isinstance(rec.get('points'), list) or not 1 <= len(rec['points']) <= 5:
        r.error('"recall"', 'is missing or incomplete.', 'Add "recall": {"ask": "Look away and explain ...", "points": ["...", "..."]} with 1 to 5 points.')
    else:
        numbers_ok('"recall"', ' '.join(map(str, rec['points'])), list(ids) + list(calc_pool), 'A recall point')
    pr = lesson.get('practice')
    if not isinstance(pr, dict) or not str(pr.get('ask', '')).strip() or not str(pr.get('answer', '')).strip():
        r.error('"practice"', 'is missing or incomplete.', 'Add "practice": {"ask": ..., "answer": ..., "steps": [...], "claims": [...]}: one new problem like the one taught.')
    else:
        refs = need_claims('"practice"', pr.get('claims'), True, 'The practice answer')
        steps = pr.get('steps') if isinstance(pr.get('steps'), list) else []
        numbers_ok('"practice"', ' '.join([str(pr.get('ask', '')), str(pr.get('answer', ''))] + [str(s) for s in steps]), refs, 'The practice problem')
        if kind == 'problem' and not steps:
            r.error('"practice"', 'has no steps.', 'List the solution steps in "steps" so the learner can check each one.')
    for cid in conflicts:
        o = ids[cid].get('other')
        if isinstance(o, str) and o in ids and not any(cid in s and o in s for s in cited_pairs):
            r.error(f'Claim {cid}', f'disagrees with {o}, but no beat cites both.',
                    f'Add a beat with "claims": ["{cid}", "{o}"] that says what each source says and which one the course uses.')
    for cid in ids:
        if cid and cid not in used and not any(ids[x].get('other') == cid for x in conflicts):
            r.warn(f'Claim {cid}', 'is never used.', 'Use it in a sentence, or delete it.')
    for kid in calcs:
        if kid not in used and not any(re.search(rf'\b{re.escape(kid)}\b', str(k.get('expr', ''))) for k in calcs.values()):
            r.warn(f'Calc {kid}', 'is never cited.', 'Cite it in the sentence or screen item that uses its number, or delete it.')
    if scenes and total < 45:
        r.warn('The video', f'is only {total:.0f} s of narration.', 'Check that every objective is taught.')
    # Audio clips that no longer match their sentence must not play.
    audio = lesson.get('audio')
    if isinstance(audio, dict) and isinstance(audio.get('clips'), dict):
        keys = {fnv1a(b['say']) for s in scenes if isinstance(s, dict) for b in (s.get('beats') if isinstance(s.get('beats'), list) else [])
                if isinstance(b, dict) and isinstance(b.get('say'), str)}
        stale_clips = sorted(k for k in audio['clips'] if k not in keys)
        if stale_clips:
            r.error('"audio.clips"', f'has {len(stale_clips)} clip(s) for sentences that changed: ' + ', '.join(stale_clips[:5]) + '.', 'Run scripts/video_voice.py again; it remakes only the changed clips.')
        missing = sorted(keys - set(audio['clips']))
        if missing:
            r.warn('"audio.clips"', f'is missing {len(missing)} clip(s).', 'Those sentences use the browser voice until you add clips.')
        voice = audio.get('voice')
        if audio['clips'] and not (isinstance(voice, dict) and str(voice.get('disclose', '')).strip()):
            r.error('"audio.voice"', 'does not disclose the AI voice.', 'Run scripts/video_voice.py, which writes "voice": {"engine", "name", "disclose"}; or write "disclose": "Narration is an AI voice: <model> (<voice>)."')

    # Review of what code cannot check.
    review = lesson.get('review')
    reviewed = False
    if review is not None:
        if not isinstance(review, dict) or not str(review.get('by', '')).strip() or not DATE.match(str(review.get('date', ''))) or review.get('result') not in ('pass', 'fail'):
            r.error('"review"', 'must be {"by": ..., "date": "YYYY-MM-DD", "result": "pass" or "fail", "notes": ...}.', 'Record who reviewed the explanations, when, and what they found.')
        elif review['result'] == 'fail':
            r.error('"review"', 'failed.', 'Fix what the reviewer found, then have it reviewed again.')
        else:
            reviewed = True
    if final:
        if sources is None:
            r.error('--final', 'needs --sources.', 'Give the source files with --sources so every quote can be matched.')
        if not reviewed:
            r.error('"review"', 'is missing.', 'Do step 6: a second reader checks the explanations, pause answers and practice answer, then record "review".')

    # The badge. Only this code decides it.
    n_claims = len(ids)
    n_quoted = len(quoted)
    lines = []
    if sources is None:
        level, label = 'unverified', 'Unverified: no quote was matched to a source file'
    elif lk == 'course':
        course_quoted = sum(1 for cid in quoted if ids[cid].get('from') == 'course')
        if outside_n == 0 and course_quoted == course_n and course_n:
            level, label = 'checked', f'Checked against your course: {course_quoted} of {course_n} claims quoted'
        elif course_quoted:
            level, label = 'partial', f'Checked against your course: {course_quoted} of {course_n} course claims quoted'
            lines.append(f'Not checked against your course: {outside_n} claim{"s" if outside_n != 1 else ""} from outside sources')
        else:
            level, label = 'partial', f'Not checked against your course: {outside_n} claims from outside sources'
    else:
        level = 'checked' if n_quoted == n_claims and n_claims else 'partial'
        label = f'Checked against its sources: {n_quoted} of {n_claims} claims quoted'
    if calcs:
        lines.append(f'Every number recomputed by code: {len(calcs)} calculation{"s" if len(calcs) != 1 else ""}')
    if conflicts:
        lines.append(f'Sources disagree on {len(conflicts)} point{"s" if len(conflicts) != 1 else ""}: flagged in the video')
    if dismissed:
        lines.append(f'{dismissed} possible contradiction{"s" if dismissed != 1 else ""} dismissed by the writer')
    lines.append(f'Explanations reviewed by {review["by"]} (as recorded)' if reviewed else 'Explanations not independently reviewed')
    if stale:
        lines.append(f'{stale} source{"s" if stale != 1 else ""} read over a year ago')
    verification = {'by': 'video_check.py', 'version': VERSION, 'date': today.isoformat(), 'level': level, 'label': label,
                    'lines': lines, 'claims': {cid: ('quoted' if cid in quoted else 'not matched') for cid in ids if cid},
                    'sha256': ''}
    # The hash has no key, so anyone can recompute it. With the sources in hand, refuse a block that claims
    # more than this check finds, so a hand-made "checked" block fails here even when its hash matches.
    old = lesson.get('verification')
    if sources is not None and isinstance(old, dict) and old.get('sha256') == sha256_of(lesson):
        differs = [k for k in ('level', 'label', 'claims') if old.get(k) != verification[k]]
        if differs:
            r.error('"verification"', f'says {", ".join(differs)} other than this check finds ({level}: {label}).',
                    'Delete the whole "verification" block, then sign the lesson again with --write or --build.')
    summary = {'seconds': round(total), 'pauses': pauses, 'scenes': len(scenes), 'claims': n_claims,
               'claims_checked': n_quoted, 'calcs': len(calcs), 'verification': verification}
    return r.errors, r.warnings, summary


def sign(lesson, verification):
    """Return a copy of the lesson carrying the verification block, hashed over everything else."""
    out = {k: v for k, v in lesson.items() if k != 'verification'}
    v = dict(verification)
    v['sha256'] = sha256_of(out)
    out['verification'] = v
    return out


class _Unfixable(Exception):
    pass


class _Loose:
    """A forgiving JSON reader for the slips small models make. It repairs only what has one reading:
    a comma before } or ], a doubled comma, a stray ", after a value, a missing comma between items, a { or [ left open, a doubled
    closing quote, a line break inside text, and words before or after the object. Anything else is unfixable."""

    NUM = re.compile(r'-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?')

    def __init__(self, text):
        self.t, self.i, self.fixes, self.closers = text, 0, [], []

    def fix(self, what, at=None):
        self.fixes.append(f'line {self.t.count(chr(10), 0, self.i if at is None else at) + 1}: {what}')

    def peek(self):
        while self.i < len(self.t) and self.t[self.i] in ' \t\r\n':
            self.i += 1
        return self.t[self.i] if self.i < len(self.t) else ''

    def value(self):
        c = self.peek()
        if c == '{':
            return self.obj()
        if c == '[':
            return self.arr()
        if c == '"':
            return self.string()
        for word, val in (('true', True), ('false', False), ('null', None)):
            if self.t.startswith(word, self.i):
                self.i += len(word)
                return val
        m = self.NUM.match(self.t, self.i)
        if m:
            self.i = m.end()
            return json.loads(m.group())
        raise _Unfixable

    def string(self):
        start, self.i, buf = self.i, self.i + 1, []
        while True:
            if self.i >= len(self.t):
                raise _Unfixable
            ch = self.t[self.i]
            if ch == '\\' and self.i + 1 < len(self.t):
                buf.append(self.t[self.i:self.i + 2])
                self.i += 2
                continue
            if ch == '\n':
                self.fix('a line break inside text became a space', start)
                buf.append(' ')
                self.i += 1
                continue
            self.i += 1
            if ch == '"':
                break
            buf.append(ch)
        try:
            return json.loads('"' + ''.join(buf) + '"')
        except json.JSONDecodeError:
            raise _Unfixable

    def after_value(self, closer):
        """After an item: True when another item follows."""
        c = self.peek()
        if c == ',':
            self.i += 1
            while self.peek() == ',':
                self.fix('removed a doubled ,')
                self.i += 1
            # In an object a key comes next, so "x",", "k" has a stray ", (a key never reads ", ").
            if closer == '}' and re.match(r'",\s*"(?!\s*:)', self.t[self.i:self.i + 40]):
                self.fix('removed a stray ",')
                self.i += 2
                self.peek()
            if self.peek() in '}]':
                self.fix('removed a comma before ' + self.peek())
                return False
            return True
        if c == '"' and closer == '}':
            j = self.i + 1
            while j < len(self.t) and self.t[j] in ' \t':
                j += 1
            if j < len(self.t) and self.t[j] in ',}]\r\n':
                self.fix('removed a doubled "')
                self.i += 1
                return self.after_value(closer)
        if c in '"{[' or (c and (c.isdigit() or c == '-')):
            self.fix('added a missing comma')
            return True
        return False

    def obj(self):
        self.i += 1
        out = {}
        while True:
            c = self.peek()
            if c == '}':
                self.closers.append(self.i)
                self.i += 1
                return out
            if c in ']{' or not c:
                self.fix('closed a { left open with }')
                return out
            if c != '"':
                raise _Unfixable
            key = self.string()
            if self.peek() != ':':
                raise _Unfixable
            self.i += 1
            out[key] = self.value()
            if not self.after_value('}') and self.peek() not in '}]{':
                raise _Unfixable

    def arr(self):
        self.i += 1
        out = []
        while True:
            c = self.peek()
            if c == ']':
                self.closers.append(self.i)
                self.i += 1
                return out
            if c == '}' or not c:
                self.fix('closed a [ left open with ]')
                return out
            out.append(self.value())
            if not self.after_value(']') and self.peek() not in ']}':
                raise _Unfixable


def _parse_loose(text, a):
    """(object, fixes, closers, stop). On a clean read the object and its fixes; otherwise None, the
    structural } and ] read before it stopped, and how far it got."""
    p = _Loose(text)
    p.i = a
    try:
        obj = p.obj()
    except (_Unfixable, RecursionError):
        return None, None, p.closers, p.i
    rest = re.sub(r'</?[A-Za-z_][^>]*>', '', text[p.i:]).strip()
    if rest and not re.match(r'[A-Za-z#*>`]', rest):
        return None, None, p.closers, p.i  # more JSON after the object: a } or ] closed it too early
    if text[:a].strip():
        p.fixes.insert(0, 'removed words before the first {')
    if text[p.i:].strip():
        p.fixes.append('removed words after the last }')
    return obj, p.fixes, None, len(text)


def repair_json(text, tries=12, window=40):
    """(object, fixes) when the text is one JSON object with slips that have a single reading, else None.
    When reading stops, it tries removing one extra } or ] that it had read as structure, or the one
    where it stopped (never a character inside text). It keeps a removal that reads the whole object with the fewest repairs, or
    else the one that reads farthest, and removes at most `tries` in all."""
    a = text.find('{')
    if a < 0:
        return None
    removed = []
    for _ in range(tries + 1):
        obj, fixes, closers, stop = _parse_loose(text, a)
        if obj is not None:
            return obj, [f'line {n}: removed an extra {c}' for n, c in removed] + fixes
        if len(removed) == tries:
            return None
        best = None
        # The } or ] where reading stopped is a candidate too: one too many right after a close.
        here = [stop] if stop < len(text) and text[stop] in '}]' else []
        for j in here + sorted(closers, reverse=True)[:window]:
            cand = text[:j] + text[j + 1:]
            o, f, _, far = _parse_loose(cand, a)
            score = (0, len(f)) if o is not None else (1, -far)
            if far > stop and (best is None or score < best[0]):
                best = (score, j, cand)
        if best is None:
            return None
        removed.append((text.count('\n', 0, best[1]) + 1, text[best[1]]))
        text = best[2]
    return None


def tidy(lesson, sources=None):
    """Fix in place the slips that have one right answer, and return what changed. The check then
    judges the result like any other file. A small model makes these often and can rarely fix them
    from a report: a beat that only shows something, a file name one slip off a given file, a file
    name written in "from", a claim or calc id like (k1) in narration, and a spaced = in narration."""
    done = []
    if not isinstance(lesson, dict):
        return done
    names = list(sources or {})
    for c in lesson.get('claims') if isinstance(lesson.get('claims'), list) else []:
        if not isinstance(c, dict):
            continue
        cid = c.get('id', '?')
        f = c.get('file')
        if names and isinstance(f, str) and f not in names:
            close = difflib.get_close_matches(f, names, n=2, cutoff=0.8)
            if len(close) == 1:
                c['file'] = close[0]
                done.append(f'claim {cid}: "file" {f!r} is now {close[0]!r}, the given file it was close to')
        frm = c.get('from')
        if isinstance(frm, str) and frm not in ('course', 'outside') and re.search(r'\.\w{1,5}$|^https?://', frm.strip()):
            c['from'] = 'outside' if re.match(r'^https?://', str(c.get('where', ''))) else 'course'
            done.append(f'claim {cid}: "from" was {frm!r}, a file name; it is now "{c["from"]}" (from its "where")')
    for si, scene in enumerate(lesson.get('scenes') if isinstance(lesson.get('scenes'), list) else [], 1):
        beats = scene.get('beats') if isinstance(scene, dict) else None
        if not isinstance(beats, list):
            continue
        out = []
        for bi, b in enumerate(beats, 1):
            if (isinstance(b, dict) and set(b) <= {'show', 'claims'} and isinstance(b.get('show'), list)):
                host = None
                for x in reversed(out):  # never back past a pause: a reveal after a question stays after it
                    if isinstance(x, dict) and 'pause' in x:
                        break
                    if isinstance(x, dict) and 'say' in x:
                        host = x
                        break
                if host is None:
                    host = next((x for x in beats[bi:] if isinstance(x, dict) and 'say' in x), None)
                if host is not None:
                    host['show'] = (host.get('show') if isinstance(host.get('show'), list) else []) + b['show']
                    extra = [x for x in b.get('claims') or [] if isinstance(x, str) and x not in (host.get('claims') or [])]
                    if extra:
                        host['claims'] = list(host.get('claims') or []) + extra
                    done.append(f'scene {si}, beat {bi}: it only showed something, so it now shows with the sentence beside it')
                    continue
            ids_said = r'\s*\((?:[ck]\d+)(?:\s*,\s*[ck]\d+)*\)'
            if isinstance(b, dict) and isinstance(b.get('say'), str) and re.search(ids_said, b['say']):
                b['say'] = re.sub(ids_said, '', b['say'])
                done.append(f'scene {si}, beat {bi}: claim or calc ids like (k1) were in the narration; they belong in "claims" and are gone')
            if isinstance(b, dict) and isinstance(b.get('say'), str) and re.search(r'\s=\s', b['say']):
                b['say'] = re.sub(r'\s=\s', ' equals ', b['say'])
                done.append(f'scene {si}, beat {bi}: " = " in the narration now reads "equals"')
            out.append(b)
        scene['beats'] = out
    return done


def dump_lesson(lesson):
    """The lesson as JSON in the template's shape: short values on one line, and one claim, calc or beat per line."""
    def fmt(v, ind, one_line_items=False):
        s = json.dumps(v, ensure_ascii=False)
        if len(s) <= 100 or not isinstance(v, (dict, list)) or not v:
            return s
        pad = ' ' * (ind + 2)
        if isinstance(v, list):
            items = (json.dumps(x, ensure_ascii=False) if one_line_items else fmt(x, ind + 2) for x in v)
            return '[\n' + ',\n'.join(pad + x for x in items) + '\n' + ' ' * ind + ']'
        return ('{\n' + ',\n'.join(pad + json.dumps(k, ensure_ascii=False) + ': ' + fmt(x, ind + 2, k in ('beats', 'claims', 'calc'))
                                     for k, x in v.items()) + '\n' + ' ' * ind + '}')
    return fmt(lesson, 0) + '\n'


def read_lesson(path):
    """Load the lesson, tolerating a ```json fence around it and repairing slips that have one reading.
    A repaired file is saved back so the next draft starts from valid JSON. Returns (lesson, note) or raises SystemExit(2)."""
    text = Path(path).read_text()
    note = None
    fenced = re.match(r'^\s*```[a-zA-Z]*\s*\n(.*?)\n\s*```\s*$', text, re.S)
    if fenced:
        text, note = fenced.group(1), 'The file was wrapped in ``` marks; they were ignored. Save only the JSON next time.'
    try:
        return json.loads(text), note
    except json.JSONDecodeError as exc:
        fixed = repair_json(text)
        if fixed and isinstance(fixed[0], dict):
            lesson, fixes = fixed
            Path(path).write_text(dump_lesson(lesson))
            shown = '; '.join(fixes[:8]) + (f'; and {len(fixes) - 8} more' if len(fixes) > 8 else '')
            return lesson, (f'The file was not valid JSON. Repaired and saved it ({shown}). '
                            'Read the saved file and check every beat is where you meant it.')
        # Quote the text around the exact spot: a long line cut at its start hides the slip.
        before = text[max(0, exc.pos - 70):exc.pos].replace('\n', ' ')
        after = text[exc.pos:exc.pos + 50].replace('\n', ' ')
        print(f'NOT VALID JSON: line {exc.lineno}, column {exc.colno}: {exc.msg}.')
        print(f'  The slip is at >>> : ...{before}>>> {after}...')
        print('FIX: change the text at >>> . The usual causes:')
        print('  1. A missing comma between two items or two "key": value pairs.')
        print('  2. A comma right before ] or }. Delete it.')
        print('  3. A " inside text. Replace it with \' .')
        print('  4. A comment (// or #) or your own notes. JSON has no comments. Delete them.')
        print('  5. Two values for one key, like "type": "title": {...}. Each key holds one value: "type": "title", "text": "...".')
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


def speakable(text, pronounce):
    """The words a voice engine should read: each "pronounce" key swapped for its respelling, whole words, any case."""
    if not isinstance(pronounce, dict):
        return text
    for k in sorted((k for k, v in pronounce.items() if isinstance(k, str) and k.strip() and isinstance(v, str)), key=len, reverse=True):
        text = re.sub(r'(?<![A-Za-z0-9])' + re.escape(k.strip()) + r'(?![A-Za-z0-9])', lambda m, v=pronounce[k].strip(): v, text, flags=re.I)
    return text


def audio_plan(lesson):
    """Each narration line: the clip file name, the caption text, and the text the voice reads."""
    scenes = lesson.get('scenes') if isinstance(lesson, dict) else None
    pron = lesson.get('pronounce') if isinstance(lesson, dict) else None
    return [{'clip': fnv1a(b['say']) + '.mp3', 'text': b['say'], 'read': speakable(b['say'], pron)}
            for s in (scenes if isinstance(scenes, list) else [])
            if isinstance(s, dict) for b in (s.get('beats') if isinstance(s.get('beats'), list) else [])
            if isinstance(b, dict) and isinstance(b.get('say'), str)]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('lesson')
    ap.add_argument('--sources', action='append', help="the source files as text, a file or a folder (repeatable)")
    ap.add_argument('--final', action='store_true', help='also require --sources and a recorded review')
    ap.add_argument('--build', metavar='OUT.html', help='sign the lesson and write the player with it inside, only if the check passes')
    ap.add_argument('--write', action='store_true', help='sign the lesson file in place (adds the "verification" block), only if the check passes')
    ap.add_argument('--audio-plan', action='store_true', help='print each narration line with its clip name, as JSON')
    ap.add_argument('--json', action='store_true', help='print the result as JSON')
    a = ap.parse_args(argv)
    lesson, note = read_lesson(a.lesson)
    sources = load_sources(a.sources) if a.sources else None
    if a.audio_plan:  # read-only: video_voice.py keys its clips to the lesson as it is on disk
        print(json.dumps(audio_plan(lesson), indent=1, ensure_ascii=False))
        return 0
    tidied = tidy(lesson, sources)
    if tidied:
        Path(a.lesson).write_text(dump_lesson(lesson))
        shown = '; '.join(tidied[:8]) + (f'; and {len(tidied) - 8} more' if len(tidied) > 8 else '')
        note = ((note + ' ') if note else '') + f'Fixed and saved {len(tidied)} slip(s) with one right answer: {shown}.'
    errors, warnings, summary = check(lesson, sources, a.final)
    if a.json:
        print(json.dumps({'errors': errors, 'warnings': warnings, 'summary': summary}, indent=1, ensure_ascii=False))
        return 1 if errors else 0
    if note:
        print('NOTE: ' + note)
    if errors:
        groups = {}
        for where, problem, fix in errors:  # the same problem in many places is printed once
            groups.setdefault((problem, fix), []).append(where)
        print(f'NOT READY: {len(errors)} problem(s). Fix them in this order, then run the check again.')
        for i, ((problem, fix), wheres) in enumerate(groups.items(), 1):
            if i > SHOW_MAX:
                print(f'... and {len(groups) - SHOW_MAX} more kinds of problem. Fix the {SHOW_MAX} above first, then run the check again to see the rest.')
                break
            places = '; '.join(wheres[:8]) + (f'; and {len(wheres) - 8} more' if len(wheres) > 8 else '')
            print(f'{i}. {places}{" (" + str(len(wheres)) + " places)" if len(wheres) > 1 else ""}: {problem}\n   Fix: {fix}')
    if warnings:
        print(f'WORTH FIXING ({len(warnings)}), not required:')
        for where, problem, fix in warnings:
            print(f'- {where} {problem} {fix}')
    m, s = divmod(summary.get('seconds', 0), 60)
    print(f'Video: {m}:{s:02d} of narration, {summary.get("scenes", 0)} chapters, {summary.get("pauses", 0)} pause questions, '
          f'{summary.get("claims", 0)} claims ({summary.get("claims_checked", 0)} quoted from files), {summary.get("calcs", 0)} calculations.')
    if errors:
        return 1
    v = summary['verification']
    print('Badge: ' + v['label'] + ''.join('; ' + x for x in v['lines']) + '.')
    signed = sign(lesson, v)
    if a.write:
        Path(a.lesson).write_text(json.dumps(signed, indent=1, ensure_ascii=False) + '\n')
        print(f'Signed {a.lesson}.')
    if a.build:
        Path(a.build).write_text(embed(signed))
        print(f'READY. Wrote {a.build}. Open it and watch the first minute before you share it.')
    elif not a.write:
        print('READY. Run with --build video.html to sign it and write the video.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
