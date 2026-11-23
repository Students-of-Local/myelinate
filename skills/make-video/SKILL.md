---
name: make-video
description: "Use when asked to make a teaching video, animated lesson or explainer to learn a topic, or to turn slides into one. Finding one: find-media. Not app demos, intros or edits."
---

# Make video

A teaching video a learner watches, pauses and answers. You do not draw or animate anything. You write one lesson file. A fixed player turns it into a narrated, animated video with captions, chapters, sources and questions that wait for an answer. A checker finds every problem in the file and tells you how to fix it.

Paths like `templates/…` and `scripts/…` are relative to this skill's folder, which carries its own copy of every file it names. Other Myelinate skills are siblings (`../find-media/SKILL.md`). If a file is missing from your copy, follow this file: it is enough on its own.

**Stand down when it isn't wanted.** A demo of an app, a vlog edit, a YouTube intro or a trailer is not this skill. To find an existing video, use `find-media`. To learn from a video they already have, use `video`.

Evidence and limits: the design follows multimedia learning research (Mayer, *Multimedia Learning*, 3rd ed., 2020): names before process, narration with few words on screen, short segments, worked then faded examples, and questions during the video (`references/evidence.md`). No study has tested this player. Never say it raises grades.

## 0. Never

1. **Never invent** a quote, a source, a page number, a web address or a date.
2. **Never narrate a fact that is not in `claims`.** Every fact sentence cites a claim id.
3. **Never say "verified", "checked" or "tested" unless that step ran.** Use these words exactly: *prepared* (written, not checked), *checked* (step 6 ran), *tested* (you opened the video and played it).
4. **Never deliver while the checker shows a problem.**
5. **Never for graded work.** A video that solves their homework or a take-home question does the work for them. Use `assignment` for that, and make the video about a parallel problem instead.

## 1. Ask once, then start

Send **one** message. Don't wait for the answer to start drafting.

**For a class**, ask for everything at once:

> To make this match your class, send whatever you have: your notes, the study guide, the slides, the syllabus, the textbook and its edition, past quizzes or exams, what the exam looks like (multiple choice, problems, essays), and any symbols your professor uses. And: what part confuses you most?

**For self-study**, ask: "What do you want to be able to do with this, and how much do you already know?"

If they have nothing, or don't answer, build it anyway from reliable sources (a textbook, a university, a government agency, a journal). Set `"checked": "not-yet"`. The video then says **"Draft: not yet checked against your course"**. When their materials arrive, redo step 3 against them.

If `debrief` or the learner named a question they missed, put it in `learner.target` and make that miss the video's misconception.

## 2. Choose the scope

1. Write 1 to 3 objectives. Each starts with a verb: Explain, Solve, Compare, Predict.
2. Write the one question the video answers.
3. Choose `lessonType`: `"problem"` if the learner must solve problems with steps (math, chemistry calculations, physics); otherwise `"concept"`.
4. Keep it short: 2 to 6 minutes of narration is right. Split a bigger topic into several videos.

## 3. List the claims first

Before you write any narration, list every fact the video will state. For **each claim**, do exactly this:

1. Find the line in the source that says it.
2. Copy that line, letter for letter, into `"quote"`. Never fix its spelling and never shorten it in the middle.
3. Write where it is in `"where"`: the page, slide or section number for the learner's material (`"from": "course"`), or the full `https://` address for anything else (`"from": "outside"`, plus `"checked": "YYYY-MM-DD"`).
4. **If no line says it, delete the claim.** Or find a reliable outside source and mark it `"from": "outside"`. On screen it shows as *outside your course*.
5. If the course and a reliable source disagree, keep the course's version, set `"status": "conflict"` and write both in `"note"`. The narration says both: "Your slides say X. Most references say Y. Ask your professor which one the exam uses."
6. Leave `"status": "unchecked"`. Step 6 changes it.

Use the course's own words and symbols. If the professor writes ΔH, write ΔH.

## 4. Write the scenes

Copy `templates/video-lesson.json` and replace every `<<...>>`. The complete example `examples/video-lesson-sky.json` shows a finished lesson. Build the scenes in this order:

