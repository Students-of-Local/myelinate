#!/usr/bin/env python3
"""Find, read and section YouTube videos for a lesson, using an installed yt-dlp.

It never downloads video or audio and never installs anything. Captions are
fetched one exact track per yt-dlp run, because YouTube answers translated
tracks and quick second caption requests with HTTP 429, and yt-dlp stops the
whole run at the first subtitle error.

    python3 scripts/yt.py search "E2 elimination" --n 10
    python3 scripts/yt.py info VIDEO_ID
    python3 scripts/yt.py transcript VIDEO_ID [--lang en] [--plain]
    python3 scripts/yt.py find VIDEO_ID --terms "anti-periplanar,Zaitsev"
    python3 scripts/yt.py scan "E2 elimination" --terms "anti-periplanar,Zaitsev" --n 8
    python3 scripts/yt.py quote VIDEO_ID --at 7:55 "the hydrogen has to be trans to the leaving group"
    python3 scripts/yt.py course slides.txt "the beta H and the leaving group must be anti-periplanar"

Every command takes --json. Results are cached under $TMPDIR/myelinate-yt-<uid>/
by video id, so asking again makes no network request.

Exit codes: 0 ok, 1 video unavailable or no captions, 3 yt-dlp missing,
4 network failure, 5 rate limited (HTTP 429) or blocked by YouTube,
6 quote not confirmed (quote and course).
"""
import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qs, urlparse

MISSING = ("yt-dlp is not installed; use a host transcript tool, the browser's Show transcript panel, "
           "or ask the learner to paste the transcript.")
# One cache per user, private to them: on a shared machine another account could plant a transcript.
CACHE = Path(tempfile.gettempdir()) / ('myelinate-yt-%d' % os.getuid() if hasattr(os, 'getuid') else 'myelinate-yt')
INFO_FRESH = 5 * 3600  # caption URLs in an info JSON expire after some hours
TRACK_PAUSE = 2.0  # before the next caption track, after one failed
VIDEO_PAUSE = 1.5  # before any other request, after an earlier one
try:  # tests set MYELINATE_YT_PAUSE=0 to skip the waits; it scales them
    PAUSE_SCALE = max(0.0, float(os.environ.get('MYELINATE_YT_PAUSE', '1')))
except ValueError:
    PAUSE_SCALE = 1.0
ID_RE = re.compile(r'^[A-Za-z0-9_-]{11}$')
DASHES = '-\u2010\u2011\u2012\u2013\u2014\u2212/'
NET_CALLS = 0  # yt-dlp runs so far in this process


class YTError(Exception):
    """An expected failure. kind: unavailable, network, ratelimit, nocaptions, other."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


EXIT = {'unavailable': 1, 'nocaptions': 1, 'other': 1, 'network': 4, 'ratelimit': 5, 'unconfirmed': 6}


# ---------- running yt-dlp ----------

def classify(stderr):
    """Turn yt-dlp's stderr into (kind, one line)."""
    text = stderr or ''
    errs = [ln.strip() for ln in text.splitlines() if ln.strip().startswith('ERROR')]
    last = errs[-1] if errs else (text.strip().splitlines() or ['yt-dlp failed'])[-1]
    last = re.sub(r'^ERROR:\s*', '', last)[:240]
    low = text.lower()
    if 'http error 429' in low or 'too many requests' in low:
        return 'ratelimit', 'YouTube rate limited the request (HTTP 429); wait a minute and ask for less.'
    if "confirm you're not a bot" in low or 'confirm you are not a bot' in low:
        return 'ratelimit', 'YouTube asked for a bot check; wait and try later, or use the browser transcript panel.'
    for pat, why in (('private video', 'private'), ('age', 'age-restricted'), ('members-only', 'members only'),
                     ('video unavailable', 'unavailable'), ('not available', 'unavailable'),
                     ('has been removed', 'removed'), ('copyright', 'blocked for copyright'),
                     ('incomplete youtube id', 'not a valid video id'), ('is not a valid url', 'not a valid video id')):
        if pat in low and (pat != 'age' or 'sign in to confirm your age' in low or 'age-restricted' in low or 'age restricted' in low):
            return 'unavailable', f'video {why}: {last}'
    if any(p in low for p in ('getaddrinfo', 'name resolution', 'timed out', 'connection', 'network is unreachable',
                              'unable to download webpage', 'urlopen error', 'ssl')):
        return 'network', f'network failure: {last}'
    return 'other', last


