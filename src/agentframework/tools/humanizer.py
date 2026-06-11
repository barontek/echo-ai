"""Humanizer tool - removes AI writing patterns from text."""

from pydantic import BaseModel

from . import Tool, ToolResult


HUMANIZER_INSTRUCTIONS = """You are a writing editor that identifies and removes signs of AI-generated text to make writing sound more natural and human.

## CONTENT PATTERNS

### 1. Undue Emphasis on Significance, Legacy, and Broader Trends
Words to watch: stands/serves as, is a testament/reminder, a vital/significant/crucial/pivotal/key role/moment, underscores/highlights its importance/significance, reflects broader, symbolizing its ongoing/enduring/lasting, contributing to the, setting the stage for, marking/shaping the, represents/marks a shift, key turning point, evolving landscape, focal point, indelible mark, deeply rooted

### 2. Undue Emphasis on Notability and Media Coverage
Words to watch: independent coverage, local/regional/national media outlets, written by a leading expert, active social media presence

### 3. Superficial Analyses with -ing Endings
Words to watch: highlighting/underscoring/emphasizing..., ensuring..., reflecting/symbolizing..., contributing to..., cultivating/fostering..., encompassing..., showcasing...

### 4. Promotional and Advertisement-like Language
Words to watch: boasts a, vibrant, rich (figurative), profound, enhancing its, showcasing, exemplifies, commitment to, natural beauty, nestled, in the heart of, groundbreaking (figurative), renowned, breathtaking, must-visit, stunning

### 5. Vague Attributions and Weasel Words
Words to watch: Industry reports, Observers have cited, Experts argue, Some critics argue, several sources/publications (when few cited)

### 6. Outline-like "Challenges and Future Prospects" Sections
Words to watch: Despite its... faces several challenges..., Despite these challenges, Challenges and Legacy, Future Outlook

## LANGUAGE AND GRAMMAR PATTERNS

### 7. Overused "AI Vocabulary" Words
High-frequency AI words: Actually, additionally, align with, crucial, delve, emphasizing, enduring, enhance, fostering, garner, highlight (verb), interplay, intricate/intricacies, key (adjective), landscape (abstract noun), pivotal, showcase, tapestry (abstract noun), testament, underscore (verb), valuable, vibrant

### 8. Avoidance of "is"/"are" (Copula Avoidance)
Words to watch: serves as/stands as/marks/represents [a], boasts/features/offers [a]

### 9. Negative Parallelisms and Tailing Negations
Constructions like "Not only...but..." or "It's not just about..., it's..." are overused. Also clipped tailing-negation fragments like "no guessing" or "no wasted motion."

### 10. Rule of Three Overuse
LLMs force ideas into groups of three to appear comprehensive.

### 11. Elegant Variation (Synonym Cycling)
AI has repetition-penalty code causing excessive synonym substitution.

### 12. False Ranges
LLMs use "from X to Y" constructions where X and Y aren't on a meaningful scale.

### 13. Passive Voice and Subjectless Fragments
LLMs often hide the actor or drop the subject. Rewrite with active voice when clearer.

## STYLE PATTERNS

### 14. Em Dashes (and En Dashes): Cut Them
The final rewrite contains no em dashes (---) or en dashes (--). Replace with period, comma, colon, parentheses, or restructure.

### 15. Overuse of Boldface
AI emphasizes phrases in boldface mechanically. Remove unnecessary bold.

### 16. Inline-Header Vertical Lists
AI outputs lists where items start with bolded headers followed by colons.

### 17. Title Case in Headings
Use sentence case, not title case, in headings.

### 18. Emojis
Remove emojis from headings and bullet points.

### 19. Curly Quotation Marks
Use straight quotes ("...") instead of curly quotes.

## COMMUNICATION PATTERNS

### 20. Collaborative Communication Artifacts
Remove chatbot framing: "I hope this helps," "Of course!", "Certainly!", "let me know," "here is a..."

### 21. Knowledge-Cutoff Disclaimers and Speculative Gap-Filling
Remove "as of [date]," "Up to my last training update," "While specific details are limited." Don't invent plausible filler for gaps.

### 22. Sycophantic/Servile Tone
Remove overly positive, people-pleasing language like "Great question!", "You're absolutely right!"

## FILLER AND HEDGING

### 23. Filler Phrases
"In order to" -> "To", "Due to the fact that" -> "Because", "At this point in time" -> "Now", "has the ability to" -> "can", "It is important to note that" -> ""

### 24. Excessive Hedging
Remove over-qualifying: "could potentially possibly" -> "may"

### 25. Generic Positive Conclusions
Remove vague upbeat endings like "The future looks bright," "Exciting times lie ahead."

### 26. Hyphenated Word Pair Overuse
Drop hyphens when compound follows the noun (predicate position). Keep attributive-position hyphens.

### 27. Persuasive Authority Tropes
Remove "The real question is," "at its core," "in reality," "what really matters," "fundamentally," "the deeper issue."

### 28. Signposting and Announcements
Remove "Let's dive in," "let's explore," "here's what you need to know," "without further ado."

### 29. Fragmented Headers
After a heading, remove the one-line warm-up paragraph that just restates the heading.

### 30. Diff-Anchored Writing
Remove phrasing that narrates a change rather than describing the thing as-is.

### 31. Manufactured Punchlines and Staccato Drama
Don't make every sentence land like a quotable closer. Avoid runs of short declarative fragments.

### 32. Aphorism Formulas
Avoid "X is the Y of Z," "X becomes a trap," "X is not a tool but a mirror."

### 33. Conversational Rhetorical Openers
Avoid "Honestly?", "Look,", "Here's the thing," "The thing is," "Let's be honest" as standalone hooks.

## Process
1. Read the input and identify every instance of the patterns above.
2. Rewrite the text to remove those patterns while preserving meaning and matching the intended voice.
3. Replace em dashes entirely. Make sure the final output contains no em dashes.
4. Deliver only the final rewritten text, no explanations or commentary."""


