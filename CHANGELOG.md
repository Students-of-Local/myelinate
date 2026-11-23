# Changelog

All notable changes to Myelinate are recorded here.

What was actually tested for each version, and its limits, is in [evals/verification.md](evals/verification.md). The behavioral checks are in [evals/scenarios.md](evals/scenarios.md).

## [Unreleased]

## [3.1.1] - 2026-11-22

Quotes in a vetting note are checked by code, not by the model that wrote them.

- **`yt.py quote URL --at m:ss "text"`** confirms the words were said within 20 seconds of the timestamp. It ignores case, punctuation, curly quotes, dashes and a copied `[8:01]` stamp. It keeps what changes meaning: numbers, signs (−30.5 is not 30.5), exponents (10⁵ is not 105), "not" (with "isn't" read as "is not"), and every word except "uh", "um" and the articles. A word that differs passes only as a plural or a one-letter typo inside a word of seven or more letters with the same first two and last three letters, and never as a vowel swap. So "subsituted" passes, while "alkane" for "alkene", "nitrite" for "nitrate" and "syn-periplanar" for "anti-periplanar" fail. The whole quote must be at least 0.90 similar. A quote is one unbroken stretch of at least four words, and a `...` cut is refused, because two true fragments can splice into a false claim. A real quote at the wrong time fails and says when it was said. A machine-translated track confirms nothing, and auto captions are labeled. On success, it prints the source's own words and a link to show the learner, so the label comes from the checker, never from the model's retyping. Exit 6 means not confirmed.
- **`yt.py course FILE "text"`** checks a course quote against any text file the same way (slides, notes, a pasted transcript), also undoing ligatures and words hyphenated across lines, and names the line. It needs no `yt-dlp`. A PDF is refused with the `pdftotext` command to run first.
- **`references/video-finder.md` and `video` require the check** before any vetting quote or contradiction flag is shown; each verdict cites the course quote and the video quote, and "Contradicts" needs both confirmed. When the checker can't run (any exit but 0 or 6), quotes are copied from the text read and labeled "Quotes not machine-checked."
- **A small-model run** (`evals/quote-check/run.py`, LFM3 1.7B through Ollama) plants eight attacks; the checker refused all eight and confirmed both real quotes, while the same model, asked to judge, answered "NO" to every quote, real ones included. Results in `evals/verification.md`.
- Offline tests cover a real quote at the wrong time, words changed at the right time (a swapped term, a dropped "not", an added number), an invented quote, a spliced cut, a dropped sign or exponent, a dropped meaning word, one-letter chemistry swaps, a machine-translated track, and altered or invented course quotes.

## [3.1.0] - 2026-11-22

Video learners get the few minutes that teach the concept, checked against their course.

