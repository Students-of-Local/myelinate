#!/usr/bin/env python3
"""Tests for scripts/video_voice.py and scripts/voice_check.py with no real voice engine, no Whisper and no browser.

Clips are tones made with ffmpeg. A fake TTS command (a small Python script) stands in for a real engine,
and a local HTTP server stands in for an OpenAI-compatible endpoint. Needs ffmpeg and ffprobe.

usage: python3 tests/voice_check_test.py
"""
import copy
import http.server
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
VOICE = SCRIPTS / 'video_voice.py'
WORK = Path(tempfile.mkdtemp(prefix='voice-check-test-'))
sys.path.insert(0, str(SCRIPTS))


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


vv = load('video_voice')
vk = load('voice_check')
failures = []

LINES = ['Look up on a clear afternoon and the sky is blue.',
         'Yet the light filling it comes from the Sun, and sunlight looks white.',
         'Rayleigh scattering sends the short blue waves all over the sky.']
LESSON = {'format': 'myelinate-video/1', 'title': 'Test', 'wpm': 145,
          'scenes': [{'title': 'One', 'role': 'intro', 'beats': [{'say': LINES[0]}, {'say': LINES[1]},
                                                                  {'pause': {'ask': 'Why?', 'answer': 'Air', 'why': 'It scatters.'}},
                                                                  {'say': LINES[2], 'show': [{'type': 'term', 'word': 'Rayleigh scattering', 'meaning': 'x'}]}]}]}
FAKE_TTS = '''import subprocess, sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding='utf-8')
with open(sys.argv[3], 'a', encoding='utf-8') as log:
    log.write(text.strip() + '\\n')
secs = len(text.split()) * 60 / 150
subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=22050:cl=mono:d=0.3', '-f', 'lavfi',
                '-i', f'sine=f=300:d={secs}:sample_rate=22050', '-filter_complex', '[0][1]concat=n=2:v=0:a=1', sys.argv[2]], check=True)
'''
BUSY_TTS = '''import sys
print('Refusing to start: GPU is in use by process 4242.')
sys.exit(1)
'''


def check(condition, message):
    if condition:
        print('PASS:', message)
    else:
        print('FAIL:', message)
        failures.append(message)


def ffmpeg(*args):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-nostdin', *args], check=True)


def lesson_dir(name, lesson=None):
    d = WORK / name
    if d.exists():
        shutil.rmtree(d)
    (d / 'audio').mkdir(parents=True)
    path = d / 'lesson.json'
    path.write_text(json.dumps(lesson or LESSON, indent=2) + '\n')
    return d, path


def tone(dest, seconds, kind='good'):
    """A clip at -19 LUFS (good), too quiet, hard clipped, or with 2 s of dead air in the middle."""
    raw = dest.with_suffix('.raw.wav')
    if kind == 'clipped':
        ffmpeg('-f', 'lavfi', '-i', f'aevalsrc=0.999*sgn(sin(300*2*PI*t)):s=24000:d={seconds}', '-ac', '1',
               '-c:a', 'libmp3lame', '-b:a', '128k', str(dest))
        return
    if kind == 'dead':
        half = seconds / 2
        ffmpeg('-f', 'lavfi', '-i', f'sine=f=300:d={half}:sample_rate=24000', '-f', 'lavfi', '-i', 'anullsrc=r=24000:cl=mono:d=2',
               '-f', 'lavfi', '-i', f'sine=f=300:d={half}:sample_rate=24000', '-filter_complex', '[0][1][2]concat=n=3:v=0:a=1', str(raw))
    else:
        ffmpeg('-f', 'lavfi', '-i', f'sine=f=300:d={seconds}:sample_rate=24000', str(raw))
    vv.finish_clip(raw, dest, 'libmp3lame')
    raw.unlink()
    if kind == 'quiet':
        quiet = dest.with_suffix('.q.mp3')
        ffmpeg('-i', str(dest), '-af', 'volume=-12dB', '-c:a', 'libmp3lame', '-b:a', '128k', str(quiet))
        quiet.replace(dest)


