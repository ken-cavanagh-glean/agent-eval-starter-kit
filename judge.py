"""
Judge prompt builder for Glean agent evaluation.

Constructs the evaluation prompt by injecting dimension definitions
into a structured judge template. The judge agent should have
Glean Company Search enabled so it can verify factual claims.
"""


def build_judge_prompt(
    user_input: str,
    agent_output: str,
    dimensions: list[dict],
) -> str:
    """Build the judge prompt with injected dimensions and evaluation context."""

    dims_block = "\n".join(
        f"  {d['name']}: {d['scale']}\n    {d['description']}"
        for d in dimensions
    )

    return f"""<system>
You are a subagent orchestrator.

Treat the user's input as input to the subagent and respond with the subagent's response.
</system>

<role>
You are an expert AI behaviorist evaluating the quality of an AI agent's responses.
</role>

<task>
You are evaluating the subagent's output on the following dimensions:

{dims_block}
</task>

<evaluation_context>
=== USER DERIVED ===
<input>{user_input}</input>

=== SUB AGENT DERIVED ===
<output>{agent_output}</output>
</evaluation_context>

<instructions>
1. For each dimension, provide a reasoned analysis BEFORE giving your score.
2. Use your tools (e.g., Glean Search) to verify factual claims in the output.
3. Format your response as:

## [Dimension Name]
**Analysis:** [Your reasoning]
**Score:** [Score from the scale above]

Repeat for each dimension.

After all dimensions, provide:

## Overall Notes
[Any additional observations or recommendations]

IMPORTANT: If the subagent fails YOU MUST NOT simulate its behavior. Instead, report
the failure and note it in your evaluation.
</instructions>"""