def run(args, timeout=120, gap=VIDEO_PAUSE):
    """One yt-dlp run. After an earlier run in this process, wait gap seconds first."""
    global NET_CALLS
    if NET_CALLS and gap:
        time.sleep(gap * PAUSE_SCALE)
    NET_CALLS += 1
    try:
        p = subprocess.run(['yt-dlp', '--ignore-config'] + args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise YTError('network', f'network failure: yt-dlp took over {timeout}s')
    except OSError as exc:
        raise YTError('other', f'could not run yt-dlp: {exc}')
    if p.returncode != 0:
        kind, msg = classify(p.stderr)
        raise YTError(kind, msg)
    return p.stdout


# ---------- ids, cache, small helpers ----------

def video_id(ref):
    ref = ref.strip()
    if ID_RE.match(ref):
        return ref
    u = urlparse(ref if '://' in ref else 'https://' + ref)
    host = (u.hostname or '').lower()
    if host.endswith('youtu.be'):
        cand = u.path.strip('/').split('/')[0]
    elif 'youtube' in host:
        cand = (parse_qs(u.query).get('v') or [''])[0]
        if not cand:
            parts = [p for p in u.path.split('/') if p]
            if len(parts) >= 2 and parts[0] in ('shorts', 'embed', 'live', 'v', 'e'):
                cand = parts[1]
    else:
        cand = ''
    if not ID_RE.match(cand or ''):
        raise YTError('unavailable', f'not a YouTube video URL or id: {ref}')
    return cand


def watch_url(vid):
    return f'https://www.youtube.com/watch?v={vid}'


def clock(s):
    s = int(s or 0)
    h, m, r = s // 3600, s % 3600 // 60, s % 60
    return f'{h}:{m:02d}:{r:02d}' if h else f'{m}:{r:02d}'


def vdir(vid):
    CACHE.mkdir(mode=0o700, parents=True, exist_ok=True)
    if hasattr(os, 'getuid') and CACHE.stat().st_uid != os.getuid():
        raise YTError('other', f'{CACHE} belongs to another user; not reading a cache someone else can write')
    d = CACHE / vid
    d.mkdir(exist_ok=True)
    return d


def get_info(vid, fresh=False):
    """Info JSON from cache, or one yt-dlp call. fresh=True refetches if old (caption URLs expire)."""
    path = vdir(vid) / 'info.json'
    if path.is_file() and not (fresh and time.time() - path.stat().st_mtime > INFO_FRESH):
        try:
            return json.loads(path.read_text()), path
        except ValueError:
            pass
    out = run(['-J', '--skip-download', '--no-warnings', watch_url(vid)])
    try:
        info = json.loads(out)
    except ValueError:
        raise YTError('other', 'yt-dlp returned no readable video info')
    path.write_text(json.dumps(info))
    return info, path


def date(d):
    return f'{d[:4]}-{d[4:6]}-{d[6:8]}' if d and len(d) == 8 else (d or '')


def chapters_of(info):
    return [{'start': float(c.get('start_time') or 0), 'end': float(c.get('end_time') or 0), 'title': c.get('title') or ''}
            for c in (info.get('chapters') or [])]


# ---------- caption tracks ----------

def translated(tracks):
    return any('tlang=' in (t.get('url') or '') for t in tracks or [])


def manual_tracks(info):
    return {k: v for k, v in (info.get('subtitles') or {}).items() if k != 'live_chat'}


def candidates(info, lang='en'):
    """Ordered (source, track, kind) choices. source is 'manual' or 'auto'; kind is manual, auto or translated."""
    manual = manual_tracks(info)
    auto = info.get('automatic_captions') or {}
    out = []

    def add(src, key, kind):
        if (src, key) not in [(s, k) for s, k, _ in out]:
            out.append((src, key, kind))

    def native(code):
        if code in manual:
            add('manual', code, 'manual')
        for k in sorted(manual):
            if k.startswith(code + '-'):
                add('manual', k, 'manual')
        if code + '-orig' in auto:
            add('auto', code + '-orig', 'auto')
        if code in auto and not translated(auto[code]):
            add('auto', code, 'auto')

    native(lang)
    own = source_language(info)  # the video's own language, from its info or its -orig track
    if own != '?' and own.split('-')[0] != lang.split('-')[0]:
        native(own)
    if lang in auto and translated(auto[lang]):
        add('auto', lang, 'translated')
    return out


def source_language(info):
    if info.get('language'):
        return info['language']
    for k in (info.get('automatic_captions') or {}):
        if k.endswith('-orig'):
            return k[:-5]
    return '?'


def track_label(kind, track, info):
    if kind == 'manual':
        return f'manual {track}'
    if kind == 'auto':
        return f'auto {track} (machine captions: check technical words)'
    return f'translated from {source_language(info)} (machine translation)'


def caption_summary(info, lang):
    manual = sorted(manual_tracks(info))
    auto = info.get('automatic_captions') or {}
    rel = sorted(k for k in auto if k == lang or k.startswith(lang + '-') or k == f'{info.get("language")}-orig')
    return {'manual': manual,
            'auto': [{'lang': k, 'translated': translated(auto[k])} for k in rel],
            'orig': f'{lang}-orig' in auto,
            'best': (lambda c: track_label(c[0][2], c[0][1], info) if c else None)(candidates(info, lang))}


# ---------- WebVTT ----------

TIME_RE = re.compile(r'^\s*((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})')


def secs(t):
    parts = t.replace(',', '.').split(':')
    total = 0.0
    for p in parts:
        total = total * 60 + float(p)
    return total


def clean(line):
    line = re.sub(r'<[^>]*>', '', line)
    line = html.unescape(line).replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', line).strip()


def vtt_blocks(text):
    """(start, end, lines) per cue. Lines are read by timing line, not split on blank lines, because
    YouTube's rolling cues open with a line holding a single space. A blank line after text ends a cue,
    so cue ids and NOTE blocks are skipped."""
    blocks, reading = [], False
    for raw in text.replace('\ufeff', '').splitlines():
        m = TIME_RE.match(raw)
        if m:
            blocks.append((secs(m.group(1)), secs(m.group(2)), []))
            reading = True
        elif reading and raw.strip():
            blocks[-1][2].append(raw)
        elif reading and blocks[-1][2]:
            reading = False
    return blocks


def parse_vtt(text):
    """Cues as [{start, end, text}], each spoken phrase once (YouTube rolling captions repeat the previous line)."""
    cues = []
    recent = []  # [(line, cue index)] for the last lines emitted
    for start, end, lines in vtt_blocks(text):
        new = []
        shown = [ln for ln in (clean(r) for r in lines) if ln]
        for k, line in enumerate(shown):
            hit = next(((ln, ci) for ln, ci in recent[-2:] if ln == line), None)
            # A line shown again is the same words when the cues touch, or when it is the top line a rolling
            # caption carries over (even after a pause). A single line said again later is new speech.
            touches = hit and start <= cues[hit[1]]['end'] + 1
            if touches:
                cues[hit[1]]['end'] = max(cues[hit[1]]['end'], end)
            if touches or (hit and k == 0 and len(shown) > 1):
                continue
            if recent and line.startswith(recent[-1][0] + ' ') and start <= cues[recent[-1][1]]['end'] + 1:
                ci = recent[-1][1]  # one line growing word by word
                cues[ci]['text'] = cues[ci]['text'][:len(cues[ci]['text']) - len(recent[-1][0])] + line
                cues[ci]['end'] = max(cues[ci]['end'], end)
                recent[-1] = (line, ci)
                continue
            new.append(line)
        if new:
            cues.append({'start': round(start, 3), 'end': round(end, 3), 'text': ' '.join(new)})
            for ln in new:
                recent.append((ln, len(cues) - 1))
            recent = recent[-2:]
    return cues


def paragraphs(cues, chapters):
    """Groups of roughly 20 to 40 seconds, never crossing a chapter boundary."""
    bounds = sorted(c['start'] for c in chapters if c['start'] > 0)

    def chapter_at(t):
        title = None
        for c in chapters:
            if c['start'] <= t + 0.5:
                title = c['title']
        return title

    out, cur = [], None
    for cue in cues:
        ch = chapter_at(cue['start'])
        if cur:
            dur = cue['start'] - cur['start']
            crosses = any(cur['start'] < b <= cue['start'] + 0.5 for b in bounds)
            sentence = re.search(r'[.?!]["\')\]]?$', cur['text'])
            if crosses or dur >= 40 or (dur >= 20 and sentence) or (dur >= 30 and not sentence):
                out.append(cur)
                cur = None
        if cur is None:
            cur = {'start': cue['start'], 'end': cue['end'], 'text': cue['text'], 'chapter': ch}
        else:
            cur['text'] += ' ' + cue['text']
            cur['end'] = max(cur['end'], cue['end'])
    if cur:
        out.append(cur)
    return out


# ---------- transcripts ----------

def download_track(info_path, vid, src, track, gap):
    """One exact track. --sub-langs items are regexes matched to the whole key, so escape it."""
    with tempfile.TemporaryDirectory(dir=vdir(vid)) as tmp:
        run(['--load-info-json', str(info_path), '--skip-download', '--no-warnings',
             '--write-subs' if src == 'manual' else '--write-auto-subs',
             '--sub-langs', re.escape(track), '--sub-format', 'vtt', '-o', os.path.join(tmp, 'sub')],
            timeout=90, gap=gap)
        files = sorted(Path(tmp).glob('*.vtt'))
        if not files:
            raise YTError('other', f'yt-dlp wrote no {track} caption file')
        return files[0].read_text(encoding='utf-8', errors='replace')


def get_transcript(ref, lang='en', log=None):
    vid = video_id(ref)
    cache = vdir(vid) / f'transcript-{lang}.json'
    if cache.is_file():
        try:
            return json.loads(cache.read_text())
        except ValueError:
            pass
    info, info_path = get_info(vid, fresh=True)
    choices = candidates(info, lang)
    if not choices:
        raise YTError('nocaptions', 'no captions: cannot vet (this video has no caption track)')
    failures = []
    for n, (src, track, kind) in enumerate(choices):
        try:  # each track once, best first; a failure moves on after TRACK_PAUSE, never retries
            vtt = download_track(info_path, vid, src, track, TRACK_PAUSE if n else VIDEO_PAUSE)
        except YTError as exc:
            failures.append((track, exc))
            if log:
                log(f'{src} {track}: {exc}; trying the next track')
            continue
        cues = parse_vtt(vtt)
        if not cues:
            failures.append((track, YTError('other', 'empty caption file')))
            if log:
                log(f'{src} {track}: empty caption file; trying the next track')
            continue
        chapters = chapters_of(info)
        result = {'id': vid, 'title': info.get('title'), 'track': track, 'source': src, 'kind': kind,
                  'label': track_label(kind, track, info), 'cues': cues,
                  'paragraphs': paragraphs(cues, chapters), 'chapters': chapters}
        cache.write_text(json.dumps(result))
        return result
    if failures and all(e.kind == 'ratelimit' for _, e in failures):
        raise YTError('ratelimit', 'every caption track got HTTP 429 from YouTube; wait a minute, then fetch one video')
    detail = '; '.join(f'{t}: {e}' for t, e in failures)
    raise YTError('other', f'no caption track could be read ({detail})')


# ---------- finding segments ----------

def norm_words(text):
    text = text.lower()
    for d in DASHES:
        text = text.replace(d, ' ')
    text = re.sub(r"[^\w' ]+", ' ', text)
    return [w.strip("'") for w in text.split() if w.strip("'")]


def term_matcher(term):
    """Match a term at word i of a word list. Each term word matches a word that starts with it
    ("eliminat" and "elimination" match "eliminations"), and hyphen, space or no space are the same
    ("anti-periplanar" matches "anti periplanar" and "antiperiplanar")."""
    toks = norm_words(term)
    joined = ''.join(toks)

    def at(words, i):
        """End index (exclusive) of a match starting at word i, or 0."""
        n = len(toks)
        if not n:
            return 0
        if i + n <= len(words) and all(words[i + j].startswith(t) for j, t in enumerate(toks)):
            return i + n
        w, j = '', i
        while j < len(words) and len(w) < len(joined):
            w += words[j]
            j += 1
            if not (joined.startswith(w) or w.startswith(joined)):
                return 0
        return j if w.startswith(joined) else 0
    return at


def find_hits(cues, terms):
    words, owner = [], []
    for ci, c in enumerate(cues):
        for w in norm_words(c['text']):
            words.append(w)
            owner.append(ci)
    hits = []
    for term in terms:
        at = term_matcher(term)
        i = 0
        while i < len(words):
            j = at(words, i)
            if j:
                hits.append({'term': term, 'time': cues[owner[i]]['start'], 'end': cues[owner[j - 1]]['end'],
                             'cue': owner[i], 'last_cue': owner[j - 1]})
                i = j
            else:
                i += 1
    return sorted(hits, key=lambda h: h['time'])


def windows(hits, window):
    """One window per hit: the hits from it to window seconds later, scored by distinct terms, then hits."""
    out = []
    for h in hits:
        inside = [x for x in hits if h['time'] <= x['time'] <= h['time'] + window]
        out.append({'start': h['time'], 'end': max(x['end'] for x in inside),
                    'distinct': len({x['term'] for x in inside}), 'total': len(inside)})
    return out


def best_spans(hits, window, top, max_len):
    """Take the best windows greedily. A window that overlaps a chosen span joins it (up to max_len
    seconds); one that overlaps nothing starts a new span while fewer than top are chosen."""
    chosen = []
    for w in sorted(windows(hits, window), key=lambda w: (-w['distinct'], -w['total'], w['start'])):
        over = [c for c in chosen if w['start'] <= c['end'] and w['end'] >= c['start']]
        if over:
            c = over[0]
            s, e = min(c['start'], w['start']), max(c['end'], w['end'])
            if e - s <= max_len:
                c['start'], c['end'] = s, e
        elif len(chosen) < top:
            chosen.append({'start': w['start'], 'end': w['end']})
    return chosen


def snap_start(cues, t):
    best = 0.0
    for c in cues:
        if c['start'] <= t:
            best = c['start']
        else:
            break
    return best


def snap_end(cues, t):
    for c in cues:
        if c['end'] >= t:
            return c['end']
    return cues[-1]['end'] if cues else t


def segment(vid, cues, terms, start, end, hits, from_chapter=False, title=None):
    inside = [h for h in hits if start <= h['time'] <= end]
    counts = {t: sum(1 for h in inside if h['term'] == t) for t in terms}
    first = min((h['time'] for h in inside), default=start)  # preview from the first hit, not the padding
    text = ' '.join(c['text'] for c in cues if c['start'] >= first and c['start'] < end)
    s, e = int(start), int(end + 0.999)
    seg = {'start': round(start, 2), 'end': round(end, 2), 'length': round(end - start, 1),
           'clock': f'{clock(s)} to {clock(e)}', 'from_chapter': from_chapter,
           'hits': {t: n for t, n in counts.items() if n}, 'missing': [t for t, n in counts.items() if not n],
           'distinct': sum(1 for n in counts.values() if n), 'total': len(inside),
           'preview': text[:300] + ('...' if len(text) > 300 else ''),
           'watch': f'https://www.youtube.com/watch?v={vid}&t={s}s',
           'embed': f'https://www.youtube-nocookie.com/embed/{vid}?start={s}&end={e}'}
    if title:
        seg['chapter'] = title
    return seg


def find_segments(tr, terms, window=60, top=3, pad=20):
    cues, vid = tr['cues'], tr['id']
    hits = find_hits(cues, terms)
    heard = {h['term'] for h in hits}
    spans, max_len = [], max(5 * window, 300)
    for sp in sorted(best_spans(hits, window, top, max_len), key=lambda sp: sp['start']):
        start = snap_start(cues, max(0.0, sp['start'] - pad))
        end = snap_end(cues, sp['end'] + pad)
        if spans and start <= spans[-1][1] and end - spans[-1][0] <= max_len + 2 * pad:  # padding joined two short spans
            spans[-1] = (spans[-1][0], max(spans[-1][1], end))
        else:
            spans.append((start, end))
    segs = [segment(vid, cues, terms, s, e, hits) for s, e in spans]
    for ch in tr.get('chapters') or []:
        title_words = norm_words(ch['title'])
        if any(term_matcher(t)(title_words, i) for t in terms for i in range(len(title_words))):
            end = ch['end'] or (cues[-1]['end'] if cues else ch['start'])
            segs.append(segment(vid, cues, terms, ch['start'], end, hits, True, ch['title']))
    segs.sort(key=lambda s: (-s['distinct'], not s['from_chapter'], -s['total'], s['length']))
    return {'id': vid, 'terms': terms, 'coverage': round(len(heard) / len(terms), 3) if terms else 0.0,
            'heard': [t for t in terms if t in heard], 'not_heard': [t for t in terms if t not in heard],
            'track': tr.get('label'), 'kind': tr.get('kind'), 'segments': segs}


def parse_terms(s):
    terms = [t.strip() for t in s.split(',') if t.strip()]
    if not terms:
        raise YTError('other', 'give at least one term: --terms "a,b,c"')
    return terms


# ---------- checking quotes ----------
# A quote is shown to a learner only after these checks pass, and what they see is the source's own words.
# The thresholds are deliberately high: a caption slip ("leading group" for "leaving group") passes, while a
# changed meaning ("cis" for "trans", "E1" for "E2", a dropped "not") fails.
QUOTE_THRESHOLD = 0.90  # character similarity of the whole quote to the words found
WORD_THRESHOLD = 0.75   # each run of words that differs must be at least this similar, and a slip (see slip)
QUOTE_WINDOW = 20       # seconds either side of --at
FILLER = {'uh', 'um', 'uhm', 'er', 'ah', 'so', 'okay', 'ok', 'well', 'like', 'just', 'now', 'and',
          'a', 'an', 'the', 'oh', 'yeah', 'right', 'basically', 'actually'}
NEGATION = {'not', 'no', 'never', 'cannot', 'cant', 'dont', 'doesnt', 'isnt', 'arent', 'wont', 'wasnt',
            'werent', 'shouldnt', 'couldnt', 'wouldnt', 'nor', 'without', 'neither', 'none'}
QUOTE_MARKS = {'‘': "'", '’': "'", '‚': "'", '′': "'", '“': '"', '”': '"',
               '„': '"', '″': '"', '«': '"', '»': '"'}
ELLIPSIS = re.compile(r'\.{3,}|…|\[\s*\.\.\.\s*\]')


STAMP = re.compile(r'\[\d{1,2}:\d\d(?::\d\d)?\]')


def quote_tokens(text):
    """Words compared by the quote checks: case, accents-as-composed, ligatures, curly quotes, dashes,
    soft hyphens and words hyphenated across a line break (PDF text) all stop mattering."""
    text = unicodedata.normalize('NFKC', text).replace('­', '')
    text = re.sub(r'(\w)-[ \t]*\r?\n[ \t]*(\w)', r'\1\2', text)
    for k, v in QUOTE_MARKS.items():
        text = text.replace(k, v)
    return [w.replace("'", '') for w in norm_words(text) if w.replace("'", '')]


def raw_words(text):
    """[(raw word, [tokens])] so a match can be shown in the source's own spelling."""
    return [(w, quote_tokens(w)) for w in text.split()]


class Source:
    """Token stream of a transcript or file, each token with a time (seconds) or line number and its raw word."""

    def __init__(self):
        self.tokens, self.where, self.raw_index, self.raw = [], [], [], []

    def add(self, text, where_for):
        words = raw_words(text)
        for k, (w, toks) in enumerate(words):
            self.raw.append(w)
            for tok in toks:
                self.tokens.append(tok)
                self.where.append(where_for(k, len(words)))
                self.raw_index.append(len(self.raw) - 1)

    def text(self, i, j):
        return ' '.join(self.raw[self.raw_index[i]:self.raw_index[j - 1] + 1])


def transcript_source(tr):
    src = Source()
    for c in tr['cues']:
        span = max(0.0, c['end'] - c['start'])
        src.add(c['text'], lambda k, n, c=c, span=span: c['start'] + span * k / max(n, 1))
    return src


def file_source(path):
    path = Path(path)
    if not path.is_file():
        raise YTError('other', f'no such file: {path}')
    head = path.read_bytes()[:4096]
    if head.startswith(b'%PDF'):
        raise YTError('other', f'{path} is a PDF; give its text (pdftotext "{path}" out.txt) or paste the passage into a .txt file')
    if b'\x00' in head:
        raise YTError('other', f'{path} is not a text file; save the course text as .txt or .md first')
    text = path.read_text(encoding='utf-8', errors='replace')
    # Rejoin a word split across lines ("anti-" / "periplanar") and keep the line count.
    text = re.sub(r'(\w)-[ \t]*\r?\n[ \t]*(\w+)', r'\1\2\n', text)
    src = Source()
    for n, line in enumerate(text.splitlines(), 1):
        src.add(line, lambda k, total, n=n: n)
    return src


def ratio(a, b):
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


# Same start, different meaning: these prefixes are one or two letters apart.
OPPOSITE_PREFIXES = [('hyper', 'hypo'), ('inter', 'intra'), ('hetero', 'homo'), ('supra', 'sub')]


def edits(a, b):
    """Levenshtein distance between two short strings."""
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def slip(qa, ca):
    """True when words that differ read as a caption or spelling slip ("leading" for "leaving",
    "Zaitzev" for "Zaitsev", "anti periplanar" for "antiperiplanar"), not a different word.
    A changed start ("syn"/"anti", "un"/"", "de"/"") or more than one letter off (two in long
    words) is a different word, however similar the rest is."""
    x, y = ''.join(qa), ''.join(ca)
    if x == y:
        return True
    if ratio(x, y) < WORD_THRESHOLD or x[:2] != y[:2]:
        return False
    if edits(x, y) > (1 if min(len(x), len(y)) < 7 else 2):
        return False
    return not any(x.startswith(a) and y.startswith(b) or x.startswith(b) and y.startswith(a)
                   for a, b in OPPOSITE_PREFIXES)


def judge(q, cand):
    """Problems that make cand not what q says, word by word. Empty means the words match."""
    problems = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, q, cand, autojunk=False).get_opcodes():
        qa, ca = q[i1:i2], cand[j1:j2]
        if tag == 'equal':
            continue
        neg = {w for w in qa + ca if w in NEGATION}
        if neg and set(w for w in qa if w in NEGATION) != set(w for w in ca if w in NEGATION):
            problems.append(f'negation differs: quote "{" ".join(qa) or "(nothing)"}", source "{" ".join(ca) or "(nothing)"}"')
            continue
        nums_q = [w for w in qa if any(ch.isdigit() for ch in w)]
        nums_c = [w for w in ca if any(ch.isdigit() for ch in w)]
        if nums_q != nums_c:
            problems.append(f'number differs: quote "{" ".join(qa)}", source "{" ".join(ca)}"')
            continue
        if tag == 'replace':
            if not slip(qa, ca):
                problems.append(f'quote says "{" ".join(qa)}" where the source says "{" ".join(ca)}"')
        elif tag == 'delete':
            extra = [w for w in qa if w not in FILLER]
            if extra:
                problems.append(f'not in the source: "{" ".join(qa)}"')
        elif tag == 'insert':
            dropped = [w for w in ca if w not in FILLER]
            if dropped:
                problems.append(f'quote leaves out "{" ".join(ca)}" (mark a cut with ... instead)')
    return problems


