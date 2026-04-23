#!/usr/bin/env python3
"""
Glean Agent Eval Starter Kit

Evaluate any Glean agent using an LLM-as-judge pattern.

Usage:
    1. Copy .env.example to .env and fill in credentials
    2. Set agent_id in dimensions.yaml
    3. Add test cases to eval_inputs_template.csv
    4. Configure dimensions in dimensions.yaml
    5. Run: python eval.py
"""

import csv
import os
import re
import time

import httpx
import yaml
from dotenv import load_dotenv
from glean.api_client import Glean

from judge import build_judge_prompt, create_judge_agent, run_judge

load_dotenv()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIGURATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

INPUT_CSV = "eval_inputs_template.csv"
OUTPUT_CSV = "eval_results.csv"
CONFIG_FILE = "dimensions.yaml"

# Glean Agents API: 0.5 req/s (30 qpm)
DELAY_BETWEEN_CALLS = 2.5


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# IMPLEMENTATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def load_config(path: str) -> tuple[str, list[dict]]:
    """Load agent ID and dimensions from the YAML config file."""
    with open(path, "r") as f:
        config = yaml.safe_load(f)

    agent_id = config.get("agent_id", "")
    if not agent_id or agent_id == "your-target-agent-id":
        raise ValueError("Set agent_id in dimensions.yaml")

    dims = config.get("dimensions", [])
    for d in dims:
        if not all(k in d for k in ("id", "name", "description", "scale")):
            raise ValueError(
                f"Dimension '{d.get('name', '?')}' missing required fields "
                f"(need: id, name, description, scale)"
            )

    return agent_id, dims


def get_agent_input_schema(api_token: str, server_url: str, agent_id: str) -> dict:
    """Fetch the agent's input schema to detect form fields.

    Returns the input_schema dict (e.g. {"prospect": {"type": "string"}})
    or empty dict for chat-triggered agents.
    """
    resp = httpx.get(
        f"{server_url}/rest/api/v1/agents/{agent_id}/schemas",
        headers={"Authorization": f"Bearer {api_token}"},
        timeout=15,
    )
    if resp.is_success:
        return resp.json().get("input_schema", {})
    return {}


def run_target_agent(
    client: Glean,
    agent_id: str,
    user_input: str,
    input_schema: dict,
    csv_row: dict,
) -> str:
    """Run the target agent, handling both form-triggered and chat-triggered agents."""
    if input_schema:
        fields = {}
        schema_field_names = list(input_schema.keys())
        for field in schema_field_names:
            if field in csv_row and csv_row[field]:
                fields[field] = csv_row[field]
            elif field == schema_field_names[0]:
                fields[field] = user_input
            else:
                fields[field] = ""
        response = client.client.agents.run(agent_id=agent_id, input=fields)
    else:
        response = client.client.agents.run(
            agent_id=agent_id,
            messages=[
                {"role": "user", "content": [{"text": user_input, "type": "text"}]},
            ],
        )

    if response.messages:
        parts = []
        for msg in response.messages:
            if msg.content:
                for block in msg.content:
                    if hasattr(block, "text") and block.text:
                        parts.append(block.text)
        return "\n".join(parts)
    return ""


def parse_score(judge_response: str, dim: dict) -> tuple[str, str]:
    """Extract score and reasoning from judge response using XML tags.

    Looks for: <dim_id_reasoning>...</dim_id_reasoning> and <dim_id>score</dim_id>
    """
    dim_id = dim["id"]

    reasoning_match = re.search(
        rf"<{dim_id}_reasoning>([\s\S]*?)</{dim_id}_reasoning>",
        judge_response,
    )
    reasoning = reasoning_match.group(1).strip() if reasoning_match else ""

    score_match = re.search(
        rf"<{dim_id}>([\s\S]*?)</{dim_id}>",
        judge_response,
    )
    raw_score = score_match.group(1).strip().lower() if score_match else ""

    # Match against valid scale values
    matched = None
    for category in dim["scale"]:
        if category.lower() in raw_score:
            matched = category
            break

    if not matched:
        print(f"  !! Could not parse score for {dim['name']}. Raw: '{raw_score}'")

    return matched or raw_score or "PARSE_ERROR", reasoning


