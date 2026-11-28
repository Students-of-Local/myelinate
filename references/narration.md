# Writing narration for the ear

Read this before you write the `say` lines of a video lesson. A listener can't skim back, can't see punctuation and hears every word at the voice's pace. These rules make a sentence easy to follow the first time.

Credit: the craft here is paraphrased from Hildegard's podcast and writing guides (Donovan Baney, `Students-of-Local/hildegard`, AGPL-3.0), which draw on NPR Training, Transom and Jessica Abel's *Out on the Wire* (2015). Nothing is copied; Myelinate does not need Hildegard to run. If Hildegard is installed, hand it any sound design beyond plain narration (music beds, effects, mixing).

## Sentences

1. **One idea per sentence.** If a sentence has "and" joining two facts, make it two sentences.
2. **Subject and verb early.** "Selection removes the dominant allele quickly" beats "Quickly, because it shows in heterozygotes, the dominant allele is removed."
3. **Concrete words.** Name the thing: "green frogs", not "the phenotype in question".
4. **Repeat names.** On paper a pronoun works; by ear, say "the recessive allele" again instead of "it" when two things are in play.
5. **No asides in parentheses.** The voice can't show brackets. Make the aside its own sentence or cut it.

## Numbers and symbols

1. **Say symbols as words.** "p squared plus two p q plus q squared equals one". Never `p^2`, `=`, `/` or `Δ` in a `say` line. The checker refuses them; put the symbols on screen in an `equation` or `step`.
2. **Say numbers the way a person would.** "zero point six five", "about nine hundred ninety", "one in ten thousand". The caption shows the same words, so match the course's style.
3. **Round when the exact value doesn't matter,** and repeat a number the learner must hold: "Chi-square is two point nine two. Two point nine two is less than three point eight four."
4. **One new number per sentence** when you can.

## Signposts

1. **Tell them where they are.** "Step three." "Now the second case." "Here is the trap." The ear needs the map the eye gets from headings.
2. **Recap after a long stretch.** One sentence: "So far: count alleles, then square them."
3. **End a chapter with a pull into the next.** A question works: "So how do we test whether a real population fits?"

## The voice itself

1. **One voice for the whole lesson.** A change of voice sounds like a new speaker.
2. **Pace 130 to 165 words a minute.** Slower for a worked step, never rushed. `voice_check.py` measures it.
3. **Read every line aloud once** before making clips. Rewrite any line you stumble on; the voice will stumble too.
4. **Fix mispronounced words with `pronounce`,** never by misspelling the caption.
5. **Disclose the AI voice** in the credits. Never use a voice made to sound like a real person.

## Words to cut

Stock phrases that sound machine-made: "delve", "tapestry", "a testament to", "in a world where", "it's important to note", "let's dive in". Lists of three that exist only for rhythm. "Not X, but Y" when nobody said X. An abstraction where an example would do the work.