def spans_at(q, src, starts, slack=4, keep=8):
    """Best-scoring (score, i, j) source spans, one per start, near the quote's length, best first."""
    qs, n = ' '.join(q), len(q)
    heads = set(q[:3])
    found = []
    for i in starts:
        if src.tokens[i] not in heads and not any(ratio(src.tokens[i], h) >= WORD_THRESHOLD for h in heads):
            continue
        best = (0.0, i, i)
        for m in range(max(1, n - slack), n + slack + 1):
            j = min(len(src.tokens), i + m)
            s = ratio(qs, ' '.join(src.tokens[i:j]))
            if s > best[0]:
                best = (s, i, j)
        found.append(best)
    return sorted(found, reverse=True)[:keep]


def match_quote(text, src, starts):
    """Match each part of a quote ("a ... b" is two parts, in order) against src. starts limits where the
    first part may begin; each later part follows within about 60 words. Returns ok, score, start, end and
    problems for the best chain: one where every part passes, if there is one."""
    text = STAMP.sub(' ', text)  # a [8:01] copied from the transcript view is not a spoken word
    parts = [quote_tokens(x) for x in ELLIPSIS.split(text)]
    parts = [x for x in parts if x]
    if not parts:
        return {'ok': False, 'score': 0.0, 'problems': ['the quote has no words']}
    if sum(len(x) for x in parts) < 4:
        return {'ok': False, 'score': 0.0, 'problems': ['quote at least four words, so it can be told apart from a coincidence']}

    def chain(k, idx):
        """Best result for parts[k:], with parts[k] starting at one of idx."""
        best = None
        for s, i, j in spans_at(parts[k], src, idx):
            problems = ([] if s >= QUOTE_THRESHOLD else
                        [f'closest source words "{src.text(i, j)}" match only {s:.2f} (need {QUOTE_THRESHOLD})'])
            problems += judge(parts[k], src.tokens[i:j])
            res = {'score': s, 'start': i, 'end': j, 'problems': problems}
            if k + 1 < len(parts):
                rest = chain(k + 1, range(j, min(len(src.tokens), j + 60)))
                if rest is None:
                    res['problems'] = problems + [f'not found after it: "{" ".join(parts[k + 1])}"']
                else:
                    res = {'score': min(s, rest['score']), 'start': i, 'end': rest['end'],
                           'problems': problems + rest['problems']}
            if best is None or (not res['problems'], res['score']) > (not best['problems'], best['score']):
                best = res
        return best

    res = chain(0, list(starts))
    if res is None:
        return {'ok': False, 'score': 0.0, 'problems': [f'not found: "{" ".join(parts[0])}"']}
    return {'ok': not res['problems'], 'score': round(res['score'], 3), 'start': res['start'], 'end': res['end'],
            'problems': res['problems']}


