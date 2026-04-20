# Glean Agent Eval Boilerplate

Evaluate your Glean agents using an LLM-as-judge pattern. Runs your agent against a set of test inputs, then uses a judge agent (with Glean Company Search) to score responses across configurable dimensions.

## Setup

### 1. Prerequisites

- Python 3.9+
- A Glean API token with `agents` and `search` scopes
- Two agents in Glean Agent Builder:
  - **Target agent** — the agent you want to evaluate
  - **Judge agent** — an agent with Company Search enabled (used to verify facts and score responses)

### 2. Install

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your credentials and agent IDs
```

### 3. Create a Judge Agent

In Glean Agent Builder, create a new agent:
- **Name:** "Eval Judge" (or whatever you prefer)
- **Tools:** Enable **Company Search** (required for fact verification)
- **Instructions:** Leave blank — the eval script injects the judge prompt dynamically

### 4. Prepare Test Cases

Edit `eval_inputs.csv` with your test inputs:

```csv
input
What is our company's PTO policy?
How do I submit an expense report?
```

### 5. Configure Dimensions

Edit the `DIMENSIONS` list in `eval.py` to define what you're measuring:

```python
DIMENSIONS = [
    {
        "name": "Groundedness",
        "description": "Is the response grounded in verifiable data?",
        "scale": "FULL | SUBSTANTIAL | PARTIAL | MINIMAL | FAILURE",
    },
    # Add your own dimensions here
]
```

## Run

```bash
# Load env vars
source .env

# Run evals
python eval.py
```

Results are written to `eval_results.csv`.

## File Structure

| File | Purpose |
|------|---------|
| `eval.py` | Main script — config, dimensions, runner. **Edit this file.** |
| `judge.py` | Judge prompt template — injects dimensions into evaluation prompt |
| `eval_inputs.csv` | Your test cases (one input per row) |
| `eval_results.csv` | Output with scores per dimension |
| `.env.example` | Environment variable template |

## How It Works

```
For each row in eval_inputs.csv:
  1. Send input to target agent (Agents API)
  2. Build judge prompt (inject dimensions + input + output)
  3. Send to judge agent (Agents API, with Company Search)
  4. Parse scores from judge response
  5. Write to eval_results.csv
```

## Rate Limits

The Glean Agents API allows 0.5 requests/second (30 per minute). The script includes a configurable delay (`DELAY_BETWEEN_CALLS`) between API calls. For large eval sets, expect ~5 seconds per test case.

## Customization

- **Add dimensions:** Add entries to the `DIMENSIONS` list in `eval.py`
- **Change scales:** Use any scale format (binary, 3-level, 5-level)
- **Form-triggered agents:** If your target agent uses a form trigger instead of chat, modify `run_agent()` to pass `input={...}` instead of `messages=[...]`