def build(name, kinds=None, voice_entries=None, disclose=True, extra_clips=None, lesson=None, lines=None, secs=None):
    """A lesson folder with one clip per line made directly (no engine), voice.json and the lesson's "audio"."""
    lesson = copy.deepcopy(lesson or LESSON)
    d, path = lesson_dir(name, lesson)
    kinds = kinds or {}
    clips, table = {}, {}
    for i, text in enumerate(lines or LINES):
        key = vv.vc.fnv1a(text)
        kind = kinds.get(i, 'good')
        if kind == 'missing':
            continue
        tone(d / 'audio' / f'{key}.mp3', (secs or (lambda x: len(x.split()) * 60 / 150))(text), kind)
        clips[key] = f'audio/{key}.mp3'
        table[key] = {'file': f'{key}.mp3', 'tts_sha256': 'x', 'engine': 'cmd', 'voice': 'v1'}
    table.update(voice_entries or {})
    clips.update(extra_clips or {})
    (d / 'audio' / 'voice.json').write_text(json.dumps({'engine': 'cmd', 'voice': 'v1', 'settings': {}, 'clips': table}))
    lesson['audio'] = {'clips': clips, 'voice': {'engine': 'cmd', 'name': 'v1'}}
    if disclose:
        lesson['audio']['voice']['disclose'] = 'Narration is an AI voice: test (v1).'
    path.write_text(json.dumps(lesson, indent=2) + '\n')
    return d, path


def problems_of(path, **kw):
    kw.setdefault('asr', 'none')
    problems, notes, summary = vk.check(path, **kw)
    return [f'{w} {p}' for w, p, _ in problems], notes, summary


def has(items, text):
    return any(text in x for x in items)


def env_clean(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith('MYELINATE_')}
    env.update(extra)
    return env


def voice(path, *args, env=None):
    r = subprocess.run([sys.executable, str(VOICE), str(path), *args], capture_output=True, text=True, env=env or env_clean())
    return r.returncode, r.stdout + r.stderr


# ---------- Unit tests ----------

def test_pronounce():
    p = {'allele': 'uh-LEEL', 'chi-square': 'KYE-square', 'chi': 'KYE'}
    got = vv.apply_pronounce('Chi-square tests check each Allele; chi values, alleles and Allele-level data.', p)
    check(got == 'KYE-square tests check each uh-LEEL; KYE values, alleles and uh-LEEL-level data.', f'pronounce: whole words, any case, hyphenated keys ({got!r})')
    check(vv.apply_pronounce('No change here.', {}) == 'No change here.', 'pronounce: an empty map changes nothing')
    check(vv.apply_pronounce('Rayleigh  scattering', {'Rayleigh scattering': 'RAY-lee scattering'}) == 'RAY-lee scattering',
          'pronounce: a two-word key matches across extra spaces')


def test_numbers_and_wer():
    n = vk.normalize
    check(n('In 2026, 40% of 1,250 cells') == 'in two thousand twenty six forty percent of one thousand two hundred fifty cells'.split(),
          'normalize: years, percents and thousands are spelled out')
    check(n('0.7 and 3.14') == 'zero point seven and three point one four'.split(), 'normalize: decimals read digit by digit')
    check(n('1/4 of the 21st') == 'one quarter of the twenty first'.split(), 'normalize: a quarter and ordinals')
    check(n('Chi-square, isn’t it?') == 'chi square isnt it'.split(), 'normalize: hyphens split, punctuation and apostrophes drop')
    check(n('forty percent') == n('40%'), 'normalize: spoken and written numbers match')
    check(n('Carriers are 2pq times') == n('Carriers are 2 p q times') == 'carriers are two p q times'.split(), 'normalize: letters run together (2pq) match letters said apart')
    check(vk.wer('Carriers are 2 p q times 50,000, about 990.', 'Carriers are 2pq times 50,000, about 990.') == 0, 'WER: 2pq heard for 2 p q is not an error')
    check(vk.wer('The sky is blue.', 'the sky is blue') == 0, 'WER: case and punctuation do not count')
    check(abs(vk.wer('the sky is blue today', 'the sky blue to day') - 0.6) < 1e-9, 'WER: 1 deletion + 1 substitution + 1 insertion over 5 words is 60%')
    edits, missed = vk.align('rayleigh scattering makes blue'.split(), 'raleigh scattering blue'.split())
    check(edits == 2 and missed == [('rayleigh', 'raleigh'), ('makes', '')], f'align: reports the substituted and dropped words ({missed})')
    check(vk.is_technical('scattering', {}) and not vk.is_technical('because', {}) and vk.is_technical('dna', {'dna': None}),
          'technical words: long uncommon words and listed terms count, common words do not')


