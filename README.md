# Glean Agent Eval Starter Kit

Evaluate any Glean agent using an LLM-as-judge pattern. Supports both workflow (form-triggered) and autonomous (chat-triggered) agents.

The judge is a LangChain agent powered by `ChatGlean` with `GleanSearchTool` — Glean handles both LLM inference and enterprise search. No external LLM provider needed.

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/ken-cavanagh-glean/agent-eval-starter-kit.git
cd agent-eval-starter-kit
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | What it is | Where to find it |
|----------|-----------|-----------------|
| `GLEAN_API_TOKEN` | User-scoped API token with `chat`, `search`, and `agents` scopes | Your Glean admin provisions these. [Docs](https://developers.glean.com/api-info/client/authentication/glean-issued) |
| `GLEAN_SERVER_URL` | Your Glean backend URL | [app.glean.com/admin/about-glean](https://app.glean.com/admin/about-glean) → "Server instance (QE)" |
| `TARGET_AGENT_ID` | The agent you want to evaluate | Agent Builder URL: `/admin/agents/{agentId}` |

### 3. Prepare test cases

Edit `eval_inputs_template.csv` with inputs appropriate for your agent:

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

### 4. Configure dimensions

Edit `dimensions.yaml` to define what you're measuring:

```yaml
- name: Groundedness
  description: Is the response grounded in verifiable company data?
  scale: FULL | SUBSTANTIAL | PARTIAL | MINIMAL | FAILURE

- name: Task Success
  description: Did the agent complete the requested task?
  scale: PASS | PARTIAL | FAIL
```

### 5. Run

```bash
python eval.py
```

Results are written to `eval_results.csv`.

## How It Works

```
For each row in eval_inputs_template.csv:

  1. Auto-detect agent type (form fields vs chat)
  2. Send input to target agent (Agents API)
  3. Build judge prompt (inject dimensions + input + output)
  4. Run LangChain judge (ChatGlean + GleanSearchTool)
  5. Parse dimension scores from judge response
  6. Write scored row to eval_results.csv
```

The **target agent** is called via the Glean Agents API. The script queries the agent's input schema to auto-detect form fields vs chat triggers.

The **judge** is a LangChain agent using `ChatGlean` as the LLM and `GleanSearchTool` for enterprise search. It can do multi-step reasoning — searching your indexed data to verify factual claims before scoring each dimension. All inference runs through Glean.

## File Structure

| File | Purpose |
|------|---------|
| `eval.py` | Main script — runs target agent, calls judge, writes results |
| `judge.py` | LangChain judge — ChatGlean + GleanSearchTool |
| `dimensions.yaml` | Evaluation dimensions — edit this |
| `eval_inputs_template.csv` | Test case inputs — edit this |
| `eval_results.csv` | Scored output (generated) |
| `.env.example` | Credentials template |

## Customization

- **Dimensions** — Edit `dimensions.yaml`. Use any scale: 5-level, 3-level, or binary.
- **Judge prompt** — Edit `build_judge_prompt()` in `judge.py` to change evaluation instructions.
- **Form fields** — For multi-field agents, add CSV columns matching the agent's input field names.

## Rate Limits

The Glean Agents API allows 0.5 requests/second (30 per minute). The script includes a configurable delay (`DELAY_BETWEEN_CALLS`).

For more details, see the [Glean Developer Docs](https://developers.glean.com/).