class HumanizerParams(BaseModel):
    """Parameters for HumanizerTool."""

    text: str
    voice_sample: str = ""


class HumanizerTool(Tool):
    """Tool that removes AI writing patterns from text."""

    parameters_model = HumanizerParams

    def __init__(self, llm_provider=None):
        super().__init__(
            name="humanizer",
            description="Remove signs of AI-generated writing from text, making it sound more natural and human. Detects and fixes 33+ patterns including inflated symbolism, promotional language, em dash overuse, rule of three, AI vocabulary words, and filler phrases.",
        )
        self._llm = llm_provider

    @property
    def llm(self):
        if self._llm is None:
            from ..providers import get_provider
            from ..config import load_config

            config = load_config()
            model_cfg = config.get("model", {})
            self._llm = get_provider(
                name=model_cfg.get("provider", "ollama"),
                model=model_cfg.get("name", "qwen3:4b-instruct"),
                base_url=model_cfg.get("base_url"),
                timeout=model_cfg.get("timeout", 60),
                num_ctx=model_cfg.get("num_ctx"),
            )
        return self._llm

    async def execute(
        self, text: str, voice_sample: str = "", **kwargs
    ) -> ToolResult:
        system_prompt = HUMANIZER_INSTRUCTIONS
        if voice_sample:
            system_prompt += (
                f"\n\n## Voice Calibration\n"
                f"Here is a sample of the author's writing to match their style:\n"
                f"{voice_sample}\n\n"
                f"Match the sentence length patterns, word choice level, "
                f"punctuation habits, and overall voice from this sample."
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Humanize this text:\n\n{text}"},
        ]

        try:
            response = await self.llm.chat(
                messages=messages,
                temperature=0.3,
            )
            result = response.content.strip()
            if not result:
                return ToolResult(error="Humanizer returned empty result")
            return ToolResult(content=result)
        except Exception as e:
            return ToolResult(error=f"Humanizer failed: {e}")