VOXTYPE_SAMPLE = '''Loading audio file: "/tmp/x/3e9b6039.wav"
Audio format: 16000 Hz, 1 channel(s), Int
Processing 53794 samples (3.36s)...
VAD: 2.84s speech (84.5% of audio)

 Look up on a clear afternoon and the sky is blue.
'''


def test_voxtype_parse():
    check(vk.parse_voxtype(VOXTYPE_SAMPLE) == 'Look up on a clear afternoon and the sky is blue.', 'voxtype: header lines are dropped')
    silent = 'Loading audio file: "a.wav"\nAudio format: 16000 Hz, 1 channel(s), Int\nProcessing 16000 samples (1.00s)...\nVAD: 0.00s speech (0.0% of audio)\nNo speech detected, skipping transcription.\n'
    check(vk.parse_voxtype(silent) == '', 'voxtype: no speech gives an empty transcript')


def test_sample_lines():
    lines = [(str(i), 'one two three four five six seven eight nine ten') for i in range(10)]
    picked = vv.sample_lines(lines, 10, 150)
    check(len(picked) == 3, f'--sample: picks lines until about the asked seconds ({len(picked)} of 10 lines for 10 s)')


# ---------- voice_check on made clips ----------

def test_clean():
    d, path = build('clean')
    p, notes, summary = problems_of(path)
    check(p == [], f'clean clips: no problems ({p[:3]})')
    check(has(notes, 'skipped by request'), 'clean clips: --asr none says the round trip was skipped by request')
    check(130 <= summary['pace'] <= 165, f'clean clips: pace in range ({summary["pace"]} wpm)')
    r = subprocess.run([sys.executable, str(SCRIPTS / 'voice_check.py'), str(path), '--asr', 'none'], capture_output=True, text=True)
    check(r.returncode == 0 and r.stdout.strip().endswith('READY.'), 'clean clips: the command prints READY and exits 0')


def test_pace_counts_spoken_words():
    lines = ['Step 2: p squared is 0.4225, 2 p q is 0.455, and q squared is 0.1225.',
             'Multiply 0.7 times 0.7 to get 0.49, which is p squared.',
             'Carriers are 2 p q times 50,000, about 990 people in all.']
    lesson = copy.deepcopy(LESSON)
    beats = lesson['scenes'][0]['beats']
    beats[0]['say'], beats[1]['say'], beats[3]['say'] = lines
    d, path = build('numbers', lesson=lesson, lines=lines, secs=lambda x: len(vk.normalize(x)) * 60 / 150)
    p, notes, summary = problems_of(path)
    check(not has(p, 'words a minute'), f'pace: numbers count as the words spoken, so 150 spoken wpm passes ({p[:2]})')
    check(140 <= summary['pace'] <= 160, f'pace: the summary counts spoken words ({summary["pace"]} wpm)')

    d, path = build('slow', secs=lambda x: len(vk.normalize(x)) * 60 / 100)
    vj = json.loads((d / 'audio' / 'voice.json').read_text())
    vj['settings'] = {'speed': 0.7}
    (d / 'audio' / 'voice.json').write_text(json.dumps(vj))
    probs, _, summary = vk.check(path, asr='none')
    fixes = [f for w, pr, f in probs if 'words a minute' in pr]
    check(len(fixes) == 1 and '--speed 1.03' in fixes[0], f'pace: a slow voice gets one problem naming the speed to rerun with ({fixes})')


def test_stale_and_missing():
    d, path = build('stale', kinds={1: 'missing'}, extra_clips={'deadbeef': 'audio/deadbeef.mp3'})
    p, _, _ = problems_of(path)
    check(has(p, 'deadbeef') and has(p, 'gone or changed'), 'a clip for a sentence that changed is reported as stale')
    check(has(p, 'has no clip'), 'a line without a clip is reported')
    p2, notes, _ = problems_of(path, partial=True)
    check(not has(p2, 'has no clip') and has(notes, 'Partial check'), 'a sample run (--partial) does not count lines without clips')
    r = subprocess.run([sys.executable, str(SCRIPTS / 'voice_check.py'), str(path), '--asr', 'none'], capture_output=True, text=True)
    check(r.returncode == 1 and 'NOT READY: ' in r.stdout and 'Fix: ' in r.stdout, 'problems print with a Fix line and NOT READY, exit 1')


