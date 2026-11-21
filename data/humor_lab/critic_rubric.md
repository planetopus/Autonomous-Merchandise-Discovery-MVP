# Sticker Line Critic Rubric

Score every line 1–10. **Keep only lines scoring 7 or higher.**

These scores mean whether the **target group and most people** would find the line funny, not whether it matches one person's private taste. The catalog should cover millions of different kinds of people. Joke shapes are reused across identities. The example groups (dads, nurses, morticians) are not the topic and get no extra weight.

A line that only describes the behavior, with no ironic twist, scores under 7.

Judge like a tough crowd that also has $5 to spend on a sticker.

## The one test that matters most
**Would a real member of this group read it, say "that's literally me" (or "that's my dad/wife/coworker"), and buy it?**
If the answer is no, the line can't score above 5, however clever it is.

## Hard gates (fail any one and the score is at most 4)
1. **Real group, true traits.** Every trait named must be true of the same real, recognizable person. Random stacks fail ("ASTRONAUT GOAT FARMERS WHO LOVE JAZZ").
2. **Clear ironic or sarcastic turn.** The line must contain either
   - **Irony:** the opposite of what's expected, where both halves are true. A sincere/wholesome identity plus a vice, a calm pro who panics at small things, or a "safety" role doing the unsafe thing.
   - **Sarcasm:** saying the opposite with a straight face, like fake enthusiasm, gratitude or pride about something miserable. The tell must be unmistakable.
   No turn = no joke ("Nurse life: coffee, chaos, repeat").
3. **Original.** It doesn't copy or closely paraphrase any Reddit reference line, stock slogan ("Professional overthinker", "World's okayest…", "Keep calm and…"), or forum sentence.
4. **4–14 words**, readable in about 1 second at bumper distance.
5. **No job-title puns.** "Code Blue, Cold Case" is a title, not a joke.

## Scored criteria (after the gates)
| Criterion | Points | What earns full marks |
|---|---|---|
| Self-recognition | 0–3 | Insiders instantly see themselves; a specific, true habit (not "loves coffee") |
| Irony/sarcasm strength | 0–3 | The turn is sharp, lands at the END of the line, and needs no explanation |
| Voice mismatch | 0–2 | Words the group would never use about themselves (Gen Z slang on grandpas, clinical jargon on a marriage, chipper tone on death) |
| Sellability | 0–2 | Giftable ("that's so you"), wearable in public, has a clear buyer, works as text-only |

Dark humor is welcome. Darkness 0–3 doesn't add or subtract points by itself. It only counts if the darkness is the group's OWN gallows humor (nurses, morticians, dispatchers, divorced folks laughing at their own lives). Punching at victims, illness from the outside, or tragedies fails gate 1.

## Anchored examples

### 3/10 (reject)
- "Code Blue, Cold Case": a pun title with no person, no turn and no recognition.
- "This is with a 0.4 mm nozzle.": a quoted forum sentence with no joke.
- "ASTRONAUT GOAT FARMERS WHO LOVE JAZZ": a random stack that no real person matches.
- "Nurse life: coffee, chaos, repeat.": a stock format with no ironic turn, already sold a million times.

### 6/10 (close, but cut)
- "Professional overthinker": true and relatable, but worn out, with no turn left.
- "Retired: no boss, no deadlines, no idea what day it is.": recognizable, but a generic list with no twist.
- "WHOLESOME VAPING GRANNIES": the right idea, but too short and vague, and it reads as random rather than a group you've actually met.
- "HOT TAKE HAIRSTYLISTS WITH NO THERAPY LICENSE": the true trait is buried under a weak mismatch word.

### 9/10 (keep, top tier)
- "Calm through forty overdoses. Panics when the doorbell rings." is the ceiling for competence versus a tiny fear. Vague "sigma" with no vivid habit is only ok, not top tier.
- "Calm through forty overdoses. Panics when the doorbell rings.": sharp situational irony and the dispatcher's own dark humor. Insiders feel seen.
- "Hi! I'm everyone's emergency contact!": sarcasm via fake cheer about a heavy role. Oldest daughters and moms buy it instantly.
- "Discharged against medical advice to go to Applebee's.": clinical jargon on a personal life, an ironic turn at the end, and every nurse knows it.
- Reference ceiling (ant's favorite, not ours to copy): "THICC DADS WHO VAPE FOR CHRIST" is a real, existing group named truthfully in Gen Z words, with the sincere "for Christ" against the vape.

## Output format for the engine's critic
Return JSON per line:
`{"line": "...", "gates_passed": true, "device": "irony|sarcasm", "self_recognition": 0-3, "turn": 0-3, "voice_mismatch": 0-2, "sellability": 0-2, "score": 1-10, "who_buys_it": "one phrase", "why": "one sentence"}`
Score = sum of criteria (max 10). If any gate fails, the score is at most 4.
