#!/usr/bin/env python3
"""
Glean Agent Eval Boilerplate

Evaluate a Glean agent's responses using an LLM-as-judge pattern.

Usage:
    1. Set environment variables (see .env.example)
    2. Edit DIMENSIONS below to match your evaluation criteria
    3. Fill eval_inputs.csv with test cases
    4. Run: python eval.py

Prerequisites:
    - pip install glean-api-client
    - A Glean API token with agents + search scopes
    - A judge agent built in Glean Agent Builder with Company Search enabled
"""

import csv
import os
import re
import time

from glean.api_client import Glean

from judge import build_judge_prompt

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIGURATION — Edit this section
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Agent to evaluate (find ID in Agent Builder URL: /admin/agents/{agentId})
TARGET_AGENT_ID = os.getenv("TARGET_AGENT_ID", "your-target-agent-id")

# Judge agent (must have Glean Company Search enabled)
JUDGE_AGENT_ID = os.getenv("JUDGE_AGENT_ID", "your-judge-agent-id")

# File paths
INPUT_CSV = "eval_inputs.csv"
OUTPUT_CSV = "eval_results.csv"

# Rate limiting — Glean allows 0.5 req/s (30 qpm) for /agents/runs
DELAY_BETWEEN_CALLS = 2.5  # seconds between agent calls

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DIMENSIONS — Edit these to match your evaluation criteria
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Each dimension has:
#   name        — column header in the output CSV
#   description — what the judge should evaluate (be specific)
#   scale       — the scoring options (judge picks one)

DIMENSIONS = [
    {
        "name": "Groundedness",
        "description": (
            "Is the response grounded in data verifiable in Glean? "
            "Use Glean Search to check whether claims can be traced "
            "to indexed documents."
        ),
        "scale": "FULL | SUBSTANTIAL | PARTIAL | MINIMAL | FAILURE",
    },
    {
        "name": "Response Quality",
        "description": (
            "Is the response clear, well-structured, and actionable "
            "for the user? Consider formatting, completeness, and "
            "whether it directly addresses the request."
        ),
        "scale": "FULL | SUBSTANTIAL | PARTIAL | MINIMAL | FAILURE",
    },
    {
        "name": "Task Success",
        "description": (
            "Did the agent successfully complete the requested task? "
            "A pass means the core request was fulfilled. Partial means "
            "some but not all aspects were addressed."
        ),
        "scale": "PASS | PARTIAL | FAIL",
    },
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# IMPLEMENTATION — You probably don't need to edit below here
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def run_agent(client: Glean, agent_id: str, message: str) -> str:
    """Run a Glean agent and return the response text.

    Uses the Agents API (POST /rest/api/v1/agents/runs/wait).
    The agent must be chat-triggered (not form-triggered).
    """
    response = client.client.agents.run(
        agent_id=agent_id,
        messages=[
            {"role": "user", "content": [{"text": message, "type": "text"}]},
        ],
    )

    # Extract text from response messages
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
    """Extract scores from judge response text.

    Looks for the pattern:
        ## Dimension Name
        **Analysis:** ...
        **Score:** SCORE_VALUE
    """
    scores = {}
    for dim in dimensions:
        name = dim["name"]
        # Match: ## Dimension Name ... **Score:** VALUE
        pattern = (
            rf"##\s*{re.escape(name)}"
            rf".*?\*\*Score:\*\*\s*(.+?)(?:\n|$)"
        )
        match = re.search(pattern, judge_response, re.DOTALL | re.IGNORECASE)
        scores[name] = match.group(1).strip() if match else "PARSE_ERROR"
    return scores


def main():
    # Validate environment
    api_token = os.getenv("GLEAN_API_TOKEN")
    instance = os.getenv("GLEAN_INSTANCE")
    server_url = os.getenv("GLEAN_SERVER_URL")

    if not api_token:
        print("Error: GLEAN_API_TOKEN environment variable is required.")
        print("See .env.example for setup instructions.")
        return

    if not instance and not server_url:
        print("Error: Set either GLEAN_INSTANCE or GLEAN_SERVER_URL.")
        return

    if TARGET_AGENT_ID.startswith("your-"):
        print("Error: Set TARGET_AGENT_ID in eval.py or as an env var.")
        return

    if JUDGE_AGENT_ID.startswith("your-"):
        print("Error: Set JUDGE_AGENT_ID in eval.py or as an env var.")
        return

    # Read inputs
    if not os.path.exists(INPUT_CSV):
        print(f"Error: {INPUT_CSV} not found. Create it with an 'input' column.")
        return

    with open(INPUT_CSV, "r") as f:
        reader = csv.DictReader(f)
        if "input" not in (reader.fieldnames or []):
            print("Error: CSV must have an 'input' column.")
            return
        cases = list(reader)

    if not cases:
        print("Error: No rows found in CSV.")
        return

    print(f"Evaluating {len(cases)} cases against agent {TARGET_AGENT_ID}")
    print(f"Judge: {JUDGE_AGENT_ID}")
    print(f"Dimensions: {', '.join(d['name'] for d in DIMENSIONS)}")
    print()

    # Initialize Glean client
    client_kwargs = {"api_token": api_token}
    if server_url:
        client_kwargs["server_url"] = server_url
    elif instance:
        client_kwargs["instance"] = instance

    results = []

    with Glean(**client_kwargs) as client:
        for i, case in enumerate(cases):
            user_input = case["input"]
            print(f"[{i + 1}/{len(cases)}] {user_input[:80]}...")

            # Step 1: Run the target agent
            print("  -> Running target agent...")
            try:
                agent_output = run_agent(client, TARGET_AGENT_ID, user_input)
            except Exception as e:
                print(f"  !! Target agent failed: {e}")
                agent_output = f"AGENT_ERROR: {e}"

            time.sleep(DELAY_BETWEEN_CALLS)

            # Step 2: Run the judge agent
            print("  -> Running judge agent...")
            judge_prompt = build_judge_prompt(user_input, agent_output, DIMENSIONS)
            try:
                judge_response = run_agent(client, JUDGE_AGENT_ID, judge_prompt)
            except Exception as e:
                print(f"  !! Judge agent failed: {e}")
                judge_response = f"JUDGE_ERROR: {e}"

            time.sleep(DELAY_BETWEEN_CALLS)

            # Step 3: Parse scores
            scores = parse_scores(judge_response, DIMENSIONS)

            result = {
                "input": user_input,
                "output": agent_output[:2000],
                **scores,
                "judge_reasoning": judge_response[:3000],
            }
            results.append(result)

            # Print scores
            for dim_name, score in scores.items():
                print(f"  {dim_name}: {score}")

    # Write results
    if results:
        fieldnames = (
            ["input", "output"]
            + [d["name"] for d in DIMENSIONS]
            + ["judge_reasoning"]
        )
        with open(OUTPUT_CSV, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
        print(f"\nResults written to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
