#!/usr/bin/env python3
"""Export a built Myelinate video lesson to an MP4 file, then check it and write a contact sheet.

usage:
    python3 scripts/video_export.py video.html video.mp4 [--fps 30] [--width 1280] [--height 720]
                                    [--sheet sheet.png] [--seconds N]

video.html is a lesson player built by `python3 scripts/video_check.py lesson.json --build video.html`.
The player is opened with ?export=1, where window.__video.renderAt(t) draws the exact frame for time t.
Each frame is screenshotted and streamed to ffmpeg, so memory stays flat however long the lesson is.

Narration: when the lesson has "audio": {"clips": {key: src}}, each clip is placed at the start of its
sentence and mixed into an AAC track. src is relative to video.html. Without clips the video is silent.

Needs: ffmpeg and ffprobe, plus a Playwright browser driver (Python `playwright`, or Node with
`playwright` or `playwright-core` on its module path, NODE_PATH included). This script never installs anything.

Exit codes: 0 every check passed; 1 a check failed; 2 bad arguments or input; 3 a tool is missing.
"""
import argparse
import base64
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

NOT_INSTALLED = 'This script never installs anything.'

# Node driver. Talks to Python on stdout with messages: 1 type byte ('J' JSON or 'F' PNG frame),
# a 4 byte big-endian length, then the payload. It waits on 'drain' so frames never pile up in memory.
NODE_DRIVER = r"""
const {chromium} = require(process.env.VX_MODULE);
const a = JSON.parse(process.env.VX_ARGS);
const out = process.stdout;
function send(type, payload) {
  const body = Buffer.isBuffer(payload) ? payload : Buffer.from(JSON.stringify(payload));
  const head = Buffer.alloc(5); head.write(type, 0, 'ascii'); head.writeUInt32BE(body.length, 1);
  return out.write(Buffer.concat([head, body])) ? Promise.resolve() : new Promise(r => out.once('drain', r));
}
(async () => {
  let browser;
  try { browser = await chromium.launch(); }
  catch (e) { await send('J', {type: 'error', stage: 'launch', message: String(e && e.message || e)}); process.exit(0); }
  const errors = [];
  try {
    const ctx = await browser.newContext({viewport: {width: a.width, height: a.height}, deviceScaleFactor: 1, colorScheme: 'light'});
    const page = await ctx.newPage();
    page.on('pageerror', e => errors.push(String(e)));
    await page.goto(a.url, {waitUntil: 'load'});
    try { await page.waitForLoadState('networkidle', {timeout: 8000}); } catch (e) {}
    try { await page.waitForFunction(() => window.__video && window.__video.duration > 0, null, {timeout: 15000}); }
    catch (e) { await send('J', {type: 'error', stage: 'page', message: 'window.__video never reported a duration. Is this a player built with video_check.py --build?', errors}); await browser.close(); return; }
    const info = await page.evaluate(async () => {
      try { await document.fonts.ready; } catch (e) {}
      // The player fits the first board before web fonts arrive; a resize makes it fit again with the real fonts.
      window.dispatchEvent(new Event('resize'));
      const v = window.__video, l = v.lesson || {};
      return {exportMode: document.body.classList.contains('export'), duration: v.duration, timeline: v.timeline(), audio: l.audio || null, title: l.title || ''};
    });
    if (!info.exportMode) { await send('J', {type: 'error', stage: 'page', message: 'The page did not enter export mode (?export=1).', errors}); await browser.close(); return; }
    const span = a.seconds > 0 ? Math.min(a.seconds, info.duration) : info.duration;
    const last = Math.ceil(span * a.fps - 1e-9);
    await send('J', Object.assign({type: 'header', frames: last + 1, span}, info));
    for (let i = 0; i <= last; i++) {
      await page.evaluate(t => window.__video.renderAt(t), i / a.fps);
      const png = await page.screenshot({type: 'png', animations: 'disabled', caret: 'hide'});
      await send('F', png);
    }
    await send('J', {type: 'done', errors});
  } catch (e) {
    await send('J', {type: 'error', stage: 'render', message: String(e && e.message || e), errors});
  }
  await browser.close();
})();
"""


class Fail(Exception):
    """A named check failed."""


def say(msg):
    print(msg, flush=True)


def warn(msg):
    print('warning: ' + msg, file=sys.stderr, flush=True)


# ---------- Tools ----------

