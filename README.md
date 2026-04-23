# Glean Agent Eval Starter Kit

Evaluate any Glean agent using an LLM-as-judge pattern. Feed your agent a set of test inputs, then let a judge — powered by Glean's own LLM and enterprise search — score each response across dimensions you define.

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/ken-cavanagh-glean/agent-eval-starter-kit.git
cd agent-eval-starter-kit
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.example .env   # fill in your Glean API token and server URL
```

### 3. Configure your eval

Edit `dimensions.yaml` — set your agent ID and dimensions:

```yaml
agent_id: abc123def456

dimensions:
  - id: response_quality
    name: Response Quality
    description: Is the output well-structured, concise, and actionable?
    scale: [full, substantial, partial, minimal, failure]
```

### 4. Prepare test cases

Edit `inputs_template.csv` with inputs appropriate for your agent:

```csv
input
What is our PTO policy?
How do I submit an expense report?
```

For **form-triggered agents** with multiple fields, add columns matching the field names:

```csv
input,department
Acme Corp,Sales
Globex Inc,Engineering
```

The script auto-detects whether your agent is form-triggered or chat-triggered and maps CSV columns to input fields accordingly.

### 5. Run

```bash
python eval.py
```

Results are written to `eval_results.csv`.

## Available Dimensions

The starter kit includes these dimensions. Response Quality and Groundedness are enabled by default — uncomment others in `dimensions.yaml` as needed.

| Dimension | Description | Scale |
|-----------|-------------|-------|
| Response Quality | Is the output well-structured, concise, and actionable? | full, substantial, partial, minimal, failure |
| Groundedness | Are claims supported by documents the agent actually retrieved? | full, substantial, partial, minimal, failure |
| Hallucination Risk | Does the response assert specific details without source backing? | low, medium, high |
| Factual Accuracy | Are specific claims true according to current company data? | full, substantial, partial, minimal, failure |

You can also define your own dimensions with custom scales.

## How It Works

```
For each row in inputs_template.csv:

  1. Auto-detect agent type (form fields vs chat)
  2. Send input to target agent (Agents API)
  3. For each dimension:
     a. Build a judge prompt for that dimension
     b. Run judge (ChatGlean + GleanSearchTool)
     c. Parse score from XML tags in response
  4. Write scored row to eval_results.csv
```

The **target agent** is called via the Glean Agents API. The script queries the agent's input schema to auto-detect form fields vs chat triggers.

The **judge** is a LangChain agent using `ChatGlean` as the LLM and `GleanSearchTool` for enterprise search. Each dimension gets its own judge call so scores are isolated — the judge evaluating Response Quality doesn't see Groundedness context and vice versa. All inference runs through Glean.

## File Structure

| File | Purpose |
|------|---------|
| `eval.py` | Main script — runs target agent, calls judge per dimension, writes results |
| `judge.py` | LangChain judge — ChatGlean + GleanSearchTool, XML-based score extraction |
| `dimensions.yaml` | Agent ID + evaluation dimensions — edit this |
| `inputs_template.csv` | Test case inputs — edit this |
| `eval_results.csv` | Scored output with per-dimension reasoning (generated) |
| `.env.example` | Credentials template |

## Customization

- **Dimensions** — Edit `dimensions.yaml`. Use any scale (5-level, 3-level, binary). Add your own with a unique `id`.
- **Judge prompt** — Edit `build_judge_prompt()` in `judge.py` to change evaluation instructions.
- **Form fields** — For multi-field agents, add CSV columns matching the agent's input field names.

## Rate Limits

The Glean Agents API allows 0.5 requests/second (30 per minute). With one judge call per dimension, a 2-dimension eval takes ~3 API calls per test case (1 target + 2 judge). The script includes a configurable delay (`DELAY_BETWEEN_CALLS`).

For more details, see the [Glean Developer Docs](https://developers.glean.com/).
