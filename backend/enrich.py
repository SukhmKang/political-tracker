"""
Entity enrichment agent — researches an entity via Exa and returns structured metadata.
"""

import asyncio
import json
import sys

from agents import Agent, ModelSettings, Runner

from search_tools import web_search, multi_search, opensecrets_search, propublica_search

_SEM = asyncio.Semaphore(5)


# ---------------------------------------------------------------------------
# Subagent output schema
# ---------------------------------------------------------------------------

_FACT_SCHEMA = """\
{
  "subagent": "<your name>",
  "facts": [
    {
      "field": "description|occupation|employer|political_party|office_held|mission|founded_year|jurisdiction",
      "value": "the extracted value as a plain string",
      "source_url": "the specific page this came from",
      "source_domain": "domain of source_url",
      "evidence_quote": "verbatim text from the source supporting this value"
    }
  ]
}"""

_NEWS_SCHEMA = """\
{
  "subagent": "news",
  "facts": [],
  "recent_news": [
    {
      "headline": "article title",
      "url": "article url",
      "date": "YYYY-MM-DD or null",
      "summary": "1-2 sentence summary of what happened"
    }
  ]
}"""

_RULES = """\
Rules:
- Only include a fact if you found an explicit source for it. Do not infer or guess.
- evidence_quote must be a verbatim excerpt from the source, not a paraphrase.
- source_url must be the specific article or page, not a homepage or search page.
- If nothing credible is found for a field, omit it entirely from facts.
- Return ONLY valid JSON — no preamble, no markdown fences."""


_SUBAGENTS = [
    (
        "bio",
        (
            "You are a political background researcher. Given an entity name, type, and state, "
            "use multi_search to run all your planned queries in parallel upfront: who this entity is, "
            "what they do (occupation for individuals/candidates, mission for organizations/committees/parties), "
            "who employs them (if individual), their political party affiliation, any office they hold or held, "
            "year founded (if org), and jurisdiction (if government entity). "
            "Include the state and entity type in your queries. "
            "Use web_search only for single follow-up queries on specific leads. "
            f"{_RULES}\n\nReturn this JSON:\n{_FACT_SCHEMA}"
        ),
        [multi_search, web_search],
    ),
    (
        "news",
        (
            "You are a political news researcher. Given an entity name, type, and state, "
            "use multi_search to run several news queries in parallel (try different phrasings and date ranges). "
            "Find 3-5 recent news articles (last 2 years) that are directly and specifically about this entity. "
            "The article must name the entity explicitly — do not include articles that merely cover related topics, "
            "adjacent people, or the same policy area without naming the entity itself. "
            "For PACs and committees, the article must mention the PAC or committee by name, not just the cause it supports. "
            "Focus on significant events: elections, investigations, major donations, leadership changes, controversies. "
            "Include the published date when available. "
            "If you cannot find articles that directly name the entity, return an empty recent_news array — do not substitute loosely related articles. "
            f"{_RULES}\n\nReturn this JSON:\n{_NEWS_SCHEMA}"
        ),
        [multi_search, web_search],
    ),
    (
        "political",
        (
            "You are a campaign finance profile researcher. Given an entity name, type, and state, "
            "use opensecrets_search and propublica_search to find their political profile: "
            "party affiliation, office held or sought, organizational mission, and any notable "
            "campaign finance context. "
            "Use multi_search when you have several independent web queries to run at once. "
            "Use web_search only for single follow-up queries on specific leads. "
            f"{_RULES}\n\nReturn this JSON:\n{_FACT_SCHEMA}"
        ),
        [opensecrets_search, propublica_search, multi_search, web_search],
    ),
]


# ---------------------------------------------------------------------------
# Synthesizer
# ---------------------------------------------------------------------------

_ENTITY_TYPE_FIELDS = {
    "individual":   ["description", "occupation", "employer", "political_party"],
    "candidate":    ["description", "occupation", "political_party", "office_held"],
    "committee":    ["description", "mission", "political_party"],
    "organization": ["description", "mission", "founded_year"],
    "party":        ["description", "mission"],
    "government":   ["description", "office_held", "jurisdiction"],
}

