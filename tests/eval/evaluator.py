"""LLM-as-a-judge evaluation harness for Vibe AI."""

import json
from pydantic import BaseModel, Field

from src.agentframework.agent import AgentConfig, create_agent

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
    score: int = Field(..., description="An integer from 1 to 10 representing how well the agent accomplished the expected behavior.")
    reasoning: str = Field(..., description="A short explanation validating the score.")

async def evaluate_dataset(dataset_path: str, agent_config: AgentConfig) -> float:
    """Run the evaluation dataset against the provided agent configuration."""
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    # Use a separate judge agent strictly for extraction.
    # Use Ollama locally so we don't require an OpenAI API Key
    judge_config = AgentConfig(provider="ollama", model="qwen3:4b-instruct", session_enabled=False)
    judge = create_agent(judge_config, api_key="dummy_judge_key")

    results = []

    for item in dataset:
        prompt = item["prompt"]
        expected = item["expected_behavior"]

        # Spawn a fresh agent for each iteration to avoid memory bleed
        agent = create_agent(agent_config)

        if console:
            console.print(f"\n[bold cyan]Evaluating [{item['id']}][/bold cyan]: {prompt}")
        else:
            print(f"\nEvaluating [{item['id']}]: {prompt}")

        try:
            actual_response = await agent.run(prompt)
        except Exception as e:
            actual_response = f"AGENT CRASHED: {e}"

        judge_prompt = (
            "You are an expert AI evaluator grading another agent's performance.\n"
            f"User Prompt: {prompt}\n"
            f"Expected Behavior: {expected}\n"
            f"Actual Response: {actual_response}\n\n"
            "Evaluate if the Actual Response successfully meets the Expected Behavior. "
            "Return a strict score from 1 to 10 and a brief justification."
        )

        try:
            evaluation: ScoreResult = await judge.extract_data(judge_prompt, ScoreResult)
        except Exception as e:
            # Fallback if judge extraction somehow fails
            evaluation = ScoreResult(score=1, reasoning=f"Judge crash: {e}")

        results.append({
            "id": item["id"],
            "score": evaluation.score,
            "reasoning": evaluation.reasoning,
        })

        if console:
            color = "green" if evaluation.score >= 8 else "yellow" if evaluation.score >= 5 else "red"
            console.print(f"[{color}]Score: {evaluation.score}/10[/{color}] - {evaluation.reasoning}")

    # Print summary
    avg_score = sum(r["score"] for r in results) / len(results) if results else 0
    if console and Table:
        table = Table(title=f"Evaluation Summary (Avg: {avg_score:.1f}/10)")
        table.add_column("ID", style="cyan")
        table.add_column("Score", style="magenta")
        table.add_column("Reasoning")

        for r in results:
            table.add_row(r["id"], str(r["score"]), r["reasoning"])
        console.print(table)
    else:
        print(f"\nFinal Average Score: {avg_score:.1f}/10")

    return avg_score