def test_loudness_clipping_dead_air():
    d, path = build('levels', kinds={0: 'quiet', 1: 'clipped', 2: 'dead'})
    p, _, _ = problems_of(path)
    check(has(p, 'LUFS; it should be -19 LUFS'), f'a clip 12 dB too quiet is reported ({[x for x in p if "LUFS" in x][:1]})')
    check(has(p, 'clips: samples reach'), 'a hard-clipped clip is reported')
    check(has(p, 'dBTP'), 'a clip over the true peak limit is reported')
    check(has(p, 'of silence inside it'), 'a clip with 2 s of dead air is reported')


def test_one_voice_and_disclose():
    other = vv.vc.fnv1a(LINES[2])
    d, path = build('mixed', voice_entries={other: {'file': f'{other}.mp3', 'tts_sha256': 'x', 'engine': 'browser', 'voice': 'af_bella'}},
                    disclose=False)
    p, _, _ = problems_of(path)
    check(has(p, 'mixes voices') and has(p, 'browser/af_bella'), 'voice.json with two voices is reported')
    check(has(p, 'disclose'), 'a missing AI voice disclosure is reported')


def test_no_asr():
    d, path = build('noasr')
    real_which, real_fw = vk.shutil.which, vk.faster_whisper_model
    asr_tools = {'whisper', 'whisper-cli', 'whisper-cpp', 'voxtype'}
    vk.shutil.which = lambda name, *a, **k: None if name in asr_tools else real_which(name, *a, **k)
    vk.faster_whisper_model = lambda download: None
    try:
        p, _, summary = problems_of(path, asr='auto')
    finally:
        vk.shutil.which, vk.faster_whisper_model = real_which, real_fw
    check(has(p, 'ASR round trip did not run: no Whisper found'), 'with no Whisper the round trip is a problem, so it cannot be READY')
    check(summary['wer'] is None, 'with no Whisper no word error rate is claimed')


FAKE_VOXTYPE = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
if os.environ.get('FAKE_ASR_FAIL'):
    print('ggml_vulkan: vk::Device::allocateMemory: ErrorOutOfDeviceMemory', file=sys.stderr)
    sys.exit(134)
