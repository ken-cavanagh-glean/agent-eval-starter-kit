# Glean Agent Eval Starter Kit

Evaluate any Glean agent using an LLM-as-judge pattern. Feed your agent a set of test inputs, then let a judge — powered by Glean's own LLM and enterprise search — score each response across dimensions you define.

## Quick Start

```bash
git clone https://github.com/ken-cavanagh-glean/agent-eval-starter-kit.git
cd agent-eval-starter-kit
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # fill in your Glean API token and server URL
```

Then configure your eval in `dimensions.yaml`:

```yaml
agent_id: your-agent-id-here

dimensions:
  - id: response_quality
    name: Response Quality
    description: Is the output well-structured, concise, and actionable?
    scale: [full, substantial, partial, minimal, failure]
```

Add test cases to `eval_inputs_template.csv` and run:

```bash
python eval.py
```

Results are written to `eval_results.csv` with scores and per-dimension reasoning.

## Available Dimensions

Response Quality and Groundedness are enabled by default. Uncomment others in `dimensions.yaml` or define your own.

| Dimension | Description | Scale |
|-----------|-------------|-------|
| Response Quality | Is the output well-structured, concise, and actionable? | full, substantial, partial, minimal, failure |
| Groundedness | Are claims supported by documents the agent actually retrieved? | full, substantial, partial, minimal, failure |
| Hallucination Risk | Does the response assert specific details without source backing? | low, medium, high |
| Factual Accuracy | Are specific claims true according to current company data? | full, substantial, partial, minimal, failure |

## How It Works

```
For each row in eval_inputs_template.csv:

  1. Auto-detect agent type (form fields vs chat)
  2. Send input to target agent (Agents API)
  3. For each dimension:
     a. Build a judge prompt for that dimension
     b. Run judge (ChatGlean + GleanSearchTool)
     c. Parse score via XML tags
  4. Write scored row to eval_results.csv
```

Each dimension gets its own judge call — the judge evaluating Response Quality doesn't see Groundedness context and vice versa. Scores are extracted via XML tags for reliable parsing.

For form-triggered agents with multiple input fields, add columns to the CSV matching the field names. The script auto-detects the agent's input schema.

## File Structure

| File | Purpose |
|------|---------|
| `eval.py` | Main script — runs target agent, calls judge per dimension, writes results |
| `judge.py` | LangChain judge — ChatGlean + GleanSearchTool |
| `dimensions.yaml` | Agent ID + evaluation dimensions |
| `eval_inputs_template.csv` | Test case inputs |
| `eval_results.csv` | Scored output with per-dimension reasoning (generated) |
| `.env.example` | Credentials template |

## Customization

- **Dimensions** — Edit `dimensions.yaml`. Use any scale (5-level, 3-level, binary). Add your own with a unique `id`.
- **Judge prompt** — Edit `build_judge_prompt()` in `judge.py`.
- **Form fields** — For multi-field agents, add CSV columns matching the agent's input field names.

## Rate Limits

The Glean Agents API allows 0.5 req/s (30 qpm). With one judge call per dimension, a 2-dimension eval takes ~3 API calls per test case. The script includes a configurable delay (`DELAY_BETWEEN_CALLS`).

See the [Glean Developer Docs](https://developers.glean.com/) for more.
