# AI Interactions Log

> **Stretch features only.** Only fill in the sections that apply to stretch features you attempted. If you did not attempt a stretch feature, leave its section blank or delete it. This file is not required for the core project.

---

## Agentic Workflow (SF8)

> Document your experience using an AI agent (e.g., Cursor Agent, Claude, Copilot) to make multi-step changes autonomously.

**What task did you give the agent?**

<!-- Describe the goal you asked the agent to accomplish -->
Preview the songs csv to understand basic trends

**Prompts used:**

<!-- Paste the key prompts you gave the agent -->
generate 5–10 additional songs in a valid CSV format that includes the existing headers. Ensure the new songs represent a diverse range of genres and moods not already present in the starter file

**What did the agent generate or change?**

<!-- List the files edited, code generated, or commands run -->
basic system architecutre (see README file), which we discussed and updated continuously 

**What did you verify or fix manually?**

<!-- Describe anything the agent got wrong or that required human review -->
insisted that the user profile only store the top genre, i suggested doing a recording keeping of the user's taste across genres.
my ai agent aggreeed and suggested that the caluclation be based on the user's highest favored genre
 

---

## Design Pattern (SF10)

> Document how AI helped you choose or implement a design pattern.

**Which design pattern did you use?**

<!-- e.g., Strategy, Factory, Observer, etc. -->

**How did AI help you brainstorm or implement it?**

<!-- Describe the conversation or suggestions that led to your decision -->

**How does the pattern appear in your final code?**

<!-- Point to the relevant class or method -->

---

## Project 4: Agent Reasoning Traces

The recommender's agent mode (`src/agent.py`) plans, acts, checks its own results and revises its plan before answering:

| Step | What happens |
|---|---|
| **PLAN** | Gemini turns the request into a taste profile, which is then validated against the catalog |
| **ACT** | Tool call `search_catalog(profile)`: the Project 3 scorer retrieves the top 8 songs |
| **CHECK** | A rule-based checker looks for energy conflicts, acoustic conflicts and too few strong matches |
| **REVISE** | Gemini proposes a new profile, given the problems found and every earlier attempt (rule-based fallback if Gemini fails) |
| **STOP** | After 2 revisions, or when a revision repeats an earlier attempt |
| **ANSWER** | The best attempt (fewest conflicts, then most strong matches) is explained by Gemini, using only the retrieved songs |

Each trace below was produced with `python -m src.main --ask "<request>" --agent --save-trace`:

| Request | What the agent did | Trace |
|---|---|---|
| "chill lofi to study to" | First search passed the check, so it answered directly (no extra LLM calls) | [trace](traces/20261117-214641-chill-lofi-to-study-to.md) |
| "sad blues but really high energy, I want to get hyped" | Found that the only blues song is calm, added synthwave/rock to bridge the gap, and stopped at the revision limit | [trace](traces/20261117-214759-sad-blues-but-really-high-energy-i-want-.md) |
| "acoustic metal for headbanging" | Found that no metal song is acoustic, dropped that filter and added rock | [trace](traces/20261117-214741-acoustic-metal-for-headbanging.md) |
