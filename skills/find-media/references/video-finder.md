# Finding, vetting and sectioning a video

Use this when a learner wants a video for a concept, or says they learn best from videos. The goal is the few minutes of one video that teach exactly what their course tests, checked against their course, with questions around it. A whole 40-minute lecture with no check is not a recommendation.

## 1. Know what you're matching before you search

Write these down from the learner's own material (study guide, slides, notes, a missed exam item) before any search:

- **Target:** the one concept or move, as their course words it ("E2 needs an anti-periplanar H", not "elimination").
- **Must-say terms:** three to six words or symbols a good segment has to say aloud (`anti-periplanar, Zaitsev, strong base, Hofmann`).
- **Course claims:** the two to five statements their source makes that the video must not contradict, with where each came from (slide 14, textbook 7.3).
- **Level and notation:** intro or upper level; their sign conventions, units and symbols.
- **The confusion,** if you know it: from a debrief or a wrong answer. A segment that fixes their actual mistake beats one that covers the chapter.

With no course material, use a reliable source for the course claims and say so.

## 2. Search wide, then cut to a shortlist

<!-- local-tools -->
**With a shell and `yt-dlp` already installed** (never install it), run the finder from this skill's folder. It searches, reads each candidate's chapters and captions, and returns the shortlist with the segments where the must-say terms are spoken:

```
python3 scripts/yt.py scan "E2 elimination anti-periplanar organic chemistry" --terms "anti-periplanar,Zaitsev,strong base,Hofmann" --n 8
```

Run two or three phrasings if the first list is thin: the course's own words, the textbook's chapter title, and the exact confusion ("why does E2 need anti periplanar"). Other commands, each with `--help`: `search` (titles only), `info` (chapters, captions, embeddable), `transcript` (timestamped text), `find` (segments in one video). It reads one caption track at a time and waits between videos, because YouTube answers rapid or translated caption requests with HTTP 429. If it reports 429, wait a minute and scan fewer videos; don't loop.
<!-- /local-tools -->

**Without a shell:** use your search tool as in `find-media` (search for the watch URL, check each with the oEmbed endpoint), and get transcripts as in `video` (a host caption tool, the browser's **Show transcript** panel, or the learner's paste). A host video tool that returns transcripts is the same as the finder's `transcript`.

Cut to three or four candidates on facts you read, not on the title:

- **Captions exist.** No captions means you can't vet it or point inside it; drop it unless nothing else exists, and then say "not reviewed."
- **Embeddable,** so it can play here. A video that isn't can still be linked.
- **Length fits.** A long lecture is fine if the right segment is short. A short with no explanation is not a lesson.
- **Channel and date.** Prefer the starter channels in `find-media`, a university or the textbook's publisher. Check the date against anything that changes (exam outlines, guidelines, software versions).

## 3. Find the segment, then read it

Chapters come first: a chapter titled with the target is the segment. Otherwise use the term hits (`find`), and widen to the full explanation: start at the sentence that sets up the problem, end after the result is stated or the example is finished. Twenty seconds before and after is cheap.

Then **read the transcript of that segment yourself.** Term hits only say where words occur. A speaker who lists "SN1, SN2, E1, E2" in an intro scores well and teaches nothing. A good segment explains why, works an example, or shows the move step by step.

## 4. Vet it against the course

For each course claim from step 1, find what the segment says and give one verdict:

| Verdict | What you do |
| --- | --- |
| **Matches** | Nothing. Mention it in the vetting note. |
| **Same idea, other notation** | Keep it and give the mapping before they watch: "He writes ΔG°; your slides write ΔG°′, same idea at pH 7." |
| **Beyond the course** | Keep it if it helps; mark the part as not on their exam. |
| **Contradicts** | Drop the video if the contradiction is on a point they'll be tested on. Keep it only if it's uniquely good and the conflict is a convention or a short aside; then tell them to stop at that timestamp and what their course says instead. |
| **Can't tell** | Say so. Don't count it as a match. |

Also check, before calling it vetted:

- **Caption errors aren't contradictions.** "Zaitsev" captioned as "sight self" is a caption error. Read around it.
- **The board isn't in the transcript.** You read what was said, not what was written or drawn. Say so in the note: "I checked what she says, not every equation on the board." If your host lets you see frames or the learner sends a screenshot, check the key equation.
- **Check the subject yourself.** If the video and the course agree but both look wrong, check a reliable source and tell the learner.

## 5. Give one segment, framed for active watching

Lead with one pick. Give the learner:

1. **The segment,** not the video: title, channel, the range (`4:10 to 9:30, about 5 minutes`), a link that starts there (`&t=250s`), and an embed that stops at the end when you can render one (`inline-widgets.html`'s video view takes `start`, `end` and `segments`).
2. **The vetting note,** two or three lines: what you checked it against, what matched, any notation mapping, and what to skip.
3. **One question to watch for,** taken from their target or their mistake.
4. **Pause points** from the transcript, each just before a key move: "Pause at 6:02. Which hydrogen leaves, and why that one?"
5. **After:** a recall prompt with the video closed, then one new problem they do without it.

If the concept needs pieces from two videos, give an ordered list of at most three segments with the total minutes. Never more than about fifteen minutes of watching before they answer a question.

Then the video goes back to being a tool: recall and practice are what show whether they learned it. A learner who says they learn best from videos still gets the recall and the problem. Their preference decides how a concept gets taught first, not whether they practice it.

## Don't

Recommend a video you didn't find this session. Give a timestamp you didn't read. Call a video vetted when you read only its title or description. Hand over a full lecture when a segment exists. Download the video itself: link and embed it.
