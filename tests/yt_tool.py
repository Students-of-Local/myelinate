#!/usr/bin/env python3
"""Offline tests for scripts/yt.py against a fake yt-dlp that serves tests/fixtures/yt/.

The fake goes first on PATH (a real yt-dlp may be installed), TMPDIR points at a
fresh folder so the cache is isolated, and MYELINATE_YT_PAUSE=0 skips the waits
in the command-line runs. The pause test patches time.sleep in-process instead.

usage: python3 tests/yt_tool.py
"""
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
YT = ROOT / 'scripts' / 'yt.py'
FIX = ROOT / 'tests' / 'fixtures' / 'yt'
FAKE = FIX / 'fake_yt_dlp.py'
WORK = Path(tempfile.mkdtemp(prefix='yt-tool-test-'))
BIN = WORK / 'bin'
EMPTY = WORK / 'empty'
BIN.mkdir()
EMPTY.mkdir()
(BIN / 'yt-dlp').write_text(f'#!{sys.executable}\nimport runpy\nrunpy.run_path({str(FAKE)!r}, run_name="__main__")\n')
(BIN / 'yt-dlp').chmod(0o755)
A, B, F, G, H = 'AAAAAAAAAAA', 'BBBBBBBBBBB', 'FFFFFFFFFFF', 'GGGGGGGGGGG', 'HHHHHHHHHHH'
TERMS = 'anti-periplanar,Zaitsev,strong base,Hofmann'
sys.path.insert(0, str(ROOT / 'scripts'))
import yt  # noqa: E402


class Box:
    """A fresh cache and call log for one test."""
    n = 0

    def __init__(self):
        Box.n += 1
        self.dir = WORK / f'case{Box.n}'
        self.dir.mkdir()
        self.log = self.dir / 'calls.jsonl'

    def calls(self):
        return [json.loads(ln) for ln in self.log.read_text().splitlines()] if self.log.is_file() else []

    def subs(self):
        """The --sub-langs value of every caption run, in order."""
        return [c[c.index('--sub-langs') + 1] for c in self.calls() if '--sub-langs' in c]

    def run(self, *args, path=None, **env):
        e = dict(os.environ, PATH=str(path or BIN) + os.pathsep + os.environ.get('PATH', ''),
                 TMPDIR=str(self.dir), MYELINATE_YT_PAUSE='0', FAKE_YT_LOG=str(self.log))
        e.pop('FAKE_YT_429', None)
        e.pop('FAKE_YT_ALLOW_TLANG', None)
        if path == EMPTY:
            e['PATH'] = str(EMPTY)
        e.update(env)
        p = subprocess.run([sys.executable, str(YT)] + list(args), capture_output=True, text=True, env=e, timeout=60)
        for c in self.calls():  # every run: no downloads, exact single tracks, never a pattern
            assert '--flat-playlist' in c or '--skip-download' in c, c
            if '--sub-langs' in c:
                langs = c[c.index('--sub-langs') + 1]
                assert ',' not in langs and '.*' not in langs and langs != 'all', c
        return p.returncode, p.stdout, p.stderr


def phrases_in(vtt):
    """Each spoken phrase of a rolling VTT is the one line that carries <c> word tags."""
    return [re.sub(r'<[^>]*>', '', ln).replace('&amp;', '&') for ln in vtt.splitlines() if '<c>' in ln]


# ---------- yt-dlp missing, help ----------

def test_missing_ytdlp_exits_3_with_one_line():
    b = Box()
    code, out, err = b.run('transcript', A, path=EMPTY)
    assert code == 3, (code, err)
    assert err.strip() == yt.MISSING and len(err.strip().splitlines()) == 1, err
    assert 'Show transcript' in err and 'paste' in err and 'transcript tool' in err, err
    assert not out


def test_help_runs_without_ytdlp():
    b = Box()
    for args in (['--help'], ['search', '--help'], ['info', '--help'], ['transcript', '--help'],
                 ['find', '--help'], ['scan', '--help']):
        code, out, err = b.run(*args, path=EMPTY)
        assert code == 0 and 'usage:' in out, (args, code, err)
        if len(args) == 2:
            assert '--json' in out, args


# ---------- transcripts and tracks ----------