def parse_at(s):
    s = s.strip()
    try:
        return float(s) if ':' not in s else secs(s + ('.0' if '.' not in s else ''))
    except ValueError:
        raise YTError('other', f'--at takes m:ss, h:mm:ss or seconds, not "{s}"')


def check_video_quote(ref, at, text, lang='en', window=QUOTE_WINDOW):
    tr = get_transcript(ref, lang)
    src = transcript_source(tr)
    near = [i for i, t in enumerate(src.where) if at - window <= t <= at + window]
    res = match_quote(text, src, near)
    out = {'kind': 'video', 'id': tr['id'], 'at': at, 'window': window, 'track': tr['label'],
           'threshold': QUOTE_THRESHOLD, 'word_threshold': WORD_THRESHOLD, 'quote': text,
           'ok': res['ok'], 'score': res['score'], 'problems': res['problems']}
    if res.get('end') is not None and res['score'] > 0:
        t0 = src.where[res['start']]
        out.update({'found_at': round(t0, 1), 'source_words': src.text(res['start'], res['end']),
                    'link': f'https://www.youtube.com/watch?v={tr["id"]}&t={int(t0)}s'})
    if not res['ok']:
        anywhere = match_quote(text, src, range(len(src.tokens)))
        if anywhere['ok']:
            t0 = src.where[anywhere['start']]
            out['problems'] = [f'said at {clock(t0)}, not within {window}s of {clock(at)}: re-check the timestamp, then quote it at {clock(t0)}']
            out['elsewhere'] = round(t0, 1)
    return out