heard = json.loads(os.environ['FAKE_ASR_MAP']).get(Path(sys.argv[-1]).stem, '')
print('Loading audio file: "x.wav"\\nAudio format: 16000 Hz, 1 channel(s), Int\\nProcessing 16000 samples (1.00s)...\\nVAD: 1.00s speech\\n')
print(heard)
'''


def with_fake_voxtype(path, heard, fail=False, **kw):
    bin_dir = WORK / 'fakebin'
    bin_dir.mkdir(exist_ok=True)
    exe = bin_dir / 'voxtype'
    exe.write_text(FAKE_VOXTYPE)
    exe.chmod(0o755)
    saved = {k: os.environ.get(k) for k in ('PATH', 'FAKE_ASR_MAP', 'FAKE_ASR_FAIL')}
    os.environ['PATH'] = f'{bin_dir}{os.pathsep}{saved["PATH"]}'
    os.environ['FAKE_ASR_MAP'] = json.dumps(heard)
    if fail:
        os.environ['FAKE_ASR_FAIL'] = '1'
    try:
        return problems_of(path, asr='voxtype', **kw)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_asr_round_trip():
    keys = [vv.vc.fnv1a(t) for t in LINES]
    d, path = build('asr-ok')
    p, notes, summary = with_fake_voxtype(path, dict(zip(keys, LINES)))
    check(p == [] and summary['wer'] == 0 and has(notes, 'word error rate 0.0%'), f'ASR round trip: a clip heard right passes ({p[:2]})')
    heard = dict(zip(keys, LINES))
    heard[keys[2]] = 'Raleigh scattering sends the short blue waves all over the sky.'
    p, _, summary = with_fake_voxtype(path, heard)
    check(has(p, 'the technical word "rayleigh" was heard as "raleigh"'), 'ASR round trip: a misheard term is its own problem')
    total = sum(len(vk.normalize(t)) for t in LINES)
    check(abs(summary['wer'] - 1 / total) < 1e-9, f'ASR round trip: one wrong word in {total} is a {summary["wer"]:.1%} word error rate')
    lesson = json.loads(path.read_text())
    lesson['pronounce'] = {'Rayleigh': 'RAY-lee'}
    path.write_text(json.dumps(lesson, indent=2) + '\n')
    p, _, _ = with_fake_voxtype(path, heard)
    fixes = [f for f in vk_fixes(path, heard)]
    check(any('Change the respelling of "Rayleigh" in "pronounce" (now "RAY-lee")' in f for f in fixes),
          'ASR round trip: a term already in "pronounce" gets "change its respelling"')
    p, notes, summary = with_fake_voxtype(path, {}, fail=True)
    check(has(p, 'could not be transcribed') and not has(p, 'word error rate 100%') and summary['wer'] is None,
          'ASR round trip: a crashed speech-to-text run is a failure, not a 100% word error rate')


def vk_fixes(path, heard):
    """The Fix lines voice_check gives with the fake voxtype hearing `heard`."""
    saved = os.environ.get('PATH')
    os.environ['PATH'] = f'{WORK / "fakebin"}{os.pathsep}{saved}'
    os.environ['FAKE_ASR_MAP'] = json.dumps(heard)
    try:
        return [fix for _, _, fix in vk.check(path, asr='voxtype')[0]]
    finally:
        os.environ['PATH'] = saved
        os.environ.pop('FAKE_ASR_MAP', None)


# ---------- video_voice with fake engines ----------

def fake_cmd(name, body):
    script = WORK / name
    script.write_text(body)
    return script


def test_engine_cmd_and_cache():
    fake = fake_cmd('fake_tts.py', FAKE_TTS)
    log = WORK / 'calls.log'
    d, path = lesson_dir('cmd')
    template = f'{sys.executable} {fake} {{text_file}} {{out}} {log}'
    rc, out = voice(path, '--cmd', template, '--asr', 'none')
    check(rc == 0 and 'Engine: cmd' in out, f'auto picks a working --cmd first and voice_check passes (exit {rc}){"" if rc == 0 else out[-600:]}')
    lesson = json.loads(path.read_text())
    keys = [vv.vc.fnv1a(t) for t in LINES]
    check(list(lesson['audio']['clips']) == keys and all((d / v).is_file() for v in lesson['audio']['clips'].values()),
          'every narration line gets audio/<fnv1a of its caption>.mp3 in "audio.clips"')
    check(lesson['audio']['voice']['disclose'].startswith('Narration is an AI voice:'), 'the lesson gets the AI voice disclosure')
    check(list(lesson)[:3] == ['format', 'title', 'wpm'], 'the lesson keeps its key order')
    vj = json.loads((d / 'audio' / 'voice.json').read_text())
    check(vj['engine'] == 'cmd' and set(vj['clips']) == set(keys) and all(len(e['tts_sha256']) == 64 for e in vj['clips'].values()),
          'voice.json records the engine, voice and a hash for each clip')
    check(len(log.read_text().splitlines()) == 3, 'first run: 3 clips made')

    log.write_text('')
    rc, out = voice(path, '--cmd', template, '--no-check')
    check(rc == 0 and log.read_text() == '', 'second run: every clip is cached, nothing is made')

    lesson = json.loads(path.read_text())
    lesson['pronounce'] = {'Rayleigh': 'RAY-lee'}
    path.write_text(json.dumps(lesson, indent=2) + '\n')
    rc, out = voice(path, '--cmd', template, '--no-check')
    made = log.read_text().splitlines()
    check(made == ['RAY-lee scattering sends the short blue waves all over the sky.'],
          f'a pronounce change remakes only that line, and the engine reads the respelling ({made})')
    check(json.loads(path.read_text())['scenes'][0]['beats'][3]['say'] == LINES[2], 'the caption keeps the real spelling')

    log.write_text('')
    rc, out = voice(path, '--cmd', template, '--voice', 'other', '--no-check')
    check(len(log.read_text().splitlines()) == 3, 'a different voice remakes every clip')

    lesson = json.loads(path.read_text())
    lesson['scenes'][0]['beats'][0]['say'] = 'Look up on a clear day and the sky is blue.'
    path.write_text(json.dumps(lesson, indent=2) + '\n')
    log.write_text('')
    rc, out = voice(path, '--cmd', template, '--voice', 'other', '--no-check')
    lesson = json.loads(path.read_text())
    old = vv.vc.fnv1a(LINES[0])
    check(len(log.read_text().splitlines()) == 1 and old not in lesson['audio']['clips'] and not (d / 'audio' / f'{old}.mp3').exists(),
          'a changed sentence gets a new clip and its old clip is removed')

    rc, out = voice(path, '--cmd', template, '--voice', 'other', '--no-check', '--sample', '3')
    check(rc == 0 and (d / 'audio' / 'sample.mp3').is_file(), '--sample writes audio/sample.mp3')


class Speech(http.server.BaseHTTPRequestHandler):
    wav = b''
    bodies = []

    def do_POST(self):
        Speech.bodies.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
        self.send_response(200 if self.path == '/v1/audio/speech' else 404)
        self.send_header('Content-Type', 'audio/wav')
        self.end_headers()
        self.wfile.write(Speech.wav)

    def log_message(self, *args):
        pass


def test_busy_gpu_falls_through():
    wav = WORK / 'speech.wav'
    ffmpeg('-f', 'lavfi', '-i', 'sine=f=300:d=3:sample_rate=24000', str(wav))
    Speech.wav = wav.read_bytes()
    server = http.server.HTTPServer(('127.0.0.1', 0), Speech)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        busy = fake_cmd('busy_tts.py', BUSY_TTS)
        d, path = lesson_dir('busy')
        env = env_clean(MYELINATE_TTS_CMD=f'{sys.executable} {busy} {{text_file}} {{out}}',
                        MYELINATE_TTS_URL=f'http://127.0.0.1:{server.server_port}')
        rc, out = voice(path, '--no-check', '--voice', 'af_heart', env=env)
        check(rc == 0 and 'Skipped cmd: the command refused, saying: Refusing to start: GPU is in use by process 4242.' in out,
              'a command that says the GPU is in use is skipped, with its words quoted')
        check('Engine: endpoint' in out and json.loads(path.read_text())['audio']['voice']['engine'] == 'endpoint',
              'auto falls through to the next tier (the endpoint)')
        check(Speech.bodies and Speech.bodies[0].get('response_format') == 'wav' and Speech.bodies[0].get('voice') == 'af_heart',
              'the endpoint gets an OpenAI-style request for WAV')
        d, path = lesson_dir('busy-forced')
        before = path.read_bytes()
        rc, out = voice(path, '--engine', 'cmd', '--no-check', env=env)
        check(rc == 3 and path.read_bytes() == before, 'a forced engine that refuses exits 3 and leaves the lesson unchanged')
    finally:
        server.shutdown()


def test_engine_none():
    d, path = lesson_dir('none')
    before = path.read_bytes()
    rc, out = voice(path, '--engine', 'none')
    check(rc == 0 and path.read_bytes() == before and 'robotic fallback' in out and not any((d / 'audio').iterdir()),
          '--engine none exits 0, makes nothing and leaves the lesson unchanged')
    rc, out = voice(WORK / 'nope.json')
    check(rc == 2, 'a missing lesson file exits 2')


def main():
    if not (shutil.which('ffmpeg') and shutil.which('ffprobe')):
        print('FAIL: these tests need ffmpeg and ffprobe')
        return 1
    tests = [test_pronounce, test_numbers_and_wer, test_voxtype_parse, test_sample_lines, test_clean, test_pace_counts_spoken_words, test_stale_and_missing,
             test_loudness_clipping_dead_air, test_one_voice_and_disclose, test_no_asr, test_asr_round_trip, test_engine_cmd_and_cache,
             test_busy_gpu_falls_through, test_engine_none]
    for t in tests:
        try:
            t()
        except Exception:
            traceback.print_exc()
            failures.append(t.__name__ + ' raised')
            print('FAIL:', t.__name__, 'raised')
    shutil.rmtree(WORK, ignore_errors=True)
    if failures:
        print(f'\n{len(failures)} failure(s):')
        for f in failures:
            print(' -', f)
        return 1
    print('\nAll voice tests passed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
