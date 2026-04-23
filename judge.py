"""
Code-first judge for Glean agent evaluation.

Uses LangChain with ChatGlean (Glean as the LLM) and GleanSearchTool
for fact verification. No external LLM provider needed.

Each dimension gets its own judge call for isolated scoring.
Scores are extracted via XML tags (not markdown) for reliable parsing.
"""

from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_glean.chat_models import ChatGlean
from langchain_glean.retrievers import GleanSearchRetriever
from langchain_glean.tools import GleanSearchTool


def build_judge_prompt(user_input: str, agent_output: str, dim: dict, agent_description: str) -> str:
    """Build a judge prompt for a single dimension.

    Uses XML tags for structured output so scores can be reliably parsed
    regardless of how the LLM formats its markdown.
    """
    dim_id = dim["id"]
    scale_str = " / ".join(dim["scale"])

    return f"""You are an expert evaluator assessing an AI agent's response.

=== AGENT UNDER EVALUATION ===
{agent_description}

=== DIMENSION ===
{dim["name"]}: {dim["description"]}

Scale: {scale_str}

=== MATERIAL ===

<query>
{user_input}
</query>

<agent_response>
{agent_output}
</agent_response>

=== INSTRUCTIONS ===

1. Analyze the response against the dimension above
2. Use your glean_search tool to verify factual claims if needed
3. Provide your reasoning, then your score

Output EXACTLY this format:

<{dim_id}_reasoning>
[Your analysis here]
</{dim_id}_reasoning>
<{dim_id}>[{scale_str}]</{dim_id}>"""


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