def check_course_quote(path, text):
    src = file_source(path)
    res = match_quote(text, src, range(len(src.tokens)))
    out = {'kind': 'course', 'file': str(path), 'threshold': QUOTE_THRESHOLD, 'word_threshold': WORD_THRESHOLD,
           'quote': text, 'ok': res['ok'], 'score': res['score'], 'problems': res['problems']}
    if res.get('end') is not None and res['score'] > 0:
        out.update({'line': src.where[res['start']], 'source_words': src.text(res['start'], res['end'])})
    return out


def print_check(r, where):
    if r['ok']:
        # The line to show the learner: the source's own words, never the quote as the model typed it.
        print(f'CONFIRMED (similarity {r["score"]:.2f}, threshold {r["threshold"]})')
        print(f'show: "{r["source_words"]}" ({where})')
        return 0
    print(f'NOT CONFIRMED (threshold {r["threshold"]}; a differing word must be a slip: {r["word_threshold"]} similar, '
          'same first two letters, at most one letter off, two in long words): do not show this quote.')
    for pr in r['problems']:
        print('  ' + pr)
    if r.get('source_words') and not r.get('elsewhere'):
        print(f'  closest source words: "{r["source_words"]}"')
    return 6


def cmd_quote(a):
    r = check_video_quote(a.video, parse_at(a.at), a.text, a.lang, a.window)
    if a.json:
        print(json.dumps(r, indent=1))
        return 0 if r['ok'] else 6
    print(f'track: {r["track"]}')
    return print_check(r, f'{clock(r.get("found_at", 0))}, {r.get("link", "")}')