def test_rolling_captions_give_each_phrase_once():
    b = Box()
    code, out, err = b.run('transcript', A, '--json')
    assert code == 0, err
    tr = json.loads(out)
    want = phrases_in((FIX / f'{A}.en-orig.vtt').read_text())
    assert [c['text'] for c in tr['cues']] == want, 'cues are not the phrases, once each, in order'
    starts = [c['start'] for c in tr['cues']]
    assert starts[0] == 0.0 and all(t % 4 == 0 for t in starts), 'a cue is timed from its 10ms repeat, not its start'
    text = ' '.join(p['text'] for p in tr['paragraphs'])
    for phrase in want:
        assert text.count(phrase) == 1, phrase
    assert '<c>' not in text and '&amp;' not in text and 'rates & mechanisms' in text


def test_transcript_text_names_track_stamps_and_chapters():
    b = Box()
    code, out, err = b.run('transcript', A)
    assert code == 0, err
    lines = out.splitlines()
    assert lines[0].startswith('track: auto en-orig'), lines[0]
    assert '## Anti-periplanar geometry' in lines and '## Practice problems' in lines
    assert re.search(r'^\[2:\d\d\] ', out, re.M), 'no [m:ss] stamps'
    tr = json.loads(b.run('transcript', A, '--json')[1])
    spans = [p['end'] - p['start'] for p in tr['paragraphs']]
    assert max(spans) <= 44 and sum(1 for s in spans if s >= 20) >= 3, spans
    code, out, _ = b.run('transcript', A, '--plain')
    assert code == 0 and not re.search(r'^\[\d', out, re.M)


def test_manual_track_comes_first():
    b = Box()
    code, out, err = b.run('transcript', F)
    assert code == 0, err
    assert out.splitlines()[0] == 'track: manual en', out.splitlines()[0]
    assert b.subs() == ['en'] and '--write-subs' in b.calls()[-1] and '--write-auto-subs' not in b.calls()[-1]
    cues = json.loads(b.run('transcript', F, '--json')[1])['cues']
    assert [c['text'] for c in cues] == ['Welcome to organic chemistry.', 'Today: E1 & E2 in brief.',
                                         'With a strong base, the Zaitsev product is more substituted.',
                                         "That's it for today.", 'Thanks for watching.'], cues


def test_translated_en_is_skipped_for_en_orig():
    b = Box()
    code, out, err = b.run('transcript', G)
    assert code == 0, err
    assert out.splitlines()[0].startswith('track: auto en-orig'), out
    assert b.subs() == [re.escape('en-orig')], b.subs()


def test_naive_one_run_fails_where_yt_py_succeeds():
    b = Box()
    with tempfile.TemporaryDirectory() as tmp:
        p = subprocess.run([sys.executable, str(FAKE), '--load-info-json', str(FIX / f'info_{G}.json'), '--skip-download',
                            '--write-subs', '--write-auto-subs', '--sub-langs', 'en,en-orig', '--sub-format', 'vtt',
                            '-o', os.path.join(tmp, 'sub')], capture_output=True, text=True)
    assert p.returncode == 1 and 'HTTP Error 429' in p.stderr, (p.returncode, p.stderr)
    code, out, err = b.run('transcript', G)
    assert code == 0 and 'Zaitsev' in out, err


def test_429_moves_to_the_next_track_once():
    b = Box()
    code, out, err = b.run('transcript', A, FAKE_YT_429=f'{A}:en-orig')
    assert code == 0, err
    assert out.splitlines()[0].startswith('track: auto en '), out.splitlines()[0]
    assert 'plainautotrack' in out
    assert b.subs() == [re.escape('en-orig'), 'en'], b.subs()
    assert 'trying the next track' in err


def test_track_order_reaches_own_language_then_translation():
    b = Box()
    code, out, err = b.run('transcript', H, FAKE_YT_429=f'{H}:es-orig,{H}:es')
    assert code == 5, (code, err)
    assert b.subs() == [re.escape('es-orig'), 'es', 'en'], b.subs()
    assert len(set(b.subs())) == len(b.subs()), 'a track was asked for twice'
    assert '429' in err
    b = Box()
    code, out, err = b.run('transcript', H, FAKE_YT_429=f'{H}:es-orig')
    assert code == 0 and out.splitlines()[0].startswith('track: auto es '), out
    b = Box()
    code, out, err = b.run('transcript', H, FAKE_YT_429=f'{H}:es-orig,{H}:es', FAKE_YT_ALLOW_TLANG='1')
    assert code == 0, err
    assert out.splitlines()[0] == 'track: translated from es (machine translation)', out.splitlines()[0]