def main():
    api_token = os.getenv("GLEAN_API_TOKEN")
    server_url = os.getenv("GLEAN_SERVER_URL")

    if not api_token:
        print("Error: GLEAN_API_TOKEN not set. Copy .env.example to .env and fill it in.")
        return
    if not server_url:
        print("Error: GLEAN_SERVER_URL not set. Find it at app.glean.com/admin/about-glean.")
        return

    if not os.path.exists(CONFIG_FILE):
        print(f"Error: {CONFIG_FILE} not found.")
        return
    try:
        target_agent_id, dimensions = load_config(CONFIG_FILE)
    except ValueError as e:
        print(f"Error: {e}")
        return

    if not os.path.exists(INPUT_CSV):
        print(f"Error: {INPUT_CSV} not found.")
        return
    with open(INPUT_CSV, "r") as f:
        reader = csv.DictReader(f)
        if "input" not in (reader.fieldnames or []):
            print("Error: CSV must have an 'input' column.")
            return
        cases = list(reader)
    if not cases:
        print("Error: No rows in CSV.")
        return

    # Detect agent type
    print(f"Detecting input schema for agent {target_agent_id}...")
    input_schema = get_agent_input_schema(api_token, server_url, target_agent_id)
    if input_schema:
        print(f"  Form-triggered agent. Fields: {list(input_schema.keys())}")
    else:
        print(f"  Chat-triggered agent.")

    print(f"Evaluating {len(cases)} cases")
    print(f"Judge: ChatGlean + GleanSearchTool (one call per dimension)")
    print(f"Dimensions: {', '.join(d['name'] for d in dimensions)}")
    print()

    # Create judge agent (reused across all calls)
    judge = create_judge_agent()
    results = []

    with Glean(api_token=api_token, server_url=server_url) as client:
        for i, case in enumerate(cases):
            user_input = case["input"]
            print(f"[{i + 1}/{len(cases)}] {user_input[:80]}...")

            # Step 1: Run target agent
            print("  -> Running target agent...")
            try:
                agent_output = run_target_agent(
                    client, target_agent_id, user_input, input_schema, case
                )
            except Exception as e:
                print(f"  !! Target agent failed: {e}")
                agent_output = f"AGENT_ERROR: {e}"

            time.sleep(DELAY_BETWEEN_CALLS)

            # Step 2: Run one judge call per dimension
            scores = {}
            reasonings = {}
            for dim in dimensions:
                print(f"  -> Judging: {dim['name']}...")
                prompt = build_judge_prompt(user_input, agent_output, dim)
                try:
                    judge_response = run_judge(prompt, judge)
                    score, reasoning = parse_score(judge_response, dim)
                    scores[dim["name"]] = score
                    reasonings[dim["name"]] = reasoning
                except Exception as e:
                    print(f"  !! Judge failed for {dim['name']}: {e}")
                    scores[dim["name"]] = "JUDGE_ERROR"
                    reasonings[dim["name"]] = str(e)
                time.sleep(DELAY_BETWEEN_CALLS)

            result = {
                "input": user_input,
                "output": agent_output,
                **scores,
                **{f"{name}_reasoning": r for name, r in reasonings.items()},
            }
            results.append(result)

            for dim_name, score in scores.items():
                print(f"  {dim_name}: {score}")

    # Write results
    if results:
        fieldnames = (
            ["input", "output"]
            + [d["name"] for d in dimensions]
            + [f"{d['name']}_reasoning" for d in dimensions]
        )
        with open(OUTPUT_CSV, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
        print(f"\nResults written to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
