"""LLM-as-a-judge evaluation harness for Echo AI."""

import json
from typing import Any
from pydantic import BaseModel, Field

from src.agentframework.core import AgentConfig, AgentCallback, create_agent

# Use rich for CLI UI
try:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    has_rich = True
except ImportError:
    console = None
    has_rich = False
    Table = None


class ScoreResult(BaseModel):
    """The extraction schema for the judge LLM."""

    score: int = Field(
        ...,
        description="An integer from 1 to 10 representing how well the agent accomplished the expected behavior.",
    )
    reasoning: str = Field(..., description="A short explanation validating the score.")


class ToolUsageTracker(AgentCallback):
    """Callback that records every tool invoked during a run."""

    def __init__(self) -> None:
        self.tools_used: list[str] = []

    def on_tool_start(
        self, run_id: str, tool_name: str, tool_kwargs: dict[str, Any]
    ) -> None:
        self.tools_used.append(tool_name)

    @property
    def tool_names(self) -> set[str]:
        return set(self.tools_used)


def _format_tool_usage_failures(
    item: dict[str, Any], tracker: ToolUsageTracker
) -> str:
    """Build a diagnostic suffix when tool routing doesn't match expectations."""
    expected = item.get("tool_used")
    if not expected:
        return ""
    actual = tracker.tool_names
    if expected in actual:
        return ""
    return (
        f"\n\n[TOOL ROUTING FAILURE]\n"
        f"Expected tool: {expected}\n"
        f"Tools actually used: {sorted(actual) if actual else '(none)'}"
    )


async def evaluate_dataset(
    dataset_path: str,
    agent_config: AgentConfig,
    sub_agents_config: dict[str, dict[str, Any]] | None = None,
) -> float:
    """Run the evaluation dataset against the provided agent configuration.

    If *sub_agents_config* is provided (a dict mapping name → config dict),
    those sub-agents are registered on each agent before evaluation.
    """
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    # Use a separate judge agent strictly for extraction.
    # Use Ollama locally so we don't require an OpenAI API Key
    judge_config = AgentConfig(
        provider="ollama", model="qwen3:4b-instruct", session_enabled=False
    )
    judge = create_agent(judge_config, api_key="dummy_judge_key")

    results = []

    for item in dataset:
        prompt = item["prompt"]
        expected = item["expected_behavior"]

        # Spawn a fresh agent for each iteration to avoid memory bleed
        agent = create_agent(agent_config)

        # Register sub-agents (needed for delegate tests)
        if sub_agents_config:
            for name, sub_cfg in sub_agents_config.items():
                agent.register_sub_agent(
                    name=name,
                    description=sub_cfg.get("description", ""),
                    model=sub_cfg.get("model"),
                    tools=sub_cfg.get("tools", []),
                    system_prompt=sub_cfg.get("system_prompt", ""),
                )

        # Track tool usage
        tracker = ToolUsageTracker()
        agent.add_callback(tracker)

        if console:
            console.print(
                f"\n[bold cyan]Evaluating [{item['id']}][/bold cyan]: {prompt}"
            )
        else:
            print(f"\nEvaluating [{item['id']}]: {prompt}")

        try:
            actual_response = await agent.run(prompt)
        except Exception as e:
            actual_response = f"AGENT CRASHED: {e}"

        # --- tool-routing check -------------------------------------------------
        routing_failure = _format_tool_usage_failures(item, tracker)

        # --- keyword check ------------------------------------------------------
        keyword_failure = ""
        for kw in item.get("expected_keywords") or []:
            if kw.lower() not in actual_response.lower():
                keyword_failure += (
                    f"\n[KEYWORD MISSING] Expected keyword not found: '{kw}'"
                )

        judge_prompt = (
            "You are an expert AI evaluator grading another agent's performance.\n"
            f"User Prompt: {prompt}\n"
            f"Expected Behavior: {expected}\n"
            f"Actual Response: {actual_response}\n"
            f"{routing_failure}"
            f"{keyword_failure}"
            "\n\nEvaluate if the Actual Response successfully meets the Expected Behavior. "
            "If there are tool-routing or keyword failures listed above, the score "
            "must reflect those failures (score ≤ 4 if expected tool was not used). "
            "Return a strict score from 1 to 10 and a brief justification."
        )

        try:
            evaluation: ScoreResult = await judge.extract_data(
                judge_prompt, ScoreResult
            )
        except Exception as e:
            # Fallback if judge extraction somehow fails
            evaluation = ScoreResult(score=1, reasoning=f"Judge crash: {e}")

        entry_result: dict[str, Any] = {
            "id": item["id"],
            "score": evaluation.score,
            "reasoning": evaluation.reasoning,
        }

        if item.get("tool_used"):
            entry_result["expected_tool"] = item["tool_used"]
            entry_result["actual_tools"] = sorted(tracker.tool_names)
            entry_result["tool_routing_ok"] = item["tool_used"] in tracker.tool_names

        results.append(entry_result)

        if console:
            color = (
                "green"
                if evaluation.score >= 8
                else "yellow"
                if evaluation.score >= 5
                else "red"
            )
            tool_info = ""
            if item.get("tool_used"):
                ok = entry_result.get("tool_routing_ok", True)
                tool_info = (
                    f" [tool={item['tool_used']} {'✓' if ok else '✗'}]"
                )
            console.print(
                f"[{color}]Score: {evaluation.score}/10{tool_info}[/{color}] - {evaluation.reasoning}"
            )

    # Print summary
    avg_score = sum(r["score"] for r in results) / len(results) if results else 0
    if console and Table:
        table = Table(title=f"Evaluation Summary (Avg: {avg_score:.1f}/10)")
        table.add_column("ID", style="cyan")
        table.add_column("Score", style="magenta")
        table.add_column("Tool", style="yellow")
        table.add_column("Routing")
        table.add_column("Reasoning")

        for r in results:
            tool_cell = r.get("expected_tool", "—")
            routing_cell = (
                "✓" if r.get("tool_routing_ok", True)
                else f"✗ got {r.get('actual_tools')}"
            )
            table.add_row(
                r["id"], str(r["score"]), tool_cell, routing_cell, r["reasoning"]
            )
        console.print(table)
    else:
        print(f"\nFinal Average Score: {avg_score:.1f}/10")

    return avg_score