def test_candidate_order():
    info = {'language': 'en',
            'subtitles': {'en-GB': [{'url': 'x'}], 'fr': [{'url': 'x'}], 'live_chat': [{'url': 'x'}]},
            'automatic_captions': {'en': [{'url': 'u&tlang=en'}], 'en-orig': [{'url': 'u'}], 'de': [{'url': 'u&tlang=de'}]}}
    assert yt.candidates(info) == [('manual', 'en-GB', 'manual'), ('auto', 'en-orig', 'auto'), ('auto', 'en', 'translated')]
    info = {'subtitles': {'en': [{'url': 'x'}]},
            'automatic_captions': {'en': [{'url': 'u'}], 'es-orig': [{'url': 'u'}], 'es': [{'url': 'u'}]}}
    assert yt.candidates(info) == [('manual', 'en', 'manual'), ('auto', 'en', 'auto'), ('auto', 'es-orig', 'auto'), ('auto', 'es', 'auto')]
    assert yt.candidates({'subtitles': {}, 'automatic_captions': {}}) == []


def test_no_captions_exits_1_cannot_vet():
    b = Box()
    code, out, err = b.run('transcript', B)
    assert code == 1 and 'cannot vet' in err and not b.subs(), (code, err)
    code, out, err = b.run('info', 'ZZZZZZZZZZZ')
    assert code == 1 and 'unavailable' in err, (code, err)


# ---------- find ----------

def test_terms_match_prefixes_and_any_hyphen_spacing():
    cues = yt.parse_vtt((FIX / f'{A}.en-orig.vtt').read_text())
    for form in ('anti-periplanar', 'anti periplanar', 'antiperiplanar', 'Anti‑periplanar'):
        times = [h['time'] for h in yt.find_hits(cues, [form])]
        assert times == [144.0, 204.0], (form, times)
    assert [h['time'] for h in yt.find_hits(cues, ['eliminat'])] == [0.0, 4.0]
    at = yt.term_matcher('anti-periplanar')
    for words in (['anti', 'peri', 'planar'], ['an', 'tiperiplanar'], ['antiperiplanarity']):
        assert at(words, 0) == len(words), words
    assert not at(['periplanar'], 0) and not at(['anti', 'aromatic'], 0)
    b = Box()
    code, out, err = b.run('find', A, '--terms', 'eliminat', '--json')
    assert code == 0 and json.loads(out)['coverage'] == 1.0, err


def test_find_segments_links_and_chapters():
    b = Box()
    code, out, err = b.run('find', A, '--terms', TERMS, '--json')
    assert code == 0, err
    res = json.loads(out)
    assert res['coverage'] == 1.0 and res['not_heard'] == []
    cue_starts = {c['start'] for c in yt.parse_vtt((FIX / f'{A}.en-orig.vtt').read_text())}
    chapters = [s for s in res['segments'] if s['from_chapter']]
    plain = [s for s in res['segments'] if not s['from_chapter']]
    assert [s['chapter'] for s in chapters] == ['Anti-periplanar geometry'], chapters
    assert 1 <= len(plain) <= 3
    best = max(plain, key=lambda s: s['distinct'])
    assert best['distinct'] == 4 and best['missing'] == [] and best['start'] <= 144 <= best['end'], best
    assert any(s['start'] <= 424 <= s['end'] and set(s['missing']) == {'anti-periplanar', 'Hofmann'} for s in plain), plain
    for s in res['segments']:
        w = re.fullmatch(rf'https://www\.youtube\.com/watch\?v={A}&t=(\d+)s', s['watch'])
        e = re.fullmatch(rf'https://www\.youtube-nocookie\.com/embed/{A}\?start=(\d+)&end=(\d+)', s['embed'])
        assert w and e, (s['watch'], s['embed'])
        assert int(w.group(1)) == int(e.group(1)) == int(s['start']) < int(e.group(2)), s
        assert s['preview'] and set(s['hits']) | set(s['missing']) == set(TERMS.split(','))
    for s in plain:
        assert s['start'] in cue_starts, s['start']
    code, out, err = b.run('find', A, '--terms', TERMS)
    assert out.splitlines()[0].startswith('track: auto en-orig') and out.splitlines()[1].startswith('coverage: 100%')
    assert '(chapter: Anti-periplanar geometry)' in out
    res = json.loads(b.run('find', A, '--terms', TERMS, '--top', '1', '--json')[1])
    assert len([s for s in res['segments'] if not s['from_chapter']]) == 1


