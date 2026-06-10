---
name: skill-creator
description: Create new skills or improve existing ones through an iterative draft → test → compare → revise loop. Use when the user wants to add a skill, port one from another harness, tune triggering, or make a skill more reliable.
argument-hint: [skill name, path, or task]
---

# Skill Creator

Create or improve a skill in a way that survives contact with reality.

Topic: **$ARGUMENTS**

This is the Pi-adapted version of Anthropic's skill-creator workflow. The core idea stays the same:

1. understand what the skill should do
2. write a draft
3. test it on realistic prompts
4. compare results to a baseline
5. revise based on what actually happened
6. repeat until the skill is clearly better

The Pi adaptation changes the mechanics:
- use Pi skills and files, not Claude Code-only features
- use `agent` spawning when available, or work inline if not
- store evals and outputs as normal files
- use side-by-side markdown comparison by default instead of a custom viewer
- avoid unsupported frontmatter or harness-specific assumptions

---

## What a Good Skill Looks Like

A good skill is not just a clever prompt. It is:

- **easy to trigger** — the description says what it does *and when to use it*
- **lean** — the main `SKILL.md` stays focused; bulky detail moves to `references/` or scripts
- **practical** — if the workflow repeatedly needs helper code, bundle a script instead of making the model reinvent it
- **testable** — you can tell whether it helped on a few real tasks
- **general** — it should not only work on the exact examples used during development

When editing a skill, prefer explanation over command barking. If you keep writing `ALWAYS`, `NEVER`, or brittle step lists, stop and ask what behavior you are actually trying to induce.

---

## When to Create a Skill vs Do Something Else

Create or improve a skill when the workflow is:
- repeated across sessions or projects
- annoying to restate every time
- specialized enough that the model benefits from domain instructions
- a mix of reference material, workflow, and helper scripts

Do **not** make a skill when:
- the rule belongs in `AGENTS.md` or project `CLAUDE.md`
- the task is one-off
- the process is so deterministic that a plain script is better than a skill
- the workflow is still too vague to describe clearly

---

## Phase 1: Capture Intent

Start by understanding what the skill is for.

Pull as much as you can from the current conversation before interrogating the user. If they already described the workflow, do not make them repeat themselves.

Figure out:

1. **What should the skill enable?**
2. **When should it trigger?**
3. **What should success look like?**
4. **Is this a reference skill, an action skill, or a hybrid?**
5. **Does it need helper scripts or reference docs?**
6. **Should the user invoke it manually, or should the model auto-load it?**

Useful follow-up questions:
- What are 2-3 real prompts a user might type?
- What does a good output look like?
- What mistakes would make the skill feel broken?
- Does the workflow touch files, run scripts, or depend on external tools?
- Is the skill Pi-specific, or are we porting from Claude Code/Codex/etc.?

---

## Phase 2: Research and Inspect

Before writing, inspect the environment.

### If improving an existing skill

Read:
- the current `SKILL.md`
- supporting files in the skill directory
- recent transcripts, reports, or examples showing where the skill worked or failed

### If porting from another harness

Read the source skill carefully and translate it, do not cargo-cult it.

Look for harness-specific features such as:
- `context: fork`
- `allowed-tools`
- Claude Code-specific subagent or viewer workflows
- shell interpolation features Pi may not support
- assumptions about built-in tools or command names

Keep the underlying intent. Replace the mechanics.

### If creating from scratch

Look for neighboring skills that establish local style:
- frontmatter shape
- description style
- section ordering
- whether helper scripts or `references/` are used

---

## Phase 3: Write the First Draft

Create the skill directory and write `SKILL.md`.

### Frontmatter

Include at minimum:

```yaml
---
name: skill-name
description: What the skill does and when to use it.
---
```

Use `argument-hint` if the command benefits from arguments.

### Description guidance

The description is the trigger. Front-load the important bits.

Weak:
```yaml
description: Helps with planning.
```

Better:
```yaml
description: Create implementation plans for features, refactors, and bug fixes. Use when the user asks to break down work, estimate scope, or turn a vague task into concrete steps.
```

### Body guidance

Keep `SKILL.md` focused on:
- what the skill is for
- how to decide whether to use it
- the workflow to follow
- where to look next (`references/`, `scripts/`, templates)

Move bulky detail out of the main file when:
- a reference section gets long
- examples pile up
- there is a deterministic helper the model keeps recreating

### Structure pattern

```markdown
# Skill Name

What this skill is for.

## When to use it
- situation A
- situation B

## Workflow
1. do this
2. then this
3. verify

## Supporting files
- `references/foo.md` — domain detail
- `scripts/bar.sh` — deterministic helper
```

---

## Phase 4: Create Realistic Eval Prompts

Write 2-5 realistic prompts. These should sound like what an actual user would type, not benchmark gobbledygook.

Good eval prompts:
- resemble real user requests
- cover normal use and at least one edge case
- exercise the core promise of the skill

