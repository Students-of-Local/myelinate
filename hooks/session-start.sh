#!/bin/sh
# Claude Code SessionStart hook. Plain text only: it reads nothing, runs nothing else and uses no network.
# To turn it off, create the file ~/.myelinate/no-hint, or disable the plugin.
[ -e ~/.myelinate/no-hint ] && exit 0
echo "Myelinate (learning plugin) is installed. When the user wants to learn, understand, study or practice something (a concept, a skill, a class topic, homework or a lab report, an exam, a bare topic), call the Skill tool for the matching myelinate skill (myelinate:tutor, myelinate:assignment, myelinate:teach, myelinate:myelinate and so on) before you answer, even for a quick question. Don't load it for work they want done, or for questions about the code, repository, errors or files in front of them (explain this stack trace, what does this function do), unless they say they want to learn it."
[ -e ~/.myelinate/learner.json ] && echo "This learner keeps a Myelinate record at ~/.myelinate/learner.json. If they turn to learning, read it and fold what's due into the session, after answering whatever they came with."
exit 0