| Scene `role` | What it does |
| --- | --- |
| `intro` | A hook and the question. Show a `title`, then a `question`. |
| `names` | Each new word before the process: one `term` per word. |
| `explain` | The idea, one step per sentence. |
| `worked` | **Problem lessons:** solve one problem, one `step` per sentence. |
| `faded` | **Problem lessons:** a similar problem. Show the first steps, then a pause asks the learner for the next step. |
| `example` | **Concept lessons:** apply the idea to one concrete case. |
| `misconception` | Name the common mistake, then correct it. Use `compare`. |
| `summary` | The whole chain in 3 to 5 short `step`s. |

Each beat is **one** of these:

- `{"say": "One short sentence.", "claims": ["c3"], "show": [ ... ]}` for a fact.
- `{"say": "A question, an instruction or a transition.", "talk": true}` for words that state no fact. A sentence with a number is a fact.
- `{"pause": {"ask": "...", "choices": ["...", "..."], "answer": "...", "why": "...", "claims": ["c3"]}}` for a question. Leave out `choices` to have the learner type an answer.

Rules the checker enforces:

1. Sentences of 22 words or fewer. Never more than 30.
2. A pause question every 60 to 90 seconds of narration. Ask the learner to **predict** before you explain.
3. The screen shows key words, never the sentence being said. 40 words on screen per scene at most.
4. `wpm` from 130 to 160. Use 145.
5. A scene runs 6 minutes or less.
6. End with `recall` (look away and explain it) and `practice` (one new problem like the one taught).
7. Something appears on screen when the narration names it, in the same beat.

Things you can `show`:

| `type` | Fields | Use it for |
| --- | --- | --- |
| `title` | `text`, `sub` | The opening card |
| `question` | `text` | The question the video answers |
| `term` | `word`, `meaning` | A new word, before you use it |
| `label` | `text` | One key phrase |
| `equation` | `text`, `claims` | Typed math: `x^2`, `v_0`, `\Delta H`, `sqrt(x)`, `->` |
| `step` | `text` | One line of a worked solution or a chain; steps stack |
| `arrow` | `from`, `to`, `label` | Cause and effect, input and output |
| `compare` | `left`, `right`, `leftItems`, `rightItems` | Wrong idea and right idea; two cases |
| `graph` | `title`, `x`, `y`, `points`, `mark`, `claims` | Data. Compute every point; never guess one |
| `quote` | `text`, `claim` | A short exact quotation from a claim |
| `image` | `src`, `alt`, `credit`, `license`, `link` | A licensed figure that teaches; never decoration |
| `highlight` | `target` | Underline something already shown in this scene |

## 5. Run the checker, fix, repeat

<!-- local-tools -->
With a shell:

```sh
python3 scripts/video_check.py lesson.json
python3 scripts/video_check.py lesson.json --sources path/to/their/notes   # when you have their materials as text
```

It prints numbered problems, each with a **Fix:** line. Fix exactly what it says, in order, then run it again. Repeat until it prints `READY`. Never stop while it prints `NOT READY`. Give `--sources` the learner's materials as text files: it then confirms every course quote really appears in them.
<!-- /local-tools -->

With no shell, check the file yourself against the rules in step 4, one rule at a time, and say the checker did not run.

## 6. A second reader checks the claims

The writer of a claim is the worst judge of it. Before you deliver:

1. Give each claim's `text`, `quote` and `where`, plus any `pause` answers and the `practice` answer, to a second reader: the `key-worker` agent if you have it, or the `verify` skill. Give it the problems without your answers, so it works them itself.
2. For each claim it confirms that the quote is in the source and says the claim, set `"status": "matched"`.
3. For a claim it can't confirm, delete the claim and its sentences, or mark it `conflict` with a note.
4. Set `"verifiedBy"` to who checked and when. Then run the checker with `--final`; it fails while any claim is `unchecked`.
5. For a class, set `learner.checked` to `"yes"` only when every course claim matched the learner's own materials.

With no second reader, leave the claims `unchecked`. The video then says how many claims no second reader checked. Say so in your reply too.

## 7. Build and deliver