Bad eval prompts:
- restate the skill back to itself
- over-explain the desired answer
- only test the happy path

Save them in a simple workspace so the loop is inspectable.

## Workspace Layout

Use a temporary workspace while developing or evaluating a skill. In this repository, do not commit `skill-workspace/` directories unless the user explicitly asks to preserve skill-evaluation artifacts. The committed skill should normally contain `SKILL.md` plus deliberate `references/`, `scripts/`, or examples only.

Recommended temporary layout:

```text
<skill-root>/skill-workspace/
  evals.md
  iteration-1/
    baseline/
    with-skill/
  iteration-2/
    baseline/
    with-skill/
```

A lightweight `evals.md` is enough:

```markdown
# Evals

## eval-1
Prompt: ...
Why it matters: ...

## eval-2
Prompt: ...
Why it matters: ...
```

---

## Phase 5: Run the Comparison

The baseline depends on the situation.

### Baselines

- **New skill**: run the task without the skill
- **Existing skill improvement**: compare against the old skill version
- **Port from another harness**: compare the original skill and the Pi-adapted one if both can be exercised meaningfully

### How to run in Pi

If the `agent` tool is available, prefer spawning fresh agents so each run gets a clean context. Use one run per eval prompt for:
- `baseline`
- `with-skill`

If `agent` is not available, do the runs inline in separate fresh sessions when possible.

For each run, save:
- the prompt
- the resulting output or files
- a short note on whether the skill triggered and behaved as intended

A simple per-run file is enough:

```markdown
# eval-1 / with-skill

Prompt: ...

## Outcome
...

## Notes
- Triggered correctly? yes/no
- Main strengths:
- Main failures:
```

### What to compare

Look at:
- did the skill trigger when it should?
- did it reduce flailing?
- did it improve output structure or correctness?
- did it cause unhelpful extra work?
- did it overfit to one phrasing?

For action skills, also compare:
- file paths used
- scripts executed
- whether it actually completed the task

---

## Phase 6: Analyze and Revise

Revise from evidence, not vibes.

### Common improvement moves

#### 1. Fix triggering
If the model failed to use the skill, the description is usually the first suspect.

Improve the description by making it clearer about:
- what the skill does
- what user language should trigger it
- what nearby situations also count

#### 2. Remove dead weight
If the transcript shows the skill causing pointless ceremony, cut it.

Examples:
- too many required sections in the output
- long setup text that does not change behavior
- redundant explanation of obvious concepts

#### 3. Explain the why
If the model follows instructions mechanically but misses the point, explain the reasoning.

Instead of:
- “Always include X”

Try:
- “Include X because without it the next session cannot resume safely”

#### 4. Bundle repeated helpers
If multiple runs recreate the same helper script or transformation, add a real script under `scripts/` and tell the skill when to use it.

#### 5. Split bulky content
If the main file is turning into a wall of text, move detail to:
- `references/`
- example files
- templates
- scripts

---

## Phase 7: Iterate Until It Is Clearly Better

Run another iteration when:
- the skill improved but still misses obvious cases
- triggering is still weak
- the output is inconsistent across prompts
- the skill is promising but too verbose or too brittle

Stop when:
- the user is happy
- the skill beats the baseline on the important prompts
- further changes are mostly churn

Do not keep iterating just because iteration feels productive.

---

## Pi-Specific Adaptation Notes

When adapting a skill from Anthropic or another harness, keep these Pi realities in mind:

- Pi skills are plain skill directories with `SKILL.md` plus optional files.
- Progressive disclosure still matters: keep descriptions sharp and main files focused.
- Some harness-specific frontmatter or execution features may not exist or may behave differently in Pi.
- Pi is happy with plain files, scripts, and markdown comparisons. You do not need a fancy evaluation UI to improve a skill.
- If Pi-specific tools exist in this environment, use them. If not, write the workflow so it still works with `read`, `write`, `edit`, and `bash`.

---

## Deliverables

When finishing a skill-creation pass, leave behind:

1. the updated skill directory
2. notes on what was tested; use an issue comment or chat summary unless the user asks for committed eval artifacts
3. a concise summary for the user:
   - what changed
   - what was tested
   - what still seems weak

If the work is substantial and the repo has a scratchpad, write a report there.

---

## Gotchas

- Do not overfit to the 2-3 eval prompts that were easiest to inspect.
- Do not blindly port unsupported features from other harnesses.
- Do not turn every behavior into a rigid rule; first ask what outcome you actually need.
- Do not leave the skill untested if it has side effects or workflow complexity.
- Do not forget that the description is the trigger.
- Do not commit `skill-workspace/` folders in this repo unless explicitly requested.

---

## See Also

- [[skills/search/SKILL|/search]] — find reference skills, docs, and examples
- [[skills/report/SKILL|/report]] — capture what changed and why
- [[skills/visual-explainer/SKILL|/visual-explainer]] — useful for side-by-side eval comparison pages