def test_sliding_window_takes_best_then_merges():
    def hit(term, t):
        return {'term': term, 'time': float(t), 'end': t + 3.0}
    hits = [hit('a', 0), hit('a', 100), hit('b', 110), hit('c', 120), hit('a', 300)]
    spans = yt.best_spans(hits, 60, 2, 300)
    assert spans == [{'start': 100.0, 'end': 123.0}, {'start': 0.0, 'end': 3.0}], spans
    hits = [hit('a', 0), hit('b', 50), hit('c', 100), hit('a', 150), hit('b', 200)]
    assert yt.best_spans(hits, 60, 3, 120) == [{'start': 0.0, 'end': 103.0}, {'start': 150.0, 'end': 203.0}]


def test_padding_never_joins_spans_past_the_cap():
    # Hits every 20s for ten minutes: best_spans caps each span at 300s, and the padding
    # that makes two capped spans touch must not join them into one long segment.
    cues = [{'start': float(t), 'end': t + 10.0, 'text': ('anti-periplanar Zaitsev' if t % 20 == 0 else 'filler words')}
            for t in range(0, 600, 10)]
    res = yt.find_segments({'id': A, 'cues': cues, 'chapters': []}, ['anti-periplanar', 'Zaitsev'])
    assert res['segments'] and all(s['length'] <= 300 + 2 * 20 + 10 for s in res['segments']), \
        [s['length'] for s in res['segments']]


# ---------- search, info, scan ----------

def test_search_marks_shorts():
    b = Box()
    code, out, err = b.run('search', 'E2 elimination', '--n', '9')
    assert code == 0, err
    assert [ln for ln in out.splitlines() if '[short]' in ln] == [ln for ln in out.splitlines() if 'CCCCCCCCCCC' in ln], out
    assert 'entry with no id' not in out
    assert b.calls()[0][-1] == 'ytsearch9:E2 elimination' and '--flat-playlist' in b.calls()[0]
    res = json.loads(b.run('search', 'E2', '--json')[1])
    assert [r['id'] for r in res if r['short']] == ['CCCCCCCCCCC']


def test_info_reports_what_vetting_needs():
    b = Box()
    code, out, err = b.run('info', f'https://youtu.be/{A}')
    assert code == 0, err
    for need in ('embeddable: True', 'uploaded 2024-01-15', '10:00', 'en-orig yes', 'Fixture Chem',
                 '2:00 to 6:40  Anti-periplanar geometry', 'best track for en: auto en-orig'):
        assert need in out, need
    s = json.loads(b.run('info', A, '--json')[1])
    assert s['playable_in_embed'] is True and s['captions']['orig'] and len(s['chapters']) == 3
    g = json.loads(b.run('info', G, '--json')[1])
    assert {'lang': 'en', 'translated': True} in g['captions']['auto'] and g['captions']['best'].startswith('auto en-orig')


def test_scan_ranks_drops_and_puts_cannot_vet_last():
    b = Box()
    code, out, err = b.run('scan', 'E2 elimination', '--terms', TERMS, '--json')
    assert code == 0, err
    res = json.loads(out)
    assert [r['id'] for r in res['ranked']] == [A, F, G, B], [r['id'] for r in res['ranked']]
    assert res['ranked'][-1]['status'] == 'no captions: cannot vet'
    why = {d['id']: d['why'] for d in res['dropped']}
    assert why == {'CCCCCCCCCCC': 'short', 'DDDDDDDDDDD': 'over 90 min', 'EEEEEEEEEEE': 'live', 'IIIIIIIIIII': 'live'}, why
    asked = {c[-1][-11:] for c in b.calls() if '-J' in c and '--flat-playlist' not in c}
    assert not asked & {'CCCCCCCCCCC', 'DDDDDDDDDDD', 'EEEEEEEEEEE'}, asked
    assert res['ranked'][1]['kind'] == 'manual' and res['ranked'][1]['embeddable'] is False  # kind outranks embeddable
    assert res['stopped'] is None
    code, out, err = b.run('scan', 'E2 elimination', '--terms', TERMS)
    assert code == 0 and 'no captions: cannot vet' in out and 'dropped: ' in out, out
    assert out.index(A) < out.index(F) < out.index(G) < out.index(B)