<!-- local-tools -->
**With a shell:** `python3 scripts/video_check.py lesson.json --build video.html` writes the finished video (it refuses while there are problems). Open it, play the first minute, answer one pause question, and look at it at phone width. Then publish it where the learner can open it, or give them the file.
<!-- /local-tools -->

**With files but no shell:** copy `templates/video-player.html` and replace only the JSON between `<script type="application/json" id="lesson">` and `</script>`. Write every `<` inside the JSON as `\u003c`. Never edit the rest of the page.

**With no files at all** (this skill was pasted into a chat): give the lesson JSON in one code block, and tell the learner to paste it into the Myelinate video player page (listed in the Myelinate README). Under it, give the same lesson as a read-along script: each chapter title, each sentence, and each pause question with its answer below a line, so they can learn from it right away.

**Narration voice.** The player reads the narration aloud with the browser's voice by default, and shows captions either way. If the host can make speech audio, run `python3 scripts/video_check.py lesson.json --audio-plan`, make one clip per line, and add them as `"audio": {"clips": {"<clip name without .mp3>": "audio/<clip name>"}}`. The clip name comes from the sentence, so a changed sentence gets no stale clip; the checker reports clips that no longer match.

<!-- local-tools -->
**MP4.** When the learner wants a video file and the machine already has Playwright and ffmpeg (never install them for this): `python3 scripts/video_export.py video.html video.mp4`. It renders frame by frame, adds the clips if there are any, checks the file with ffprobe and writes a contact sheet of frames. Look at the contact sheet before you send it. The MP4 cannot wait for answers: it shows each pause question, holds it, then shows the answer.
<!-- /local-tools -->

## 8. Say exactly what state it is in

End your reply with one line:

- **prepared**: the file is written; the checker did not run, or no second reader checked the claims.
- **checked**: the checker printed READY with `--final`, and a second reader confirmed every claim.
- **tested**: you also opened the video and played it.

Then: what was checked against the learner's own materials and what was not.

## 9. A small complete example

This is the start of `examples/video-lesson-sky.json`: one claim, the opening scene and the names scene. The full file has 11 claims, 6 scenes, recall and practice.

```json
{
  "format": "myelinate-video/1",
  "title": "Why is the sky blue?",
  "subtitle": "And why sunsets turn red",
  "lessonType": "concept",
  "wpm": 145,
  "learner": {"kind": "self-study", "purpose": "Understand everyday light and color", "level": "Curious adult, no physics background", "materials": [], "checked": "not-a-course"},
  "objectives": ["Explain why air makes the daytime sky look blue", "Use the same idea to explain red sunsets"],
  "question": "If sunlight looks white, why is the sky blue?",
  "claims": [
    {"id": "c3", "text": "Blue light waves are shorter than red light waves.", "from": "outside",
     "source": "NASA Space Place, Why Is the Sky Blue?", "where": "https://spaceplace.nasa.gov/blue-sky/en/",
     "checked": "2026-11-22", "quote": "Blue light waves are shorter than red light waves.", "status": "matched"}
  ],
  "scenes": [
    {"id": "s1", "title": "The question", "role": "intro", "beats": [
      {"say": "Look up on a clear afternoon and the sky is blue.", "talk": true,
       "show": [{"type": "title", "text": "Why is the sky blue?", "sub": "And why sunsets turn red"}]},
      {"say": "So where does the blue come from?", "talk": true,
       "show": [{"type": "question", "text": "If sunlight looks white, why is the sky blue?"}]}
    ]},
    {"id": "s2", "title": "Three words first", "role": "names", "beats": [
      {"say": "Each color travels as a wave, and blue waves are shorter than red ones.", "claims": ["c3"],
       "show": [{"type": "term", "word": "Wavelength", "meaning": "Length of one wave. Blue short, red long."}]},
      {"pause": {"ask": "Which color has the shorter waves?", "choices": ["Red", "Blue"], "answer": "Blue",
                 "why": "Blue light waves are shorter than red light waves.", "claims": ["c3"]}}
    ]}
  ]
}
```

The screen shows *Wavelength* and a ten-word meaning while the voice says the full sentence. The pause asks before the next idea. The claim's quote is copied exactly from the page it names.