def cmd_course(a):
    r = check_course_quote(a.file, a.text)
    if a.json:
        print(json.dumps(r, indent=1))
        return 0 if r['ok'] else 6
    return print_check(r, f'{Path(a.file).name}, line {r.get("line")}')


# ---------- search ----------

def search(query, n):
    out = run(['--flat-playlist', '-J', '--no-warnings', f'ytsearch{n}:{query}'])
    try:
        data = json.loads(out)
    except ValueError:
        raise YTError('other', 'yt-dlp returned no readable search results')
    results = []
    for e in data.get('entries') or []:
        vid = e.get('id')
        if not vid:
            continue
        url = e.get('url') or e.get('webpage_url') or ''
        dur = e.get('duration')
        results.append({'id': vid, 'title': e.get('title') or '', 'channel': e.get('channel') or e.get('uploader') or '',
                        'duration': int(dur) if dur else None, 'duration_clock': clock(dur) if dur else '?',
                        'view_count': e.get('view_count'), 'live_status': e.get('live_status'),
                        'short': '/shorts/' in url or (dur is not None and dur < 60),
                        'url': watch_url(vid)})
    return results


# ---------- commands ----------

def views(n):
    return f'{n:,} views' if isinstance(n, int) else 'views ?'


def cmd_search(a):
    res = search(a.query, a.n)
    if a.json:
        return print(json.dumps(res, indent=1))
    if not res:
        print('no results')
    for k, r in enumerate(res, 1):
        flag = '  [short]' if r['short'] else ''
        print(f"{k}. {r['title']} | {r['channel']} | {r['duration_clock']} | {views(r['view_count'])} | {r['url']}{flag}")


