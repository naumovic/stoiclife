# STOIC-MODULES.md — Stoic modules

Focus modules Mihajlo can call from a journal entry. Add `module:<name>` at the **start or end** of a `morning prep:` / `evening review:` entry, before or after `mood:`:

- `morning prep: module:emotions mood:6 — rough start, …`
- `evening review: … quality time with Z. mood:7 module:happiness`

`save_entry.py` strips the token and stores the module on the entry. `coach_context.py` prints that module's principles, and the coach gives them extra weight in its reply (`AGENTS.md` §1).

**Format (parsed by `scripts/stoic_modules.py`, keep it exact):** one `## <number> · <Name>` section per module, then an `Aliases:` line (comma-separated, lowercase; the number and the name are always accepted), then one `- ` bullet per principle. To add a module, add a section. No code change is needed.

## 1 · Happiness
Aliases: happiness, hapiness, happy

- Seek balance and practice restraint
- Align yourself with the world - accept your unique traits and conditions
- Try to see yourself clearly - acknowledge your limitations and try your very best within you
- We can live only in the present. But unless we are connected to our past and future through memory, life does not make any sense
- Align with the wider flow of life by focusing on the sensory pleasures of the everyday
- We are a species endowed with an adventurous spirit. There is an internal child-like need for a secure base and attachment - you need to balance that with exploration
- Quo vadis: Don't just look for a happy ending - ask where you are going? When you're happy, you won't just want to live happily ever after. On the strength of a secure base, you would rather travel and explore
- Align with the consequences of your own choices - take responsibility for your actions and make the best of their outcome
- Use the concept of kodawari instead of perfection - the adherence to your own quality perception. There might be one small, niche aspect of the work (i.e. specialist skill) that you want to focus on. Kodawari is a nagomi between your ideals and the reality of the status quo.

## 2 · Creativity
Aliases: creativity, creative

- The more you go into the technical details of the system, the more you need stoicism. Otherwise what you build will just be a sandcastle blown by the winds of the world
- Be rigorous and stoically logical and observe the laws of physics
- Practice Ganbaru: make extraordinary efforts to battle through incredible difficulties

## 3 · Emotions
Aliases: emotions, emotion, emotional

- Never expect a certain behaviour from anyone. That way you will never be disappointed
- Our emotional circuits centred around amygdala reacting to surprising events fast
- As we go about our lives, we cannot simply avoid uncertainty
- Loneliness is not something that can be shared. The loneliness you might feel when you sense that your life is finally ending cannot be shared, and yet this is a destiny that will come to us all someday
- Why we shouldn't hide emotions: It's only with emotions that we can taste life in the full
