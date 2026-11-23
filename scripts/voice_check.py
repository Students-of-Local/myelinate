#!/usr/bin/env python3
"""Check a lesson's narration clips: every line has one, each says its caption, at a good pace and level, in one voice.

    python3 scripts/voice_check.py lesson.json                       # find a Whisper here and check everything
    python3 scripts/voice_check.py lesson.json --audio-dir audio     # where voice.json and the clips are
    python3 scripts/voice_check.py lesson.json --asr none            # skip the speech-to-text round trip on purpose

Checks, in order:
    1. every narration line has a clip, and no clip is left from a sentence that changed
    2. ASR round trip: speech-to-text of each clip matches its caption (word error rate 5% or less overall,
       15% or less per clip, and technical words heard right)
    3. pace: 130 to 165 words a minute overall, 110 to 190 per clip
    4. loudness: -19 LUFS (within 1.5 LU) for mono, true peak -1.5 dBTP or lower, no clipped samples
    5. dead air: no silence over 1.5 s inside a clip (the player adds the pauses between clips)
    6. one voice: one engine and voice in voice.json, one sample rate and channel count
    7. the credits disclose the AI voice (audio.voice.disclose)

Speech-to-text, first found: Python faster_whisper (a cached small.en or base.en model; it downloads only with
--asr-download), the whisper command, whisper.cpp (whisper-cli or whisper-cpp with a ggml model), voxtype.
Needs ffmpeg and ffprobe. This script never installs anything.

Exit codes: 0 READY; 1 NOT READY; 2 bad input.
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import video_check as vc  # noqa: E402

WER_MAX, CLIP_WER_MAX = 0.05, 0.15
PACE_MIN, PACE_MAX = 130, 165
CLIP_PACE_MIN, CLIP_PACE_MAX = 110, 190
CLIP_PACE_WORDS = 5  # shorter lines give a noisy per-clip pace, so only the overall pace counts them
GARBLED = 0.5  # a clip this wrong is one problem; listing each of its words would bury the fix
LUFS_MONO, LUFS_STEREO, LUFS_TOL = -19.0, -16.0, 1.5
TP_MAX, SAMPLE_PEAK_MAX = -1.5, -0.1
DEAD_AIR = 1.5
RERUN = 'Run python3 scripts/video_voice.py on the lesson again.'
ASR_ENGINES = ('faster-whisper', 'whisper', 'whisper-cpp', 'voxtype')
VOXTYPE_HEADERS = ('loading audio file', 'audio format', 'processing', 'vad:', 'no speech detected')
GGML_DIRS = [Path.home() / '.local' / 'share' / 'voxtype' / 'models', Path.home() / '.cache' / 'whisper.cpp']

# Common English words of 7 or more letters. A misheard long word outside this list is treated as a
# technical term that may need a respelling in "pronounce".
COMMON = set('''
about above across actually against already although another anything around because become becomes before
behind believe besides between brought building business certain chapter clearly company compare compared
complete consider contain contains control country current decided describe different directly during
earlier element enough especially evening everyone everything example examples explain explains explained
exactly finally following forward general getting happens happened however hundred important including
instead interest journey keeping language learned learning least letters looking million minutes morning
nothing notice number numbers outside particular perhaps picture possible present pressure probably problem
problems produce question questions quickly reading reason reasons receive remember results running
seconds several similar simple something sometimes started starting station stopped student students
suppose surface teacher thinking thought thousand through together tomorrow towards trouble usually
various whether without working written yesterday second another answers answered becoming beginning
believe brother careful changes changed children college correct covered develop discover discovered
everyday experience explore follows forever further gathered greater heavier history holding imagine
largest lighter limited listen looking machine meaning measure measured message middle moments natural
nearest neither objects opposite ordinary perfect person physical popular position powerful practice
prepare pretty process product purpose quarter quarters reached realize reflect regular remains repeat
returns science sentence separate several shorter simply smaller special spread straight strange
stronger support systems teaching thinking travels traveling turning understand understanding unless
whatever wherever whichever without wonderful afternoon midnight weekend sunlight daylight
outdoors indoors morning evening himself herself yourself ourselves themselves anybody somebody everybody
someone nowhere anywhere somewhere everywhere instead several finished started already shouldn wouldn
couldn doesn haven
'''.split())

ONES = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve',
        'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen']
TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']
SCALES = [(10 ** 12, 'trillion'), (10 ** 9, 'billion'), (10 ** 6, 'million'), (1000, 'thousand'), (100, 'hundred')]
ORDINAL = {'one': 'first', 'two': 'second', 'three': 'third', 'five': 'fifth', 'eight': 'eighth', 'nine': 'ninth',
           'twelve': 'twelfth'}
FRACTIONS = {'1/2': 'one half', '1/3': 'one third', '2/3': 'two thirds', '1/4': 'one quarter', '3/4': 'three quarters'}


# ---------- Text ----------

def number_words(n):
    """Spell a whole number: 42 -> 'forty two'. Hyphens are left out because both sides drop them."""
    n = int(n)
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ('' if n % 10 == 0 else ' ' + ONES[n % 10])
    for value, word in SCALES:
        if n >= value:
            head, rest = divmod(n, value)
            return number_words(head) + ' ' + word + ('' if rest == 0 else ' ' + number_words(rest))
    return str(n)


def ordinal_words(n):
    words = number_words(n).split()
    last = words[-1]
    if last in ORDINAL:
        words[-1] = ORDINAL[last]
    elif last.endswith('y'):
        words[-1] = last[:-1] + 'ieth'
    else:
        words[-1] = last + 'th'
    return ' '.join(words)


def spell_numbers(text):
    text = re.sub(r'(?<=\d),(?=\d{3}\b)', '', text)
    for frac, words in FRACTIONS.items():
        text = re.sub(r'(?<![\d/])' + re.escape(frac) + r'(?![\d/])', ' ' + words + ' ', text)
    text = re.sub(r'(\d+(?:\.\d+)?)\s*%', r'\1 percent', text)
    text = re.sub(r'(?<!\d)(\d+)(st|nd|rd|th)\b', lambda m: ' ' + ordinal_words(m.group(1)) + ' ', text)
    text = re.sub(r'(?<![\d.])(\d*)\.(\d+)', lambda m: ' ' + (number_words(m.group(1)) if m.group(1) else 'zero') + ' point '
                  + ' '.join(ONES[int(d)] for d in m.group(2)) + ' ', text)
    return re.sub(r'\d+', lambda m: ' ' + number_words(m.group(0)) + ' ', text)


def normalize(text):
    """Lowercase words with numbers spelled out, hyphens as spaces and no punctuation."""
    text = str(text).lower().replace('’', "'").replace('‘', "'")
    text = spell_numbers(text)
    text = re.sub(r"'", '', text)
    text = re.sub(r'[-\u2010-\u2015]', ' ', text)  # hyphen and the Unicode dashes
    return re.sub(r'[^a-z0-9 ]+', ' ', text).split()


def align(ref, hyp):
    """Word edit distance plus the reference words that were substituted or dropped."""
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]))
    missed, i, j = [], n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            if ref[i - 1] != hyp[j - 1]:
                missed.append((ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            missed.append((ref[i - 1], ''))
            i -= 1
        else:
            j -= 1
    return d[n][m], list(reversed(missed))


def wer(ref_text, hyp_text):
    ref, hyp = normalize(ref_text), normalize(hyp_text)
    edits, _ = align(ref, hyp)
    return edits / max(1, len(ref))


def parse_voxtype(stdout):
    """The transcript from `voxtype transcribe` output: drop its header lines and keep the text."""
    keep = []
    for line in stdout.splitlines():
        s = line.strip()
        if not s or s.lower().startswith(VOXTYPE_HEADERS) or s.startswith(('whisper_', 'ggml_')):
            continue
        keep.append(s)
    return ' '.join(keep)


# ---------- Audio measurements ----------

def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def probe(path):
    r = run(['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=sample_rate,channels:format=duration',
             '-of', 'json', str(path)])
    try:
        data = json.loads(r.stdout)
        st = data['streams'][0]
        return {'rate': int(st['sample_rate']), 'channels': int(st['channels']), 'duration': float(data['format']['duration'])}
    except (ValueError, KeyError, IndexError):
        return None


def _num(pattern, text):
    m = re.search(pattern, text, re.S)
    if not m:
        return None
    return None if m.group(1).startswith('-inf') or m.group(1) == 'inf' else float(m.group(1))


def loudness(path):
    """{'i': integrated LUFS, 'tp': true peak dBTP, 'peak': sample peak dBFS, 'silences': [(start, length)], 'edges': s}."""
    r = run(['ffmpeg', '-hide_banner', '-nostats', '-nostdin', '-i', str(path), '-af',
             'ebur128=peak=sample+true,silencedetect=n=-40dB:d=0.05', '-f', 'null', '-'])
    err = r.stderr
    summary = err[err.rfind('Summary:'):] if 'Summary:' in err else ''
    out = {'i': _num(r'Integrated loudness:\s*I:\s*(-?inf|-?[\d.]+)', summary),
           'tp': _num(r'True peak:\s*Peak:\s*(-?inf|-?[\d.]+)', summary),
           'peak': _num(r'Sample peak:\s*Peak:\s*(-?inf|-?[\d.]+)', summary)}
    starts = [float(x) for x in re.findall(r'silence_start: (-?[\d.]+)', err)]
    ends = [(float(a), float(b)) for a, b in re.findall(r'silence_end: (-?[\d.]+) \| silence_duration: ([\d.]+)', err)]
    sil = []
    for k, s in enumerate(starts):
        if k < len(ends):
            sil.append((max(0.0, s), ends[k][1]))
        else:
            sil.append((max(0.0, s), None))  # runs to the end of the clip
    out['silences'] = sil
    return out


def speech_seconds(duration, silences):
    """Clip length without the silence at its start and end."""
    lead = silences[0][1] if silences and silences[0][0] <= 0.01 and silences[0][1] else 0.0
    tail = 0.0
    if silences and silences[-1][1] is None:
        tail = max(0.0, duration - silences[-1][0])
    return max(0.05, duration - lead - tail)


def longest_silence(duration, silences):
    longest = 0.0
    for start, length in silences:
        longest = max(longest, length if length is not None else duration - start)
    return longest


# ---------- Speech to text ----------

def ggml_model():
    env = os.environ.get('WHISPER_CPP_MODEL', '')
    if env and Path(env).is_file():
        return Path(env)
    for d in GGML_DIRS:
        for name in ('ggml-small.en.bin', 'ggml-base.en.bin', 'ggml-small.bin', 'ggml-base.bin'):
            if (d / name).is_file():
                return d / name
    return None


def faster_whisper_model(download):
    if importlib.util.find_spec('faster_whisper') is None:
        return None
    try:
        from faster_whisper import WhisperModel
    except Exception:
        return None
    for name in ('small.en', 'base.en'):
        try:
            return WhisperModel(name, device='cpu', compute_type='int8', local_files_only=not download)
        except Exception:
            continue
    return None


def whisper_cached():
    base = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'whisper'
    for name in ('small.en', 'base.en'):
        if (base / f'{name}.pt').is_file():
            return name
    return None


class Asr:
    """Finds one speech-to-text engine and transcribes 16 kHz mono WAV files with it."""

    def __init__(self, want='auto', download=False):
        self.name, self.why, self.model = None, '', None
        order = ASR_ENGINES if want == 'auto' else (want,)
        for name in order:
            if name == 'faster-whisper':
                self.model = faster_whisper_model(download)
                if self.model:
                    self.name = name
            elif name == 'whisper' and shutil.which('whisper'):
                self.cached = whisper_cached()
                if self.cached or download:
                    self.cached = self.cached or 'small.en'
                    self.name = name
            elif name == 'whisper-cpp':
                exe = shutil.which('whisper-cli') or shutil.which('whisper-cpp')
                if exe and ggml_model():
                    self.exe, self.ggml, self.name = exe, ggml_model(), name
            elif name == 'voxtype' and shutil.which('voxtype'):
                self.name = name
            if self.name:
                return

    def transcribe(self, wav):
        """The words heard in the clip, or None when the engine failed (which is not the same as hearing nothing)."""
        if self.name == 'faster-whisper':
            segments, _ = self.model.transcribe(str(wav), language='en', beam_size=5)
            return ' '.join(s.text.strip() for s in segments)
        if self.name == 'whisper':
            with tempfile.TemporaryDirectory() as d:
                run(['whisper', str(wav), '--model', self.cached, '--language', 'en', '--output_format', 'txt',
                     '--output_dir', d, '--fp16', 'False'])
                txt = Path(d) / (Path(wav).stem + '.txt')
                return txt.read_text().strip() if txt.is_file() else None
        if self.name == 'whisper-cpp':
            r = run([self.exe, '-m', str(self.ggml), '-f', str(wav), '-nt', '-np', '-l', 'en'])
            return ' '.join(r.stdout.split()) if r.returncode == 0 else None
        if self.name == 'voxtype':
            # CPU first: a GPU another program holds can run out of memory and abort voxtype.
            # Then voxtype's own settings, then its default model.
            cpu = dict(os.environ, GGML_VK_VISIBLE_DEVICES='')
            for cmd, env in ((['voxtype', '-q', '--model', 'small.en', 'transcribe', str(wav)], cpu),
                             (['voxtype', '-q', '--model', 'small.en', 'transcribe', str(wav)], None),
                             (['voxtype', '-q', 'transcribe', str(wav)], None)):
                r = subprocess.run(cmd, capture_output=True, text=True, env=env)
                if r.returncode == 0 and 'processing' in r.stdout.lower():
                    return parse_voxtype(r.stdout)
            self.why = (r.stderr.strip().splitlines() or [f'exit {r.returncode}'])[-1][:200]
            return None
        return None


# ---------- The check ----------

def term_words(lesson):
    """Normalized words that are technical terms: "pronounce" keys and term words shown on screen. Maps word -> key."""
    terms = {}
    pron = lesson.get('pronounce') if isinstance(lesson.get('pronounce'), dict) else {}
    for key in pron:
        for w in normalize(key):
            terms[w] = key
    for scene in lesson.get('scenes') or []:
        if not isinstance(scene, dict):
            continue
        for beat in scene.get('beats') or []:
            for el in (beat.get('show') if isinstance(beat, dict) and isinstance(beat.get('show'), list) else []):
                if isinstance(el, dict) and el.get('type') == 'term' and isinstance(el.get('word'), str):
                    for w in normalize(el['word']):
                        terms.setdefault(w, None)
    return terms


def is_technical(word, terms):
    return word in terms or (len(word) >= 7 and word.isalpha() and word not in COMMON)


def check(lesson_path, audio_dir=None, asr='auto', download=False, partial=False, lines=None):
    """Return (problems, notes, summary). A problem is (where, what, fix)."""
    problems, notes = [], []
    lesson_path = Path(lesson_path)
    lesson, _ = vc.read_lesson(lesson_path)
    if not isinstance(lesson, dict):
        raise ValueError('The lesson is not one JSON object.')
    if lines is None:
        import video_voice
        lines = video_voice.plan_lines(lesson_path)
    lesson_dir = lesson_path.resolve().parent
    audio = lesson.get('audio') if isinstance(lesson.get('audio'), dict) else {}
    mapped = audio.get('clips') if isinstance(audio.get('clips'), dict) else {}
    if audio_dir:
        adir = Path(audio_dir).resolve()
    elif mapped:
        adir = (lesson_dir / str(next(iter(mapped.values())))).parent
    else:
        adir = lesson_dir / 'audio'

    # 1. Every line has a clip; no stale clips.
    keys = [k for k, _ in lines]
    stale = sorted(k for k in mapped if k not in keys)
    if stale:
        problems.append(('"audio.clips"', f'has {len(stale)} clip(s) for sentences that are gone or changed: {", ".join(stale[:5])}.', RERUN))
    present = []
    missing = 0
    for n, (key, text) in enumerate(lines, 1):
        where = f'Line {n} ({key}, "{text[:48]}")'
        path = None
        if key in mapped:
            path = lesson_dir / str(mapped[key])
            if not path.is_file():
                problems.append((where, f'names the clip {mapped[key]}, but that file is missing.', RERUN))
                continue
        else:
            for ext in ('.mp3', '.m4a'):
                if (adir / (key + ext)).is_file():
                    path = adir / (key + ext)
            if partial and path is None:
                missing += 1
                continue
            if path is None:
                problems.append((where, 'has no clip.', RERUN))
                continue
            problems.append((where, f'has the file {path.name} but it is not in "audio.clips".', RERUN))
        present.append((n, key, text, path))
    if partial:
        notes.append(f'Partial check (sample run): {len(present)} of {len(lines)} lines have clips; the rest were not checked.')

    # 7. Disclosure.
    voice = audio.get('voice') if isinstance(audio.get('voice'), dict) else {}
    if not str(voice.get('disclose', '')).strip():
        problems.append(('"audio.voice.disclose"', 'is missing, so the credits never say the voice is AI.',
                         'Rerun python3 scripts/video_voice.py, or add "disclose": "Narration is an AI voice: <model> (<voice>)." to "audio.voice".'))

    # 6. One voice.
    vj = None
    try:
        vj = json.loads((adir / 'voice.json').read_text())
    except (OSError, ValueError):
        pass
    if present:
        if not isinstance(vj, dict) or not isinstance(vj.get('clips'), dict):
            problems.append((f'{adir / "voice.json"}', 'is missing, so nothing shows the clips share one voice.', RERUN))
        else:
            eng, name = vj.get('engine'), vj.get('voice')
            mixed = sorted({f'{e.get("engine", eng)}/{e.get("voice", name)}' for e in vj['clips'].values() if isinstance(e, dict)}
                           - {f'{eng}/{name}'})
            if mixed:
                problems.append(('voice.json', f'mixes voices: {eng}/{name} and {", ".join(mixed)}.',
                                 'Use one engine and one voice for the whole lesson. ' + RERUN))
            if voice and (voice.get('engine') != eng or voice.get('name') != name):
                problems.append(('"audio.voice"', f'says {voice.get("engine")}/{voice.get("name")} but voice.json says {eng}/{name}.', RERUN))
            stray = [k for _, k, _, _ in present if k not in vj['clips']]
            if stray:
                problems.append(('voice.json', f'does not list {len(stray)} clip(s), such as {stray[0]}, so their voice is unknown.', RERUN))

    # Per clip: format, loudness, dead air, pace.
    info = {}
    formats = set()
    for n, key, text, path in present:
        where = f'Line {n} ({key})'
        p = probe(path)
        if not p:
            problems.append((where, f'{path.name} is not a readable audio file.', RERUN))
            continue
        lv = loudness(path)
        info[key] = (p, lv)
        formats.add((p['rate'], p['channels']))
        target = LUFS_MONO if p['channels'] == 1 else LUFS_STEREO
        if lv['i'] is None or abs(lv['i'] - target) > LUFS_TOL:
            got = 'silent' if lv['i'] is None else f'{lv["i"]:.1f} LUFS'
            problems.append((where, f'is {got}; it should be {target:.0f} LUFS within {LUFS_TOL} LU.', RERUN + ' It levels every clip.'))
        if lv['tp'] is not None and lv['tp'] > TP_MAX:
            problems.append((where, f'peaks at {lv["tp"]:.1f} dBTP, over {TP_MAX} dBTP.', RERUN + ' It levels every clip.'))
        if lv['peak'] is not None and lv['peak'] >= SAMPLE_PEAK_MAX:
            problems.append((where, f'clips: samples reach {lv["peak"]:.1f} dBFS.', RERUN + ' It levels every clip.'))
        gap = longest_silence(p['duration'], lv['silences'])
        if gap > DEAD_AIR:
            problems.append((where, f'has {gap:.1f} s of silence inside it.',
                             'Pauses belong between clips, not inside them. Remove the extra punctuation or line break in this sentence, then ' + RERUN.lower()))
    if len(formats) > 1:
        problems.append(('The clips', 'use different formats: ' + ', '.join(f'{r} Hz {c} ch' for r, c in sorted(formats)) + '.',
                         'Use one engine and one voice for the whole lesson. ' + RERUN))
    total_words, total_secs = 0, 0.0
    for n, key, text, path in present:
        if key not in info:
            continue
        p, lv = info[key]
        secs = speech_seconds(p['duration'], lv['silences'])
        wc = vc.words(text)
        total_words += wc
        total_secs += secs
        wpm = wc * 60 / secs
        if wc >= CLIP_PACE_WORDS and not CLIP_PACE_MIN <= wpm <= CLIP_PACE_MAX:
            problems.append((f'Line {n} ({key})', f'is spoken at {wpm:.0f} words a minute; keep each clip within {CLIP_PACE_MIN} to {CLIP_PACE_MAX}.',
                             'Check the clip for a stretched or rushed word, then ' + RERUN.lower()))
    pace = total_words * 60 / total_secs if total_secs else 0
    if total_secs and not PACE_MIN <= pace <= PACE_MAX:
        problems.append(('The narration', f'runs at {pace:.0f} words a minute; it should be {PACE_MIN} to {PACE_MAX}.',
                         'Use a voice or speed setting that lands in range, then ' + RERUN.lower()))

    # 2. ASR round trip.
    round_trip = None
    if asr == 'none':
        notes.append('ASR round trip skipped by request (--asr none).')
    else:
        engine = Asr(asr, download)
        if not engine.name:
            label = 'no Whisper found' if asr == 'auto' else f'{asr} not found'
            problems.append(('ASR round trip did not run:', label + '.',
                             'Run this check where faster-whisper, whisper, whisper.cpp or voxtype is installed, or pass --asr none to skip it on purpose.'))
        else:
            edits_total, ref_total, flagged = 0, 0, {}
            terms = term_words(lesson)
            pron = lesson.get('pronounce') if isinstance(lesson.get('pronounce'), dict) else {}
            with tempfile.TemporaryDirectory() as d:
                for n, key, text, path in present:
                    wav = Path(d) / f'{key}.wav'
                    run(['ffmpeg', '-hide_banner', '-nostdin', '-y', '-i', str(path), '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(wav)])
                    heard = engine.transcribe(wav)
                    if heard is None:
                        problems.append((f'Line {n} ({key})', f'could not be transcribed: {engine.name} failed ({engine.why or "no output"}).',
                                         'Run the check again. If it fails again, pass --asr with another engine, or --asr none to skip the round trip on purpose.'))
                        continue
                    ref, hyp = normalize(text), normalize(heard)
                    edits, missed = align(ref, hyp)
                    edits_total += edits
                    ref_total += len(ref)
                    clip_wer = edits / max(1, len(ref))
                    if clip_wer > CLIP_WER_MAX:
                        problems.append((f'Line {n} ({key})', f'word error rate {clip_wer:.0%}: speech-to-text heard "{heard.strip()[:90]}".',
                                         'Listen to the clip. If a word is said wrong, add it to "pronounce" with a respelling; then ' + RERUN.lower()))
                    for word, got in ([] if clip_wer > GARBLED else missed):
                        if is_technical(word, terms) and word not in flagged:
                            flagged[word] = True
                            heard_as = f'"{got}"' if got else 'nothing'
                            owner = terms.get(word) or next((k for k in pron if word in normalize(k)), None)
                            if owner and owner in pron:
                                fix = f'Change the respelling of "{owner}" in "pronounce" (now "{pron[owner]}") to one that sounds right, then ' + RERUN.lower()
                            else:
                                fix = f'Add "{word}": "<respelling>" to "pronounce", where <respelling> spells how it sounds (like "uh-LEEL"), then ' + RERUN.lower()
                            problems.append((f'Line {n} ({key})', f'the technical word "{word}" was heard as {heard_as}.', fix))
            round_trip = edits_total / ref_total if ref_total else None
            if round_trip is not None and round_trip > WER_MAX:
                problems.append(('The narration', f'word error rate is {round_trip:.1%} over the lesson; it must be {WER_MAX:.0%} or less.',
                                 'Fix the lines listed above, then ' + RERUN.lower()))
            if round_trip is not None:
                notes.append(f'ASR round trip with {engine.name}: word error rate {round_trip:.1%} over {ref_total} words.')
    summary = {'lines': len(lines), 'clips': len(present), 'missing': missing, 'pace': round(pace), 'wer': round_trip,
               'seconds': round(total_secs, 1)}
    return problems, notes, summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('lesson')
    ap.add_argument('--audio-dir', help='folder with voice.json and the clips (default: from "audio.clips", or audio/ next to the lesson)')
    ap.add_argument('--asr', default='auto', choices=('auto',) + ASR_ENGINES + ('none',))
    ap.add_argument('--asr-download', action='store_true', help='let faster-whisper or whisper download a model')
    ap.add_argument('--partial', action='store_true', help='a sample run: lines without clips are not problems')
    ap.add_argument('--json', action='store_true', help='print the result as JSON')
    a = ap.parse_args(argv)
    if not Path(a.lesson).is_file():
        print(f'No such file: {a.lesson}')
        return 2
    if not (shutil.which('ffmpeg') and shutil.which('ffprobe')):
        print('Cannot check: ffmpeg and ffprobe are needed. This script never installs anything.')
        return 2
    try:
        problems, notes, summary = check(a.lesson, a.audio_dir, a.asr, a.asr_download, a.partial)
    except ValueError as exc:
        print(f'Bad input: {exc}')
        return 2
    if a.json:
        print(json.dumps({'problems': problems, 'notes': notes, 'summary': summary}, indent=1))
        return 1 if problems else 0
    for note in notes:
        print('NOTE: ' + note)
    for i, (where, what, fix) in enumerate(problems, 1):
        print(f'{i}. {where} {what}\n   Fix: {fix}')
    wer_text = 'not measured' if summary['wer'] is None else f'{summary["wer"]:.1%} word error rate'
    print(f'Voice: {summary["clips"]} of {summary["lines"]} lines have clips, {summary["seconds"]} s of speech, '
          f'{summary["pace"]} words a minute, {wer_text}.')
    if problems:
        print(f'NOT READY: {len(problems)} problem(s). Fix them in this order, then run the check again.')
        return 1
    print('READY.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