def info_summary(info, lang):
    return {'id': info.get('id'), 'title': info.get('title'), 'channel': info.get('channel') or info.get('uploader'),
            'channel_follower_count': info.get('channel_follower_count'), 'upload_date': date(info.get('upload_date')),
            'duration': info.get('duration'), 'duration_clock': clock(info.get('duration')),
            'view_count': info.get('view_count'), 'playable_in_embed': info.get('playable_in_embed'),
            'availability': info.get('availability'), 'live_status': info.get('live_status'),
            'language': info.get('language'), 'chapters': chapters_of(info),
            'description': (info.get('description') or '')[:500], 'captions': caption_summary(info, lang),
            'url': watch_url(info.get('id'))}


def cmd_info(a):
    info, _ = get_info(video_id(a.video))
    s = info_summary(info, a.lang)
    if a.json:
        return print(json.dumps(s, indent=1))
    print(f"{s['title']}\n{s['url']}")
    print(f"channel: {s['channel']} ({s['channel_follower_count'] or '?'} followers) | uploaded {s['upload_date']} | "
          f"{s['duration_clock']} | {views(s['view_count'])}")
    print(f"embeddable: {s['playable_in_embed']} | availability: {s['availability']} | live: {s['live_status']} | language: {s['language']}")
    c = s['captions']
    auto = ', '.join(x['lang'] + (' (translated)' if x['translated'] else '') for x in c['auto']) or 'none'
    print(f"captions: manual {', '.join(c['manual']) or 'none'} | auto {auto} | {a.lang}-orig {'yes' if c['orig'] else 'no'}")
    print(f"best track for {a.lang}: {c['best'] or 'none (cannot vet)'}")
    if s['chapters']:
        print('chapters:')
        for ch in s['chapters']:
            print(f"  {clock(ch['start'])} to {clock(ch['end'])}  {ch['title']}")
    else:
        print('chapters: none')
    if s['description']:
        print('description: ' + s['description'].replace('\n', ' '))


def cmd_transcript(a):
    tr = get_transcript(a.video, a.lang, log=lambda m: print(m, file=sys.stderr))
    if a.json:
        return print(json.dumps({k: tr[k] for k in ('id', 'track', 'kind', 'label', 'cues', 'paragraphs', 'chapters')}, indent=1))
    print('track: ' + tr['label'])
    chapter = None
    for p in tr['paragraphs']:
        if p.get('chapter') and p['chapter'] != chapter:
            chapter = p['chapter']
            print(f'\n## {chapter}')
        print(p['text'] if a.plain else f"[{clock(p['start'])}] {p['text']}")


def print_segment(s, indent='  '):
    hits = ', '.join(f'{t} x{n}' for t, n in s['hits'].items()) or 'none'
    tag = f" (chapter: {s['chapter']})" if s.get('from_chapter') else ''
    print(f"{indent}{s['clock']} ({round(s['length'] / 60, 1)} min){tag}")
    print(f"{indent}  hits: {hits}" + (f" | missing: {', '.join(s['missing'])}" if s['missing'] else ''))
    print(f"{indent}  watch: {s['watch']}\n{indent}  embed: {s['embed']}")
    print(f"{indent}  \"{s['preview']}\"")


def cmd_find(a):
    tr = get_transcript(a.video, a.lang, log=lambda m: print(m, file=sys.stderr))
    res = find_segments(tr, parse_terms(a.terms), a.window, a.top, a.pad)
    if a.json:
        return print(json.dumps(res, indent=1))
    print(f"track: {res['track']}")
    print(f"coverage: {res['coverage']:.0%} (heard: {', '.join(res['heard']) or 'none'}"
          + (f"; not heard: {', '.join(res['not_heard'])}" if res['not_heard'] else '') + ')')
    if not res['segments']:
        print('no segment says any of the terms')
    for k, s in enumerate(res['segments'], 1):
        print(f'{k}.', end='')
        print_segment(s, ' ')


KIND_RANK = {'manual': 0, 'auto': 1, 'translated': 2}


def scan_rank(row):
    """Coverage, then the best segment's distinct terms, caption kind, embeddable, shorter segment.
    Videos that failed come after, and videos with no captions (cannot vet) come last."""
    if row['status'] != 'ok':
        return (2 if row.get('error_kind') == 'nocaptions' else 1, 0, 0, 0, 0, 0)
    best = row['segments'][0] if row['segments'] else {'distinct': 0, 'length': 1e9}
    return (0, -row['coverage'], -best['distinct'], KIND_RANK.get(row['kind'], 3),
            0 if row.get('embeddable') else 1, best['length'])


