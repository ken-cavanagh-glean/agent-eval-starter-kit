#!/usr/bin/env python3
"""
Glean Agent Eval Starter Kit

Evaluate any Glean agent using an LLM-as-judge pattern.

Usage:
    1. Copy .env.example to .env and fill in credentials
    2. Set TARGET_AGENT_ID to the agent you want to evaluate
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
        if not all(k in d for k in ("name", "description", "scale")):
            raise ValueError(f"Dimension missing required fields: {d}")

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
    """Run the target agent, handling both form-triggered and chat-triggered agents.

    For form-triggered agents: maps CSV columns to form fields.
    For chat-triggered agents: sends the input as a chat message.
    """
    if input_schema:
        # Form-triggered: build input dict from schema fields
        fields = {}
        schema_field_names = list(input_schema.keys())

        for field in schema_field_names:
            if field in csv_row and csv_row[field]:
                # CSV has a column matching this field name
                fields[field] = csv_row[field]
            elif field == schema_field_names[0]:
                # First field gets the "input" column value as default
                fields[field] = user_input
            else:
                fields[field] = ""

        response = client.client.agents.run(
            agent_id=agent_id,
            input=fields,
        )
    else:
        # Chat-triggered: send as message
        response = client.client.agents.run(
            agent_id=agent_id,
            messages=[
                {"role": "user", "content": [{"text": user_input, "type": "text"}]},
            ],
        )

    # Extract text from response
    if response.messages:
        parts = []
        for msg in response.messages:
            if msg.content:
                for block in msg.content:
                    if hasattr(block, "text") and block.text:
                        parts.append(block.text)
        return "\n".join(parts)

    return ""


def parse_scores(judge_response: str, dimensions: list[dict]) -> dict:
    """Extract scores from judge response.

    Looks for: ## Dimension Name ... **Score:** VALUE
    """
    scores = {}
    for dim in dimensions:
        name = dim["name"]
        pattern = (
            rf"##\s*{re.escape(name)}"
            rf".*?\*\*Score:\*\*\s*([A-Z_]+)"
        )
        match = re.search(pattern, judge_response, re.DOTALL | re.IGNORECASE)
        scores[name] = match.group(1).strip() if match else "PARSE_ERROR"
    return scores


def main():
    api_token = os.getenv("GLEAN_API_TOKEN")
    server_url = os.getenv("GLEAN_SERVER_URL")

    if not api_token:
        print("Error: GLEAN_API_TOKEN not set. Copy .env.example to .env and fill it in.")
        return
    if not server_url:
        print("Error: GLEAN_SERVER_URL not set. Find it at app.glean.com/admin/about-glean.")
        return
    # Load config
    if not os.path.exists(CONFIG_FILE):
        print(f"Error: {CONFIG_FILE} not found.")
        return
    try:
        target_agent_id, dimensions = load_config(CONFIG_FILE)
    except ValueError as e:
        print(f"Error: {e}")
        return

    # Read inputs
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
    print(f"Judge: ChatGlean + GleanSearchTool")
    print(f"Dimensions: {', '.join(d['name'] for d in dimensions)}")
    print()

    # Create judge agent (once, reused across cases)
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

            # Step 2: Run judge
            print("  -> Running judge...")
            judge_prompt = build_judge_prompt(user_input, agent_output, dimensions)
            try:
                judge_response = run_judge(judge_prompt, judge)
            except Exception as e:
                print(f"  !! Judge failed: {e}")
                judge_response = f"JUDGE_ERROR: {e}"

            time.sleep(DELAY_BETWEEN_CALLS)

            # Step 3: Parse scores
            scores = parse_scores(judge_response, dimensions)

            result = {
                "input": user_input,
                "output": agent_output,
                **scores,
                "judge_reasoning": judge_response,
            }
            results.append(result)

            for dim_name, score in scores.items():
                print(f"  {dim_name}: {score}")

    # Write results
    if results:
        fieldnames = (
            ["input", "output"]
            + [d["name"] for d in dimensions]
            + ["judge_reasoning"]
        )
        with open(OUTPUT_CSV, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
        print(f"\nResults written to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