def node_module():
    """Return 'playwright-core' or 'playwright' if Node can load it here (NODE_PATH included), else None."""
    node = shutil.which('node')
    if not node:
        return None
    for mod in ('playwright-core', 'playwright'):
        try:
            r = subprocess.run([node, '-e', f'require.resolve({json.dumps(mod)})'], capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if r.returncode == 0:
            return mod
    return None


def python_playwright():
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except Exception:
        return False


def find_tools():
    """Pick a driver and confirm ffmpeg and ffprobe. Exit 3 with one plain message when something is missing."""
    missing = [t for t in ('ffmpeg', 'ffprobe') if not shutil.which(t)]
    driver = None
    if python_playwright():
        driver = ('python', None)
    else:
        mod = node_module()
        if mod:
            driver = ('node', mod)
    if driver is None:
        missing.append('a Playwright browser driver (Python playwright, or Node with playwright or playwright-core on NODE_PATH)')
    if not missing and b'libx264' not in subprocess.run(['ffmpeg', '-hide_banner', '-encoders'], capture_output=True).stdout:
        missing.append('an ffmpeg build with the libx264 encoder')
    if missing:
        say('Cannot export: missing ' + ' and '.join(missing) + '. ' + NOT_INSTALLED)
        sys.exit(3)
    return driver


# ---------- Frame sources ----------

def node_frames(url, a, mod, log):
    env = dict(os.environ, VX_MODULE=mod, VX_ARGS=json.dumps({'url': url, 'width': a.width, 'height': a.height, 'fps': a.fps, 'seconds': a.seconds or 0}))
    proc = subprocess.Popen([shutil.which('node'), '-e', NODE_DRIVER], stdout=subprocess.PIPE, stderr=log, env=env)

    def exact(n):
        buf = b''
        while len(buf) < n:
            chunk = proc.stdout.read(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    try:
        while True:
            head = exact(5)
            if head is None:
                break
            kind, n = head[:1], struct.unpack('>I', head[1:])[0]
            body = exact(n)
            if body is None:
                break
            yield ('F', body) if kind == b'F' else ('J', json.loads(body))
    finally:
        proc.stdout.close()
        proc.wait()


def python_frames(url, a, log):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            yield ('J', {'type': 'error', 'stage': 'launch', 'message': str(e)})
            return
        errors = []
        try:
            ctx = browser.new_context(viewport={'width': a.width, 'height': a.height}, device_scale_factor=1, color_scheme='light')
            page = ctx.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(url, wait_until='load')
            try:
                page.wait_for_load_state('networkidle', timeout=8000)
            except Exception:
                pass
            try:
                page.wait_for_function('() => window.__video && window.__video.duration > 0', timeout=15000)
            except Exception:
                yield ('J', {'type': 'error', 'stage': 'page', 'message': 'window.__video never reported a duration. Is this a player built with video_check.py --build?', 'errors': errors})
                return
            info = page.evaluate("""async () => {
              try { await document.fonts.ready; } catch (e) {}
              window.dispatchEvent(new Event('resize'));
              const v = window.__video, l = v.lesson || {};
              return {exportMode: document.body.classList.contains('export'), duration: v.duration, timeline: v.timeline(), audio: l.audio || null, title: l.title || ''};
            }""")
            if not info['exportMode']:
                yield ('J', {'type': 'error', 'stage': 'page', 'message': 'The page did not enter export mode (?export=1).', 'errors': errors})
                return
            span = min(a.seconds, info['duration']) if a.seconds else info['duration']
            last = math.ceil(span * a.fps - 1e-9)
            yield ('J', dict(info, type='header', frames=last + 1, span=span))
            for i in range(last + 1):
                page.evaluate('t => window.__video.renderAt(t)', i / a.fps)
                yield ('F', page.screenshot(type='png', animations='disabled', caret='hide'))
            yield ('J', {'type': 'done', 'errors': errors})
        except Exception as e:
            yield ('J', {'type': 'error', 'stage': 'render', 'message': str(e), 'errors': errors})
        finally:
            browser.close()


# ---------- Audio ----------

def resolve_clip(src, html, tmp, key):
    """Return a local path for a clip src, or raise Fail."""
    if src.startswith('data:'):
        head, _, data = src.partition(',')
        if ';base64' not in head:
            raise Fail(f'audio clip {key}: only base64 data: URLs are supported')
        path = Path(tmp) / f'clip-{key}'
        path.write_bytes(base64.b64decode(data))
        return path
    if src.startswith(('http://', 'https://')):
        raise Fail(f'audio clip {key}: {src} is remote; download it next to the HTML file and use a relative path')
    if src.startswith('file://'):
        path = Path(urllib.parse.unquote(urllib.parse.urlparse(src).path))
    else:
        path = Path(urllib.parse.unquote(src.split('?')[0].split('#')[0]))
        if not path.is_absolute():
            path = html.parent / path
    if not path.is_file():
        raise Fail(f'audio clip {key}: file not found at {path}')
    return path


def probe(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,width,height:format=duration', '-of', 'json', str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        raise Fail(f'ffprobe could not read {path}: {r.stderr.strip()[:300]}')
    return json.loads(r.stdout)


def plan_audio(header, html, tmp):
    """Match clips to say items. Returns a list of (start seconds, path)."""
    audio = header.get('audio') or {}
    clips = audio.get('clips') if isinstance(audio, dict) else None
    if not isinstance(clips, dict) or not clips:
        return []
    says = {}
    for it in header['timeline']:
        if it['kind'] == 'say' and it.get('key'):
            says.setdefault(it['key'], it)
    plan = []
    for key, src in clips.items():
        it = says.get(key)
        if not it:
            warn(f'audio clip {key} matches no sentence in the lesson; skipped')
            continue
        if it['start'] >= header['span']:
            continue
        path = resolve_clip(str(src), html, tmp, key)
        dur = float((probe(path).get('format') or {}).get('duration') or 0)
        if dur > it['dur'] + 0.05:
            warn(f'audio clip {key} runs {dur - it["dur"]:.1f} s past its sentence and will overlap the next one')
        plan.append((it['start'], path))
    plan.sort()
    return plan


def mux_audio(video, plan, total, out, log):
    cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', str(video)]
    for _, path in plan:
        cmd += ['-i', str(path)]
    parts = [f'[{i + 1}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={round(start * 1000)}:all=1[a{i}]' for i, (start, _) in enumerate(plan)]
    labels = ''.join(f'[a{i}]' for i in range(len(plan)))
    mix = f'{labels}amix=inputs={len(plan)}:normalize=0:duration=longest' if len(plan) > 1 else f'{labels}anull'
    parts.append(f'{mix},apad=whole_dur={total:.3f},atrim=end={total:.3f}[aout]')
    cmd += ['-filter_complex', ';'.join(parts), '-map', '0:v', '-map', '[aout]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', str(out)]
    r = subprocess.run(cmd, stderr=log)
    if r.returncode != 0:
        raise Fail('audio mux: ffmpeg failed (see the log above)')


# ---------- Contact sheet ----------

def sheet_times(header):
    """First, each chapter midpoint, each pause question, each end card, last. Returns sorted times."""
    span, tl = header['span'], header['timeline']
    times = [0.0]
    scenes = {}
    for it in tl:
        if it.get('scene') is not None:
            s = scenes.setdefault(it['scene'], [it['start'], it['start'] + it['dur']])
            s[0] = min(s[0], it['start'])
            s[1] = max(s[1], it['start'] + it['dur'])
    times += [(a + b) / 2 for a, b in scenes.values()]
    # A pause card shows its question for 5 s, then the answer; take the question at 2.5 s and the answer at 7 s.
    for it in tl:
        if it['kind'] == 'pause':
            times += [it['start'] + 2.5, it['start'] + min(7, it['dur'] - 0.5)]
        elif it['kind'] == 'end':
            times.append(it['start'] + it['dur'] - 0.5)
    times.append(span)
    return sorted({round(t, 3) for t in times if 0 <= t <= span})


def write_sheet(video, header, fps, frames, sheet, log):
    idx = sorted({min(frames - 1, max(0, round(t * fps))) for t in sheet_times(header)})
    cols = min(4, len(idx))
    rows = math.ceil(len(idx) / cols)
    pick = '+'.join(f'eq(n\\,{i})' for i in idx)
    vf = f"select='{pick}',scale=480:-2,tile={cols}x{rows}:padding=6:margin=6:color=0x202020"
    r = subprocess.run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', str(video), '-vf', vf, '-fps_mode', 'passthrough', '-frames:v', '1', str(sheet)], stderr=log)
    if r.returncode != 0 or not Path(sheet).is_file():
        raise Fail('contact sheet: ffmpeg could not write it')
    return len(idx)


# ---------- Main ----------

def tail(path, n=15):
    try:
        lines = Path(path).read_text(errors='replace').splitlines()
    except OSError:
        return ''
    return '\n'.join(lines[-n:])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('html', help='a player built with video_check.py --build')
    ap.add_argument('mp4', help='the MP4 file to write')
    ap.add_argument('--fps', type=int, default=30)
    ap.add_argument('--width', type=int, default=1280)
    ap.add_argument('--height', type=int, default=720)
    ap.add_argument('--sheet', help='contact sheet PNG (default: NAME-sheet.png next to the MP4)')
    ap.add_argument('--seconds', type=float, help='render only the first N seconds (for tests)')
    a = ap.parse_args(argv)

    html = Path(a.html).resolve()
    out = Path(a.mp4).resolve()
    sheet = Path(a.sheet).resolve() if a.sheet else out.with_name(out.stem + '-sheet.png')
    if not html.is_file():
        say(f'Cannot export: {html} does not exist.')
        return 2
    if a.fps < 1 or a.fps > 120:
        say('Cannot export: --fps must be between 1 and 120.')
        return 2
    if a.width < 64 or a.height < 64 or a.width % 2 or a.height % 2:
        say('Cannot export: --width and --height must be even numbers of at least 64 (H.264 with yuv420p needs even sizes).')
        return 2
    if a.seconds is not None and a.seconds <= 0:
        say('Cannot export: --seconds must be more than 0.')
        return 2
    kind, mod = find_tools()
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.parent.mkdir(parents=True, exist_ok=True)
    url = html.as_uri() + '?export=1'

    with tempfile.TemporaryDirectory(prefix='video-export-') as tmp:
        logpath = Path(tmp) / 'tools.log'
        with open(logpath, 'w') as log:
            try:
                return run(a, html, out, sheet, url, kind, mod, tmp, log)
            except Fail as e:
                log.flush()
                t = tail(logpath)
                say(f'FAILED: {e}' + (f'\n--- tool log ---\n{t}' if t else ''))
                return 1


def run(a, html, out, sheet, url, kind, mod, tmp, log):
    source = node_frames(url, a, mod, log) if kind == 'node' else python_frames(url, a, log)
    driver = f'Node {mod}' if kind == 'node' else 'Python playwright'
    try:
        return export(a, html, out, sheet, source, driver, tmp, log)
    finally:
        source.close()


def export(a, html, out, sheet, source, driver, tmp, log):
    header = None
    for typ, msg in source:
        if typ == 'J':
            header = msg
            break
    if header is None:
        raise Fail(f'browser: the {driver} driver exited before it sent anything')
    if header['type'] == 'error':
        if header.get('stage') == 'launch' and "Executable doesn't exist" in header['message']:
            say(f'Cannot export: {driver} is present but its Chromium browser is missing. {NOT_INSTALLED}')
            sys.exit(3)
        raise Fail(f"browser ({header['stage']}): {header['message'][:500]}")

    duration, frames, span = header['duration'], header['frames'], header['span']
    plan = plan_audio(header, html, tmp)
    say(f'Rendering "{header.get("title", "")}": {span:.1f} s of {duration:.1f} s, {frames} frames at {a.fps} fps, {a.width}x{a.height}, driver {driver}.')

    video = Path(tmp) / 'video.mp4' if plan else out
    enc = subprocess.Popen(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', str(a.fps), '-c:v', 'png', '-i', '-',
                            '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p', '-r', str(a.fps), '-movflags', '+faststart', str(video)],
                           stdin=subprocess.PIPE, stderr=log)
    sent, end = 0, None
    try:
        for typ, msg in source:
            if typ == 'F':
                enc.stdin.write(msg)
                sent += 1
                if sent % (a.fps * 10) == 0:
                    say(f'  {sent}/{frames} frames')
            else:
                end = msg
                break
    except BrokenPipeError:
        raise Fail('encode: ffmpeg stopped reading frames')
    finally:
        try:
            enc.stdin.close()
        except BrokenPipeError:
            pass
        enc.wait()
    if end is None or end.get('type') == 'error':
        raise Fail(f"browser (render): {(end or {}).get('message', 'the driver stopped early')[:500]}")
    if enc.returncode != 0:
        raise Fail('encode: ffmpeg exited with an error')
    if sent != frames:
        raise Fail(f'frame count: rendered {sent} of {frames} frames')
    page_errors = end.get('errors') or []
    for e in page_errors:
        warn('page error: ' + e[:300])

    total = frames / a.fps
    if plan:
        mux_audio(video, plan, total, out, log)
    else:
        say('silent: captions only; add narration clips for a voice')

    # Checks on the file itself.
    info = probe(out)
    streams = info.get('streams') or []
    vids = [s for s in streams if s.get('codec_type') == 'video']
    auds = [s for s in streams if s.get('codec_type') == 'audio']
    got = float((info.get('format') or {}).get('duration') or 0)
    failed = []
    if not vids:
        failed.append('video stream: none in the file')
    elif (vids[0].get('width'), vids[0].get('height')) != (a.width, a.height):
        failed.append(f"dimensions: {vids[0].get('width')}x{vids[0].get('height')}, expected {a.width}x{a.height}")
    if abs(got - span) > 0.5 + 1 / a.fps:
        failed.append(f'duration: {got:.2f} s, expected {span:.2f} s')
    if plan and not auds:
        failed.append('audio stream: clips were given but the file has no audio')
    if page_errors:
        failed.append(f'page errors: {len(page_errors)} JavaScript error(s) while rendering')
    if failed:
        raise Fail('; '.join(failed))

    tiles = write_sheet(out, header, a.fps, frames, sheet, log)
    size = out.stat().st_size / 1e6
    say(f'OK. {out}')
    say(f'  duration {got:.2f} s (timeline {span:.2f} s), {frames} frames, {size:.2f} MB, audio {"yes, " + str(len(plan)) + " clips" if plan else "no"}')
    say(f'  sheet {sheet} ({tiles} frames)')
    say('Look at the sheet before you send this video.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