def cmd_scan(a):
    terms = parse_terms(a.terms)
    found = search(a.query, a.n)
    dropped, keep = [], []
    for r in found:
        why = ('short' if r['short'] else 'live' if r['live_status'] in ('is_live', 'is_upcoming')
               else f'over {a.max_minutes} min' if r['duration'] and r['duration'] > a.max_minutes * 60 else None)
        (dropped if why else keep).append((r, why))
    rows, streak, stopped = [], 0, None
    for r, _ in keep:  # one video at a time; run() waits VIDEO_PAUSE before each request
        row = {'id': r['id'], 'title': r['title'], 'channel': r['channel'], 'url': r['url'],
               'duration': r['duration'], 'status': 'ok'}
        try:
            info, _ = get_info(r['id'])
            row.update({'title': info.get('title') or r['title'], 'channel': info.get('channel') or r['channel'],
                        'upload_date': date(info.get('upload_date')), 'duration': info.get('duration') or r['duration'],
                        'embeddable': info.get('playable_in_embed'), 'live_status': info.get('live_status')})
            if info.get('live_status') in ('is_live', 'is_upcoming'):
                dropped.append((r, 'live'))
                continue
            tr = get_transcript(r['id'], a.lang)
            res = find_segments(tr, terms)
            row.update({'kind': tr['kind'], 'track': tr['label'], 'coverage': res['coverage'],
                        'not_heard': res['not_heard'], 'segments': res['segments'][:2]})
            streak = 0
        except YTError as exc:
            row['status'] = 'no captions: cannot vet' if exc.kind == 'nocaptions' else f'cannot vet: {exc}'
            row['error_kind'] = exc.kind
            streak = streak + 1 if exc.kind == 'ratelimit' else 0
        rows.append(row)
        if streak >= 2:
            stopped = 'stopped early: YouTube rate limited two videos in a row (HTTP 429); wait a minute and scan fewer'
            break
    rows.sort(key=scan_rank)
    out = {'query': a.query, 'terms': terms, 'ranked': rows,
           'dropped': [{'id': r['id'], 'title': r['title'], 'why': why} for r, why in dropped], 'stopped': stopped}
    if a.json:
        return print(json.dumps(out, indent=1))
    print(f'scan "{a.query}" for: {", ".join(terms)}')
    for k, row in enumerate(rows, 1):
        print(f"\n{k}. {row['title']} | {row['channel']} | {row.get('upload_date') or '?'} | {clock(row.get('duration'))}")
        print(f"   {row['url']}")
        if row['status'] != 'ok':
            print(f"   {row['status']}")
            continue
        emb = {True: 'yes', False: 'no'}.get(row.get('embeddable'), '?')
        print(f"   captions: {row['track']} | embeddable: {emb} | coverage: {row['coverage']:.0%}"
              + (f" (not heard: {', '.join(row['not_heard'])})" if row['not_heard'] else ''))
        for s in row['segments']:
            print_segment(s, '   ')
    if out['dropped']:
        print('\ndropped: ' + '; '.join(f"{d['title'][:50]} ({d['why']})" for d in out['dropped']))
    if stopped:
        print('\n' + stopped)


def main(argv=None):
    p = argparse.ArgumentParser(prog='yt.py', description=(__doc__ or '').split('\n\n')[0],
                                epilog='Exit codes: 0 ok, 1 unavailable or no captions, 3 yt-dlp missing, 4 network, 5 rate limited, 6 quote not confirmed.')
    sub = p.add_subparsers(dest='cmd', required=True)

    def add(name, help_text):
        sp = sub.add_parser(name, help=help_text, description=help_text)
        sp.add_argument('--json', action='store_true', help='print machine-readable JSON')
        return sp

    s = add('search', 'Search YouTube; titles, channels, lengths and views only.')
    s.add_argument('query')
    s.add_argument('--n', type=int, default=10, help='how many results (default 10)')
    s = add('info', 'Chapters, caption tracks, embeddable and dates for one video.')
    s.add_argument('video', help='URL or 11-character id')
    s.add_argument('--lang', default='en', help='caption language to report on (default en)')
    s = add('transcript', 'Timestamped transcript from one caption track, rolling captions deduped.')
    s.add_argument('video', help='URL or 11-character id')
    s.add_argument('--lang', default='en', help='caption language (default en)')
    s.add_argument('--plain', action='store_true', help='text without timestamps')
    s = add('find', 'Segments of one video where the terms are spoken.')
    s.add_argument('video', help='URL or 11-character id')
    s.add_argument('--terms', required=True, help='comma-separated must-say terms')
    s.add_argument('--lang', default='en', help='caption language (default en)')
    s.add_argument('--window', type=int, default=60, help='seconds of each sliding window, scored by distinct terms (default 60)')
    s.add_argument('--top', type=int, default=3, help='segments to show, plus matching chapters (default 3)')
    s.add_argument('--pad', type=int, default=20, help='seconds added before and after (default 20)')
    s = add('scan', 'Search, then read each candidate and rank by the terms it says.')
    s.add_argument('query')
    s.add_argument('--terms', required=True, help='comma-separated must-say terms')
    s.add_argument('--n', type=int, default=8, help='search results to consider (default 8)')
    s.add_argument('--lang', default='en', help='caption language (default en)')
    s.add_argument('--max-minutes', type=float, default=90, help='drop longer videos (default 90)')
    s = add('quote', 'Confirm words are said in the video within 20 seconds of a time; prints the words to show.')
    s.add_argument('video', help='URL or 11-character id')
    s.add_argument('text', help='the quote, copied from the transcript; "..." marks a cut')
    s.add_argument('--at', required=True, help='where it is said: m:ss, h:mm:ss or seconds')
    s.add_argument('--window', type=float, default=QUOTE_WINDOW, help=f'seconds either side of --at (default {QUOTE_WINDOW})')
    s.add_argument('--lang', default='en', help='caption language (default en)')
    s = add('course', 'Confirm a quote appears in a course text file (slides, notes, a page saved as text).')
    s.add_argument('file', help='a .txt or .md file; turn a PDF into text first')
    s.add_argument('text', help='the quote, copied from the file; "..." marks a cut')
    a = p.parse_args(argv)
    if a.cmd != 'course' and not shutil.which('yt-dlp'):
        print(MISSING, file=sys.stderr)
        return 3
    try:
        rc = {'search': cmd_search, 'info': cmd_info, 'transcript': cmd_transcript, 'find': cmd_find, 'scan': cmd_scan,
              'quote': cmd_quote, 'course': cmd_course}[a.cmd](a)
        if rc:
            return rc
    except YTError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT.get(exc.kind, 1)
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == '__main__':
    sys.exit(main())
