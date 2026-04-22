"""
Code-first judge for Glean agent evaluation.

Uses LangChain with ChatGlean (Glean as the LLM) and GleanSearchTool
for fact verification. No external LLM provider needed — everything
runs through your Glean instance.
"""

from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_glean.chat_models import ChatGlean
from langchain_glean.retrievers import GleanSearchRetriever
from langchain_glean.tools import GleanSearchTool


def build_judge_prompt(
    user_input: str,
    agent_output: str,
    dimensions: list[dict],
) -> str:
    """Build the evaluation prompt with injected dimensions."""

    dims_block = "\n".join(
        f"  {d['name']}: {d['scale']}\n    {d['description']}"
        for d in dimensions
    )

    return f"""You are evaluating an AI agent's output on these dimensions:

{dims_block}

=== USER INPUT ===
{user_input}

=== AGENT OUTPUT ===
{agent_output}

For each dimension, provide a reasoned analysis BEFORE giving your score.
Use your glean_search tool to verify factual claims in the output.

Format your response as:

## [Dimension Name]
**Analysis:** [Your reasoning]
**Score:** [Score from the scale above]

Repeat for each dimension, then:

## Overall Notes
[Any additional observations]

If the agent produced an error or empty response, score accordingly —
do NOT simulate what the agent might have said."""


def create_judge_agent() -> AgentExecutor:
    """Create a LangChain agent using Glean for both LLM and search."""

    llm = ChatGlean()

    retriever = GleanSearchRetriever()
    glean_tool = GleanSearchTool(
        retriever=retriever,
        name="glean_search",
        description="Search the company knowledge base to verify factual claims.",
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are an expert AI evaluator. Use glean_search to verify "
         "factual claims against company data before scoring."),
        ("user", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ])

    agent = create_openai_tools_agent(llm, [glean_tool], prompt)
    return AgentExecutor(agent=agent, tools=[glean_tool], verbose=False)


def run_judge(prompt: str, judge: AgentExecutor) -> str:
    """Run the judge and return the evaluation text."""
    result = judge.invoke({"input": prompt})
    return result.get("output", "")