- **A video finder.** `references/video-finder.md` is the method `find-media` and `video` follow: write the target, must-say terms and course claims from the learner's own material, search wide, find the segment, vet each course claim against the transcript (matches, other notation, beyond the course, contradicts, can't tell), then give one segment with a question to watch for, pause points, a recall prompt and a problem.
- **`scripts/yt.py`** drives a `yt-dlp` the learner already has (it never installs and never downloads video). `search`, `info`, `transcript`, `find` and `scan`. Captions come in two steps, one exact track per request, best first (manual, then the `-orig` auto track, then untranslated auto, then the video's own language, machine translation last), because YouTube answers translated and back-to-back caption requests with HTTP 429. `find` returns the segments where the course's terms are spoken, with links that start and stop there; `scan` ranks a search by coverage and caption quality and labels uncaptioned videos "cannot vet". Offline tests in `tests/yt_tool.py`. Left out of the Codex package: OpenAI's directory bars local tools that fetch from third-party sites.
- **Segments in the video view.** `templates/inline-widgets.html` takes `end` and a `segments` list; a segment stops once at its end and asks the question before moving on. Nothing loads from YouTube's player before play.
- **"I learn best from videos"** is taken as a preference: lead with one short vetted segment, then recall and a problem (`references/personalization.md`). `tutor`, `teach` and the router offer a vetted segment instead of "one or two verified videos".
- **Fixed: `/myelinate:video`, `/myelinate:debrief` and `/myelinate:progress` hid their skills in Claude Code.** A command named like a skill wins the name, so the skill never loaded and an assistant improvised (in one run, a raw `yt-dlp --sub-langs "en.*"`). The three commands are gone; the skills are the slash commands now, and `scripts/check.py` fails on any command named like a skill.

## [3.0.1] - 2026-11-22

Follow-ups from the 3.0.0 review (issue #31).

### Fixed
- **A graph with a tiny range no longer freezes the page.** The slider-graph view in `templates/inline-widgets.html` stepped its gridlines in a loop that could run for hundreds of millions of turns on a range like 0 to 1e-19 (photon energies in joules). Ticks now come from one bounded helper, at most 50 per axis. `tests/inline_journey.py` adds that case.
- **`debrief` tells "never learned" from "learned and lost".** A miss on an item the learner record shows as once unassisted-correct is now **Knew it, lost it**, a spacing problem, not a teaching one.
- **`rivals.py` reruns a pair when its inputs change.** Saved pairs carry a hash of the scenario, both skill texts, the judge and the model, and a changed rubric or skill reruns only the pairs it touches. Before, a resumed run reused stale verdicts.
- **`evals/triggers/run.py` no longer crashes** printing a summary for an `--only` subset with no negatives.

### Changed
- **`game` says what it isn't more plainly:** "Not making a game (Unity, Godot, code)." On "Help me build a platformer game in Unity for my portfolio", false fires fell from 4 of 5 passes to 0 of 5.
- **Trigger floors raised** to 98.7% hit and 11.2% false fire on the main set and 98.2% and 5.6% on the holdout, after the full eval measured 99.4% and 9.5%, and 100% and 0%.

## [3.0.0] - 2026-11-21

Built to learn anything, measured against the best learning plugins, and made ready for the Claude, ChatGPT and Grok directories.

### Added
- **`debrief`: a returned exam becomes one change.** Each missed item gets one cause (not studied, recognized but not recalled, recalled but not used, look-alikes, format, lost it, slip, time), checked with a cold retest. The causes are tied to the methods the learner used, and the reply ends with one scheduled change that `study-plan` puts in the first week. With the learner's OK, an `exams` ledger in the learner record tracks causes and whether the change was done, so a pattern is claimed only across three or more exams. Exam corrections for points stay graded work. `/myelinate:debrief`.
- **Making materials isn't studying.** Router rule 18: when a learner asks for a deck, a study site or formatted notes with an exam coming, make it fast, then turn the same session to retrieval from it. `debrief` counts hours making things apart from hours practicing.
- **Online homework screenshots are graded work.** Router rule 13 and `assignment`: a screenshot or paste from WileyPLUS, Mastering, ALEKS, Connect, Achieve or a Canvas or Blackboard quiz (an attempt counter, Submit, points, a score penalty) gets a parallel case and their own pick, never the option or which choices are wrong. A real learner's chat on claude.ai answered one outright.
- **When it doesn't land, change the form.** Router rule 19: after "that makes no sense", don't reword it. Work one set of numbers with signs shown, then a picture or a control, then one question. Signed-term comparisons (ΔG = ΔH − TΔS) get a two-row table at two settings.
- **Inline patterns for every host that can draw.** `templates/inline-widgets.html` holds tested practice, flashcard, step-through, slider-graph and video views for a host's own render tool, or to open as a page. The practice view holds no key. They work at phone width, in light and dark.
- **Learn anything.** Router rule 17 and `references/learn-anything.md`: skills done with the body, hands or senses get the whole small version, a drill and its dose, how to judge it alone, the gate to the next stage, and a result to report back. Safety comes first and plainly when it's real.
- **`video`**: learn from a video, lecture, playlist or transcript. Recall before any summary, timestamps on everything.
- **`progress`**: wrapping up, coming back after a gap, not being able to start, "how am I doing?", "am I ready?". `/myelinate:wrap`, `/myelinate:progress`, `/myelinate:video`.
- **`teacher`**: unit and lesson plans built backward from the outcome, rubrics with observable levels.
- `evals/head-to-head/rivals.py`: a blind head-to-head against six rival plugins and plain Claude, each on its home turf.

### Changed
- **"Give me the link" gets a link.** `find-media` searches for the URL itself, checks each video through YouTube's oEmbed, and gives a one-click YouTube search as the floor. It never tells a learner to go search, and never says it verified something it didn't check in this conversation. A real learner hit both of those failures.
- **Their material is the source.** Questions, cards and verdicts name the passage they came from, and anything added is marked *Outside your material:*. Flashcards default to a table plus an Anki-ready block with a source column.

### Fixed (directory policy)
- **Nothing is saved unless the learner asks.** `§1` no longer reads or writes host memory on its own initiative (Anthropic Software Directory Policy 1G).
- **No instructions from elsewhere.** Skills no longer fetch files from GitHub when a file is missing (policy 2F). Raw URLs live in `llms.txt` only.
- **Plain shell hook.** `hooks/session-start.sh` replaces two Python hooks, which would have held every version for a reviewer. `MYELINATE_HOME` and `MYELINATE_ROUTE_HINT` are gone: create `~/.myelinate/no-hint` to silence the note.

## [2.9.0] - 2026-11-02

### Added
- **`game`, a typed exam study game.** `templates/exam-game.html` is one offline engine: the agent fills in its JSON and nothing else. What must be memorized forms a gate: learn it, drill it from memory, then pass a perfect blank-page test before the rest opens. Stages interleave surprise recall of earlier items, a mock follows the exam's format with no feedback until the end, and a delayed recheck, set for the next morning by default, sends misses back to drilling and stays open until it's passed. Learners type formulas and see them render live, can enter a setup like `300*e^(0.2*6)`, and get new numbers on math items. Formulas are compared by value, so commuted forms pass and missing parentheses fail; unreadable input costs nothing. `gameAudit()` reports missing sources or units, formulas that can't be typed or don't match themselves, model answers that fail their own rubric, broken numbers, raw TeX, and objectives covered only by sort items. `tests/game_journey.py` plays the whole path offline. Never for graded work, since the page source holds every answer.
- Honest numbers by construction: the page shows items cleared, never readiness; the mock scores auto-marked items only and leaves short answers for the learner to compare; an answer the learner counts themselves is labeled as their own judgment.

### Changed
- **Scope comes from the source.** Router rule 10 and `tutor`: what to memorize is listed from the study guide itself, formatting that carries the rule (red for memorize, blue for provided) is read from a rendered page, totals are counted, and a study packet is saved as text after reading.
- **Formula tiers and units.** `flashcards` and rule 15 sort formulas into memorize, also know and provided, with units, and mark derived units.
- `study-plan`: for what must be memorized, the final 24 hours include an unaided check and a blank-page recheck the next morning.
- `references/production-lessons.md`: read formatting, keep what you read, and name what a number measures.

## [2.8.2] - 2026-11-02

### Fixed
Review findings on the flashcard deck (#23, #25):
- **A guess never drops a card.** Only `\f` or `\b`, which JSON makes only from a swallowed backslash, skips a card. A tab, carriage return or line break that looks like a swallowed one (`\theta`, `\rho`, `\nabla`, `\neg`), inside or outside math or between `$` signs, loads with a `deckAudit()` warning under `possibleLostBackslash`. 2.8.1 and the earlier 2.8.2 drafts skipped correct cards: display lines starting with `e^{rt}` or `u = v - at`, tab-indented lines pasted from a `.tex` file, classic-Mac line breaks, and shell cards with two `$` variables. They all load now.
- `deckAudit()` `rawTeX` reports TeX command names, an unknown command with braces (`\overline{x}`), scripts on a short symbol (`x^{2}`, `CO_{2}`, `KE_{max}`) and an opening delimiter followed by math. It ignores code: `\n`, `C:\Users`, `\d+`, `[^{}]`, `report_{year}`, `'{}_{}'.format`.
- `flashcards` states the rule and what each `deckAudit()` field means. `PRIVACY.md` says deck pages keep review dates in the browser's local storage.
- Known limits (#27): some swallowed backslashes get no warning (a lost `\rtimes` in display math), and a lost `\times` between `$` signs warns but the card shows the wrong math until it's fixed.

## [2.8.1] - 2026-11-01

### Fixed
Round-2 review findings on the flashcard deck (#21):
- **Forgetting counts.** Again on any card, due or not, resets it to relearning (interval 0, back in 10 minutes). Before, Again on a card practiced early kept its 30-day interval.
- **Review days are calendar days.** A study day runs from 4 a.m. to 4 a.m., as in Anki. A card rated Good is due from 4 a.m. on the day it comes up, so studying at the same time each morning no longer slips every rung of the ladder by a day, an 11:55 p.m. review doesn't come due again five minutes later, and "Due today" means today.
- The done screen says review dates were saved only when a due card was rated and saving worked; if saving fails it says the dates reset when the page closes; with no due card rated it says "Practice only: no review dates changed."
- `\$` in a cloze or in math shows a dollar sign. Study-guide text with Windows line endings or tabs loads instead of being skipped as a lost backslash; display math on its own lines loads; a lost backslash is caught by the engine's own command list, in display math (`\ne`, `\nabla`), after a tab (`\therefore`) and after a carriage return (`\rho`). Card ids like `constructor` work.
- Formulas: `\vec`, `\mathbf` (as Unicode bold, which Chromium shows), `\hbar`, primes, `\lim`, `\dot`, `\ddot`, `\tilde`, `\binom`, long arrows, `\iff` and `\implies` render; function names keep a visible space (`ln x`); `\text{ mL}` keeps its space. `flashcards` lists what renders and what to write instead (`\mathrm{H_2O}` for chemistry; matrices in Unicode or text).
- `deckAudit()` on a deck page lists every card's math errors and any TeX left outside math, or the fatal error when the deck doesn't load, so an agent without a screen can check a deck before delivering it.
- The template comment gives one escaping rule: every `<` in the JSON is `\u003c`.

## [2.8.0] - 2026-11-01

### Added
- **A study deck page with working formulas.** `templates/flashcards-deck.html` is the one engine for a flashcard deck a learner keeps: the agent fills in its JSON and nothing else. It works offline: answer before the reveal, again/hard/good/easy with misses requeued, three correct recalls in the first session, a saved 1 → 3 → 7 → 14 → 30 day ladder, a tag filter, a print-ready browse list, and Quizlet and Anki exports. Formulas are written in TeX and render as native MathML with no network; the Quizlet export turns them into Unicode (p² + 2pq + q² = 1) and the Anki export keeps `\( \)` for Anki's own renderer. An unsupported command shows boxed as source instead of breaking the card. Decks made before this were hand-built each time and showed raw TeX. `tests/flashcards_journey.py` covers the study loop, persistence, exports, no network requests, escaping, and formula rendering at desktop and phone widths.
- `flashcards`: a formula rule for every export format, and an exam-deck rule: when the exam supplies an equation sheet, card what each term means and when the formula applies, not the formula. The pre-send checklist in the router and `flashcards` now includes "every formula renders as math".

### Changed
- **Asks for less up front.** For a course, the router and `tutor` ask in one line for the two things that decide the most, the study guide and the exam date and format, and ask for the rest (syllabus, slides, textbook edition, past exams, equation sheet) one at a time when the work needs it, instead of a seven-item list. The course intake template records whether an equation sheet is provided.

### Fixed
- **Ready for Anthropic's directory without a reviewer hold.** The directory holds any version that ships a PDF or a non-image file of 256 KiB or more. The 656 KiB `examples/practice-test-oxygen.pdf` (and its copy) is gone from the plugin; the router names its HTML source, and the PDF is attached to the release. `check.py` fails on more than 512 files, a binary that isn't an image or font, a system file, or a non-image file of 256 KiB or more.

## [2.7.0] - 2026-11-01

### Changed
- **One screen, one idea.** A teaching reply fits on about one phone screen: the inline visual or practice widget leads when the idea has shape, then about 250 words of prose (about 400 for a "just lay it out" overview), bold only where a term is defined, no stacked bold headings, extras or recap. "Teach me all I need to know for these" gets the map of the few ideas and the first one taught well. Router §4, `tutor` Explain mode. In a blind A/B (Sonnet replies, Opus judge), the new text won 11 of 12 pairs and cut prelab replies from about 825 to about 310 words; results in `evals/verification.md`.
- **Course work counts as graded.** Prelab questions, lab-report calculations, worksheets and problem sets are graded unless the learner says otherwise. "Teach me all I need to solve these" is taught on parallel cases and the questions go back to the learner one at a time, never posted back "answered with the reasoning". Router rule 13, `assignment` §5; the `assignment` description names prelabs.
- **A question set becomes practice they do.** Questions a learner brings to get ready for become an inline practice widget: a card per question, their answer box, hints on parallel cases, and a button that sends their answers back for a verdict where the host allows it, or they paste them. On graded work the widget holds no answer, key, reveal or self-check, even in its source, and shows one of their questions at a time. Router rule 14, `assignment` §2. Measured: an ungraded practice set drew a per-question widget 3 of 3 under both the draft and final text (Sonnet already does this); a graded prelab drew none under either, so the graded-widget rule is untested in use.
- Router rule 9: on a returning topic, "what do you remember?" comes with a foothold; asked for the explanation, explain first and retrieve after.

### Fixed
- `teach` fired on "draw an architecture diagram for the design doc" in 2 of 3 Codex passes. `teach` and the router descriptions now both end "Not work diagrams" / "Not code or work diagrams", and the prompt fires nothing 3 of 3. `teach` otherwise keeps main's wording (the 2.6.0 rewrite sent "help me study" to `teach`; it now goes to the router 3 of 3).
- The no-inline-renderer rule reads the same in `references/visual-teaching.md` as in the router and `tutor` (an HTML file for anything with a control or a hidden answer); `check.py` fails if they drift.
- `PRIVACY.md` and the README describe the hooks, learner record and profile, printing and fetching the same way, and promise only what the skill text instructs.
- `evals/invocation`: a learning prompt counts only a Skill call that succeeded; a work prompt counts any attempted call as a fire. A session fails when its init event doesn't list the plugin under test or lists another Myelinate install. Sessions can't edit files or run commands, so a real repository is left untouched. Adds a conceptual-dev negative ("how does a mutex work? I need one for this worker pool").
- `evals/reply-shape/ab.py`: the blind A/B harness behind the reply-shape numbers, with its raw replies and verdicts.
- `check.py` fails if the router, `tutor` or `assignment` loses the one-screen or graded-coursework rule.

## [2.6.0] - 2026-11-01

### Added
- **Ready for the Claude and OpenAI plugin directories.** A 512 px icon (`assets/icon.png`, the mark on a paper tile), the Claude manifest's `icon`, `documentationUrl` and `supportUrl`, and the Codex manifest's `logo`, `composerIcon`, `brandColor` and capabilities. The Codex short description fits OpenAI's 30-character limit, and its category is the directory's `Education & Research`.
- `PRIVACY.md` and `TERMS.md`, linked from the Codex manifest (`privacyPolicyURL`, `termsOfServiceURL`, `supportURL`), and a README section on what the plugin runs, reads and sends. The Codex listing copy no longer says "Claude".
- `evals/invocation/run.sh`: real headless Claude Code sessions that count Skill tool calls, beside the pick-from-a-list trigger eval.
- `python3 scripts/package.py build` also writes `dist/myelinate-codex.zip` (the manifest at the top, skills only, no hooks) for OpenAI's plugin directory, and `check.py` fails on a Codex listing field past its limit or an icon that isn't in the plugin.

### Changed
- **Inline first.** Visuals and labs show in the conversation itself, through the host's inline render tool (`show_widget` on claude.ai, or an inline HTML render tool in a desktop or IDE host), ahead of a side artifact, an HTML file, a page or a link. Those still come when the learner asks for one, will keep, share, print or return to it, or the host can't render inline. Image-heavy concepts get a crafted inline figure instead of a separate page. Router rule 14, `tutor` §3d, `lab` and `references/visual-teaching.md`; `check.py` fails if any of them loses the rule.
- **Every chart plots its data.** An inline chart with axes and bands but no curve or points reads as broken; the pre-send checklist now catches it.
- Retrieve first when a learner returns to a topic, inline choice inputs for intake and preferences (never for checks of learning), and one control per input for formula visuals with a prediction before the first move.

### Fixed
- **Skills didn't load on learning questions in Claude Code.** On 2026-11-01, Sonnet loaded a Myelinate skill on 0 of 12 learning prompts (6 prompts, 2 passes: a lab report question, "explain Le Chatelier's principle", an exam on R/S, a bare topic, "what is a monad", how a transistor works): the model answered directly. A SessionStart hint (`hooks/route_hint.py`) names the moment, and the router, `tutor`, `teach` and `assignment` descriptions now name quick questions and lab data. Results are in `evals/verification.md`; `check.py` fails if the hint is unregistered or loses its instruction.

## [2.5.0] - 2026-10-25

- Added learner-built concept maps, predict-before-reveal mechanism diagrams and faded worked-step visuals, with an original self-contained HTML stepper and journey test. Credits are in `NOTICE.md`.
- Tightened trigger descriptions and a one-owner routing map across the router and 15 sub-skills. Kept all skill names and commands stable.
- Made teaching levels and host capabilities explicit, with project-space and plain-chat fallbacks. Clarified the optional dbaney.com integration.
- Removed long dash characters from authored skill text and updated the packaged copies.

## [2.4.1] - 2026-10-14

### Fixed
- **`print` no longer writes into its own folder.** The render step ran `make_pdf.py` with paths relative to the skill, so practice tests, PDFs and page previews landed inside the installed skill, which is shared, replaced on update, and bundled whole by some hosts (a rendered test can exceed a bundler's per-file limit). It now works in the learner's project folder or a scratch folder and calls the script by its path in the skill.

## [2.4.0] - 2026-10-14

Myelinate is now one plugin for Claude Code, the Claude apps and Codex, it loads on bare class topics, and its visuals are held to a stricter bar. Driven by a claude.ai session on Plato's *Alcibiades I* that exposed four failures (`evals/regressions/alcibiades-eye.md`).

### Fixed
- **Installed copies missing their files.** The router was registered as the whole repository root (`"skills": ["./"]`), so a host that copies a skill's own folder got `SKILL.md` and nothing else. The router now lives at `skills/myelinate/`, and every skill folder carries a copy of each reference, template and example it names. `scripts/package.py` generates the copies and `dist/myelinate-plugin.zip`; `scripts/check.py` fails on drift or on any referenced path missing from the zip.
- **Missing-file fallback.** The router and every sub-skill say to fetch a missing file from the pinned raw URL, and never to report the gap to the learner or stall on it.
- **Bare class topics.** The router and `tutor` descriptions now trigger on a bare topic from a class the learner takes ("Socrates, the eye"), without widening to tasks.

### Added
- **Plugin for three hosts.** `.claude-plugin` (Claude Code and the Claude apps) and `.codex-plugin` manifests with marketplaces for both. The Claude manifest carries no version, so installs update by commit.
- **`code` skill.** Learn code you have to own: what you need to do with it, a one-picture map, a traced behavior with a prediction first, a run for the verdict, and one `TODO(human)` for the piece that carries the idea. Off for ordinary coding.
- **Myelinate output style** (Claude Code): learn while you code. Claude does the engineering and hands over one decision at a time.
- **Spaced review across sessions** (Claude Code): an opt-in learner record at `~/.myelinate/learner.json` (`references/learner-record.md`) and a SessionStart hook that lists due reviews, silent without a record. `/myelinate:review` runs them; `/myelinate:quiz <topic>` drills one topic.
- **`key-worker` agent** (Claude Code): works the answer key from the problem statement without seeing the learner's answer.
- **Visual rules that stand alone** (router rule 14, `tutor` §3d, `references/visual-teaching.md`): pick the medium by what carries the lesson (a crafted figure or real image when the image itself is the content), clip children to parents, end gaze lines and rays on the target, no icon stand-ins, no scorecards, render and look before sending, and a one-minute checklist. Rule 16 adds "rendered and inspected".
- **When the answer is already on screen** (router rule 1, `tutor` §2a): one transfer or "why this and not that" question instead of a recall quiz.
- **Reference figure** `examples/alcibiades-eye.html` with its rendered screenshot, and the regression case `evals/regressions/alcibiades-eye.md`.

## [2.3.1] - 2026-10-14

Myelinate now loads on its own in long skill lists.

### Fixed
- **Auto-invocation.** Skill listings share a character budget, and once it runs out, long descriptions are dropped and a skill appears by name alone, so it never loads by itself. On claude.ai the 923-character router description was being dropped this way while shorter descriptions in the same list survived. Every description is now 175 characters or less and opens with when to use it, in the words learners type ("teach me", "quiz me", "help me understand", a question from a class).
- **Valid frontmatter.** The router, `teach` and `tutor` descriptions contained `: ` unquoted, which strict YAML parsers reject. All descriptions are now double-quoted.
- **Opt-outs still hold.** The "stay off if opted out" clause moved from the descriptions into the bodies of `teach`, `assess`, `notes`, `flashcards` and `study-plan` (`tutor`, `assignment` and `project` already had it).

### Added
- `scripts/check.py` fails on a description over 175 characters, one that isn't valid YAML, or one that doesn't open with "Use when" or "Use for".
- Trigger scenarios in `evals/scenarios.md`.

## [2.3.0] - 2026-10-11

Myelinate now beats Claude's built-in learning skill in a blind head-to-head on chat tutoring. Version 2.2.1 lost to it (see `evals/verification.md`).

### Added
- **Locate them before you teach** (router rule 1, `tutor` §1, `teach` §5). Fluent field terms set the level, not the format. A beginner missing the concept gets a short direct explanation first. A broad or contested topic gets the shape of help it needs instead of a quiz, and "just lay it out" gets structured exposition with sources.
- **One step forward, every turn.** Each turn has exactly one question and one scaffold. No confidence rating, preference question or intake question is stacked on top, and no turn is questions only.
- **Impatient vs. stuck, early vs. late time claims.** A deadline plus a concrete blocker in the opening message gets a direct answer. A time claim that appears after questioning starts is treated as impatience, and the tutor holds the line more directly.
- **Know when they're done.** After an unaided transfer, the tutor says so, names what they can now do, and points to what comes next, with no new item to answer.
- **Integrity only where it applies.** Self-learners get working answers. When it's unclear whether work is graded, the tutor asks in one line while it starts helping. "My professor allows AI" gets matched to the specific use allowed. Graded answer checks get an honest verdict but never the answer.
- **Visuals on claude.ai.** If `show_widget` is available, call `read_me` once, then show the widget with the prose outside it. Each visual shows one relationship. Neither the visual nor the prose answers the question the tutor is about to ask. Each visual says what the model simplifies.
- **Make what they ask for:** flashcards, quizzes and guides are made right away, built for active recall.
- **Build a live-turn widget** in `references/visual-teaching.md`, with `examples/chair-flip.html` as the reference: a library-free canvas projection, one state value, color that encodes the rule, highlights only where they matter, three controls, host theme tokens and phone-first sizing.
- **Learn-mode parity** scenarios in `evals/scenarios.md`.

## [2.2.1] - 2026-10-11

### Added
- **Crafted figures** in `references/visual-teaching.md`: rendered real apparatus and phenomena across fields (lab setups before lab day, physics demos, chemistry glassware and reactions, engineering mechanisms, measurement instruments), and, for abstract concepts, a recognizable machine whose working is the concept, each driven by one true model, with the mapping and its limits stated, physics-driven shaders only where lines can't draw it, one accented part to watch, prediction before motion, a framed card with a live readout, calm learner-driven motion, critic-style render verification, and honest sizing. Adapted with credit from Anatomy by Ryan (wheresryan22/anatomy, MIT); recommends that skill as an optional companion for crafted figures. `lab` points to it.

## [2.2.0] - 2026-10-11

Myelinate is now a Claude Code plugin with fourteen skills behind the router, and its aim is stated: the Socratic midwife who draws out the learner's own thinking.

### Added
- **Claude Code plugin.** `.claude-plugin/plugin.json` and a `baney75` marketplace. Install with `/plugin install myelinate --marketplace baney75/myelinate` (older Claude Code: `/plugin marketplace add baney75/myelinate`, then `/plugin install myelinate@baney75`). Every skill loads on its own description; slash commands such as `/myelinate:tutor` force one.
- **`assignment`**: coaches graded work (problem sets, lab reports, essays, coding assignments) instead of doing it. Separates tool help from authorship, follows the course's AI policy, and cites the deskilling and never-skilling evidence.
- **`project`**: learn while building, in the mix the learner chooses (build and learn, teach me, or just tell me). Used only when asked; it stays out of ordinary coding and work.
- **`assess`**: tests written to the objectives, graded against a key and rubric (key first), honest scores, optional bonus work, and a gradebook.
- **`notes`**: reads the learner's own notes (Google Drive, OneDrive, Notion, Obsidian or photos of handwritten pages) to see how they are grasping a subject, flags misconceptions and notes that only copy the slides, coaches note-taking, and turns the notes into practice.
- **`course-project`**: turns a big goal into a university-level course researched against accredited syllabi, with a lesson plan, assignments, tests and teacher instructions, to run as a Claude Project. Adds `templates/course-project-prompt.md` and `templates/gradebook.md`.
- **`print`** now builds study guides for active recall: questions first, answers at the back, blank diagrams, contrast tables for confusables, and a mixed self-test.
- **`study-plan`** offers opt-in reminders on a calendar the learner has connected, and earlier personal deadlines by agreement, labeled so they are never confused with the real date.
- **`references/personalization.md`**: an evidence-based learner model that improves over time; adapts to what works, never to a fixed learning-style label.
- **`references/first-session.md`** (shared intake for `tutor` and `teach`) and **`references/visual-teaching.md`** (rendered diagrams, linked representations, interactive 3D models, chemistry tables).
- Router: the Socratic-midwife aim, zero-config use, automatic use, slash commands, opt-outs, and a "no false starts" rule so learning intent triggers Myelinate and ordinary tasks do not.
- Community files: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CITATION.cff`, issue and pull request templates.
- Site: Open Graph and Twitter card tags, canonical link, JSON-LD, `sitemap.xml`, `robots.txt`.

### Changed
- **`tutor`** now serves a course the learner is enrolled in: it loads from memory or the conversation, owns course intake (materials and uploads), and teaches live in chat or voice in the course's scope and notation.
- **`teach`** is rewritten for learning that is not for an enrolled course (personal goals, work skills, projects): the agent designs the curriculum and lesson plans at university standard, anchored in the learner's project and driven by memory.
- Complex anatomy uses the learner's textbook or lecture figures, or licensed real images, instead of generated SVG.
- Router route table and core rules; chemistry playbook additions; new v2.2 scenarios in `evals/scenarios.md`.
- Website and README present fourteen skills and the plugin install path.
- Real headless `claude -p` trigger test with the plugin installed, one run per prompt: 11 of 11 as expected, including five coding and work prompts that loaded no Myelinate skill. One run each, so a smoke test, not a rate. Details and what was not tested are in [evals/verification.md](evals/verification.md).
- Plain words (previously drafted as 2.1.2, never released on its own): checks are called a quick check or warm-up, and clinical words stay out of the intake.

## [2.1.1] - 2026-10-10

### Fixed
- The optional intake invitation listed example conditions, which undid the earlier "never name conditions" wording. It stays open and optional and names nothing.
- A new learner's first reply could skip the question about what helps them study; it now includes one optional what-helps question.

### Changed
- The `tutor` description now mentions hints on practice problems and counting a revealed answer as known, widening its triggers.
- Skill-eval smoke test (Claude Sonnet, 2 repeats): 1.00 held-in and 1.00 held-out, up from 0.85 and 0.79. See [evals/verification.md](evals/verification.md) for limits.

## [2.1.0] - 2026-10-10

### Added
- **`references/how-the-mind-learns.md`**: prediction error, generation, desirable difficulty, consolidation, stress and metacognitive illusions, each tied to a tutor move, with the limits of the myelination evidence (mostly mice).
- `tutor`: seven override rules (verdict from the key; withhold what the learner can generate, give what they can't), a silent pre-reply check, a six-rung help ladder, an answer-leak table, and a sycophancy pressure table.
- Router core rules carry commit-then-inform and key-first honesty so they hold when the router is pasted alone.

### Fixed
- A wrong answer could be opened with "Right." Forward test (one model, author-graded): v2.0.0 passed 9 of 13 cases; v2.1.0 passed 14 of 14 after an adversarial review and one added case.

## [2.0.0] - 2026-10-06

### Changed
- Rebuilt as a router (`SKILL.md`) over nine sub-skills: `teach`, `tutor`, `lab`, `print`, `flashcards`, `memory-hooks`, `study-plan`, `find-media` and `verify`.
- Memory-first: read the learner profile at the start, save at the end, ask before saving anything personal. Honest, not agreeable.
- New brand, landing page, hero and social card.

### Added
- Interactive lab engine with an oxygen-unloading reference lab and a journey test; printable practice tests with separate answer keys; `llms.txt` for the paste-the-link route.

## [0.1.0] - 2026-10-02

### Added
- First release: a single source-grounded teaching skill with course-aware practice, feedback and spaced retrieval, an evidence ledger, a research method, an interactive sample lesson and a package check (`scripts/check.py`). Later additions before 2.0 asked about study preferences rather than conditions, added exam-clock planning and production lessons for study packs.

[2.3.1]: https://github.com/baney75/myelinate/compare/v2.3.0...v2.3.1
[2.3.0]: https://github.com/baney75/myelinate/compare/v2.2.1...v2.3.0
[2.2.1]: https://github.com/baney75/myelinate/compare/v2.2.0...v2.2.1
[2.2.0]: https://github.com/baney75/myelinate/compare/v2.1.1...v2.2.0
[2.1.1]: https://github.com/baney75/myelinate/compare/v2.1.0...v2.1.1
[2.1.0]: https://github.com/baney75/myelinate/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/baney75/myelinate/compare/v0.1.0...v2.0.0
[0.1.0]: https://github.com/baney75/myelinate/releases/tag/v0.1.0