def test_scan_rank_order():
    def row(cov=0.5, distinct=2, kind='auto', embed=True, length=60.0, status='ok', err=None):
        r = {'status': status, 'coverage': cov, 'kind': kind, 'embeddable': embed,
             'segments': [{'distinct': distinct, 'length': length}]}
        if err:
            r['error_kind'] = err
        return r
    rows = {'nocap': row(status='no captions: cannot vet', err='nocaptions'), 'limited': row(status='x', err='ratelimit'),
            'long': row(length=200), 'blocked': row(embed=False), 'translated': row(kind='translated'),
            'manual': row(kind='manual', embed=False), 'distinct3': row(distinct=3), 'cov1': row(cov=1.0, distinct=1),
            'short': row(length=30)}
    order = sorted(rows, key=lambda k: yt.scan_rank(rows[k]))
    assert order == ['cov1', 'distinct3', 'manual', 'short', 'long', 'blocked', 'translated', 'limited', 'nocap'], order


def test_scan_stops_after_two_429s():
    b = Box()
    code, out, err = b.run('scan', 'E2 elimination', '--terms', TERMS, '--json', FAKE_YT_429='all')
    assert code == 0, err
    res = json.loads(out)
    assert [r['id'] for r in res['ranked']] == [A, F] and res['stopped'], res
    asked = [c[-1][-11:] for c in b.calls() if '-J' in c and '--flat-playlist' not in c]
    assert asked == [A, F], asked


def test_cache_second_call_makes_no_ytdlp_call():
    b = Box()
    first = b.run('transcript', A)
    n = len(b.calls())
    assert first[0] == 0 and n == 2, b.calls()
    assert (b.dir / 'myelinate-yt' / A / 'transcript-en.json').is_file()
    second = b.run('transcript', A)
    assert second == first and len(b.calls()) == n, 'the second transcript call ran yt-dlp'
    b.run('info', A)
    b.run('find', A, '--terms', TERMS)
    assert len(b.calls()) == n, 'info or find ran yt-dlp with everything cached'


def test_pauses_between_network_steps():
    saved_env, saved_cache, saved_time = dict(os.environ), yt.CACHE, yt.time
    slept = []
    b = Box()
    try:
        os.environ.update(PATH=str(BIN) + os.pathsep + os.environ.get('PATH', ''), FAKE_YT_LOG=str(b.log),
                          FAKE_YT_429=f'{A}:en-orig')
        yt.CACHE, yt.PAUSE_SCALE, yt.NET_CALLS = b.dir / 'myelinate-yt', 1.0, 0
        yt.time = types.SimpleNamespace(sleep=slept.append, time=saved_time.time)  # subprocess keeps the real sleep
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            assert yt.main(['transcript', A]) == 0
        assert slept == [yt.VIDEO_PAUSE, yt.TRACK_PAUSE] == [1.5, 2.0], slept
        del slept[:]
        os.environ.pop('FAKE_YT_429')
        before = len(b.calls())
        with contextlib.redirect_stdout(io.StringIO()):
            assert yt.main(['scan', 'E2', '--terms', TERMS]) == 0
        assert len(slept) == len(b.calls()) - before and all(s >= 1.5 for s in slept), slept
    finally:
        os.environ.clear()
        os.environ.update(saved_env)
        yt.CACHE, yt.time, yt.PAUSE_SCALE = saved_cache, saved_time, 1.0


def main():
    tests = [(k, v) for k, v in globals().items() if k.startswith('test_') and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f'PASS: {name}')
        except Exception:
            failed += 1
            print(f'FAIL: {name}\n' + traceback.format_exc().rstrip())
    print(f'{len(tests) - failed} of {len(tests)} yt.py checks passed.' if not failed else f'{failed} of {len(tests)} failed.')
    return 1 if failed else 0


if __name__ == '__main__':
    try:
        code = main()
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    sys.exit(code)