_OUTPUT_SCHEMA = """\
{
  "description": "string or null",
  "occupation": "string or null",
  "employer": "string or null",
  "political_party": "string or null",
  "office_held": "string or null",
  "mission": "string or null",
  "founded_year": "string or null",
  "jurisdiction": "string or null",
  "recent_news": [
    {"headline": "...", "url": "...", "date": "YYYY-MM-DD or null", "summary": "..."}
  ],
  "sources": [
    {"url": "...", "domain": "...", "used_for": "which field this source informed"}
  ]
}"""

_SYNTHESIZER_INSTRUCTIONS = """\
You are a political data synthesizer. You receive research outputs from 3 subagents about a specific entity.

Your job:
1. For each metadata field, pick the best-supported value. Prefer values with verbatim evidence_quotes over paraphrases.
2. Only populate fields that are relevant to the entity type (provided in the prompt). Set irrelevant fields to null.
3. Deduplicate sources — include each URL once in the sources array, noting which field it informed.
4. For recent_news, merge all articles from subagents, deduplicate by URL, keep the 5 most recent/significant. Discard any article that does not explicitly name the entity — articles about related topics, adjacent people, or the same policy area without naming the entity are not acceptable.
5. If no credible value was found for a field, set it to null.
6. description should be 2-3 sentences written in dry, factual AP wire style. State concrete facts: role, office, state, party, notable actions. No filler — ban phrases like "known for", "significant contributions", "prominent figure", "dedicated to", "making an impact", "plays a key role", or any other vague superlatives. If you don't have a concrete fact to fill a sentence, write fewer sentences.

Return ONLY valid JSON — no preamble, no markdown fences:\n""" + _OUTPUT_SCHEMA


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------

def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        inner = lines[1:] if lines[-1].strip() == "```" else lines[1:]
        raw = "\n".join(inner).strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()
    return raw


async def _run_subagent(
    name: str,
    instructions: str,
    tools: list,
    entity_name: str,
    entity_type: str,
    state: str | None,
) -> dict:
    _EMPTY = {"subagent": name, "facts": [], "recent_news": []}
    try:
        async with _SEM:
            agent = Agent(
                name=name,
                model="gpt-4o-mini",
                model_settings=ModelSettings(parallel_tool_calls=True),
                instructions=instructions,
                tools=tools,
            )
            prompt = (
                f"Entity name: {entity_name}\n"
                f"Entity type: {entity_type}\n"
                f"State: {state or 'unknown'}"
            )
            result = await Runner.run(agent, prompt, max_turns=8)
        raw = _strip_fences(result.final_output)
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f"  [!] {name}: JSON parse failed — {raw}", file=sys.stderr)
        return _EMPTY
    except Exception as exc:
        print(f"  [!] {name}: failed ({type(exc).__name__}: {exc})", file=sys.stderr)
        return _EMPTY


async def _synthesize(
    entity_name: str,
    entity_type: str,
    state: str | None,
    subagent_results: list[dict],
) -> dict:
    relevant_fields = _ENTITY_TYPE_FIELDS.get(entity_type, ["description"])
    combined = json.dumps(subagent_results, indent=2)
    agent = Agent(
        name="synthesizer",
        model="gpt-4o",
        model_settings=ModelSettings(parallel_tool_calls=False),
        instructions=_SYNTHESIZER_INSTRUCTIONS,
    )
    prompt = (
        f"Entity: {entity_name}\n"
        f"Entity type: {entity_type}\n"
        f"State: {state or 'unknown'}\n"
        f"Relevant fields for this entity type: {', '.join(relevant_fields)}\n\n"
        f"Subagent outputs:\n{combined}"
    )
    result = await Runner.run(agent, prompt, max_turns=2)
    raw = _strip_fences(result.final_output)
    return json.loads(raw)


async def enrich_entity(
    entity_name: str,
    entity_type: str,
    state: str | None,
) -> dict:
    print(f"[*] Enriching '{entity_name}' (type={entity_type}, state={state})", file=sys.stderr)

    tasks = [
        _run_subagent(name, instructions, tools, entity_name, entity_type, state)
        for name, instructions, tools in _SUBAGENTS
    ]
    subagent_results = await asyncio.gather(*tasks)

    useful = [r for r in subagent_results if r.get("facts") or r.get("recent_news")]
    if not useful:
        raise RuntimeError("All subagents failed — no data available to synthesize")

    result = await _synthesize(entity_name, entity_type, state, list(subagent_results))
    print(f"[+] Enrichment complete for '{entity_name}'", file=sys.stderr)
    return result
