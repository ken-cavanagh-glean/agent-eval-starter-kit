#!/usr/bin/env python3
"""Evaluate a Glean agent using LLM-as-judge. See README for setup."""

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

INPUT_CSV = "inputs_template.csv"
OUTPUT_CSV = "eval_results.csv"
CONFIG_FILE = "dimensions.yaml"
DELAY_BETWEEN_CALLS = 2.5  # Glean Agents API: 0.5 req/s


def load_config(path: str) -> tuple[str, list[dict]]:
    with open(path) as f:
        config = yaml.safe_load(f)
    agent_id = config.get("agent_id", "")
    if not agent_id or agent_id == "your-target-agent-id":
        raise ValueError("Set agent_id in dimensions.yaml")
    return agent_id, config.get("dimensions", [])


def get_agent_input_schema(api_token: str, server_url: str, agent_id: str) -> dict:
    """Fetch input schema to detect form fields vs chat trigger."""
    resp = httpx.get(
        f"{server_url}/rest/api/v1/agents/{agent_id}/schemas",
        headers={"Authorization": f"Bearer {api_token}"},
        timeout=15,
    )
    return resp.json().get("input_schema", {}) if resp.is_success else {}


def run_target_agent(
    client: Glean, agent_id: str, user_input: str,
    input_schema: dict, csv_row: dict,
) -> str:
    """Run the target agent. Auto-handles form-triggered and chat-triggered."""
    if input_schema:
        schema_fields = list(input_schema.keys())
        fields = {}
        for field in schema_fields:
            if field in csv_row and csv_row[field]:
                fields[field] = csv_row[field]
            elif field == schema_fields[0]:
                fields[field] = user_input
            else:
                fields[field] = ""
        response = client.client.agents.run(agent_id=agent_id, input=fields)
    else:
        response = client.client.agents.run(
            agent_id=agent_id,
            messages=[{"role": "user", "content": [{"text": user_input, "type": "text"}]}],
        )

    parts = []
    for msg in response.messages or []:
        for block in msg.content or []:
            if hasattr(block, "text") and block.text:
                parts.append(block.text)
    return "\n".join(parts)


def parse_score(judge_response: str, dim: dict) -> tuple[str, str]:
    """Extract score and reasoning via XML tags."""
    dim_id = dim["id"]

    reasoning_match = re.search(rf"<{dim_id}_reasoning>([\s\S]*?)</{dim_id}_reasoning>", judge_response)
    reasoning = reasoning_match.group(1).strip() if reasoning_match else ""

    score_match = re.search(rf"<{dim_id}>([\s\S]*?)</{dim_id}>", judge_response)
    raw_score = score_match.group(1).strip().lower() if score_match else ""

    matched = next((c for c in dim["scale"] if c.lower() in raw_score), None)
    if not matched:
        print(f"  !! Could not parse score for {dim['name']}. Raw: '{raw_score}'")
    return matched or raw_score or "PARSE_ERROR", reasoning


def main():
    api_token = os.getenv("GLEAN_API_TOKEN")
    server_url = os.getenv("GLEAN_SERVER_URL")
    if not api_token or not server_url:
        print("Error: Set GLEAN_API_TOKEN and GLEAN_SERVER_URL in .env")
        return

    try:
        target_agent_id, dimensions = load_config(CONFIG_FILE)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}")
        return

    with open(INPUT_CSV) as f:
        reader = csv.DictReader(f)
        cases = list(reader)
    if not cases:
        print(f"Error: No rows in {INPUT_CSV}")
        return

    # Detect agent type
    input_schema = get_agent_input_schema(api_token, server_url, target_agent_id)
    if input_schema:
        print(f"Agent {target_agent_id} — form fields: {list(input_schema.keys())}")
    else:
        print(f"Agent {target_agent_id} — chat-triggered")
    print(f"Evaluating {len(cases)} cases | Dimensions: {', '.join(d['name'] for d in dimensions)}\n")

    judge = create_judge_agent()
    results = []

    with Glean(api_token=api_token, server_url=server_url) as client:
        for i, case in enumerate(cases):
            user_input = case["input"]
            print(f"[{i + 1}/{len(cases)}] {user_input[:80]}...")

            # Run target agent
            try:
                agent_output = run_target_agent(client, target_agent_id, user_input, input_schema, case)
            except Exception as e:
                print(f"  !! Target agent failed: {e}")
                agent_output = f"AGENT_ERROR: {e}"
            time.sleep(DELAY_BETWEEN_CALLS)

            # Judge each dimension independently
            scores, reasonings = {}, {}
            for dim in dimensions:
                print(f"  -> {dim['name']}...", end=" ", flush=True)
                try:
                    resp = run_judge(build_judge_prompt(user_input, agent_output, dim), judge)
                    score, reasoning = parse_score(resp, dim)
                    scores[dim["name"]] = score
                    reasonings[dim["name"]] = reasoning
                    print(score)
                except Exception as e:
                    print(f"ERROR: {e}")
                    scores[dim["name"]] = "JUDGE_ERROR"
                    reasonings[dim["name"]] = str(e)
                time.sleep(DELAY_BETWEEN_CALLS)

            results.append({
                "input": user_input,
                "output": agent_output,
                **scores,
                **{f"{k}_reasoning": v for k, v in reasonings.items()},
            })

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
