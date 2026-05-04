"""
Lightweight entity enrichment pipeline.
"""

import asyncio
import json
import sys
import traceback

from agents import Agent, ModelSettings, Runner

from search_tools import exa_search


# ---------------------------------------------------------------------------
# Synthesis schema and instructions
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
You are a political data synthesizer. You receive raw Exa search results about a specific entity.

Your job:
1. Extract only explicitly sourced facts. Do not infer or guess.
2. Only populate fields relevant to the entity type provided in the prompt. Set irrelevant fields to null.
3. Use result highlights as evidence. If a highlight does not explicitly support a field, ignore it.
4. Deduplicate sources. Include each URL once in the sources array, noting which field it informed.
5. For recent_news, keep at most 3 significant articles from the last 2 years when available. Discard articles that do not explicitly name the entity.
6. If no credible value was found for a field, set it to null.
7. description should be 1-2 dry, factual sentences. State concrete facts: role, office, state, party, notable actions. Avoid vague superlatives and filler.
8. Use the disambiguation hints only to identify the correct real-world entity. Do not invent facts from hints alone.
9. If search results appear to describe a different person or organization than the hints/state/entity type, discard those results.
10. If the name cannot be confidently disambiguated, return the schema with all scalar fields null, recent_news [], and sources []. Do not enrich the wrong entity.

Return ONLY valid JSON — no preamble, no markdown fences:
""" + _OUTPUT_SCHEMA

_DETERMINISTIC_SEARCHES: list[tuple[str, str, list[str] | None, bool]] = [
    (
        "background",
        "{entity} {state} {entity_type} official biography leadership mission political profile",
        None,
        True,
    ),
    (
        "recent_news",
        "{entity} {state} recent news election investigation leadership donation",
        None,
        True,
    ),
    (
        "opensecrets",
        "{entity} {state} political profile campaign finance",
        ["opensecrets.org"],
        False,
    ),
    (
        "propublica",
        "{entity} {state} nonprofit 990 officers mission revenue",
        ["propublica.org"],
        False,
    ),
]


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


def _format_query(template: str, entity_name: str, entity_type: str, state: str | None) -> str:
    return template.format(
        entity=entity_name,
        entity_type=entity_type,
        state=state or "",
    ).replace("  ", " ").strip()


async def _run_search(
    source: str,
    query_template: str,
    domains: list[str] | None,
    neural: bool,
    entity_name: str,
    entity_type: str,
    state: str | None,
) -> dict:
    query = _format_query(query_template, entity_name, entity_type, state)
    try:
        result = await asyncio.to_thread(exa_search, query, 4, domains, neural)
        return {"source": source, "query": query, "error": None, "results": result}
    except Exception as exc:
        print(f"  [!] enrichment:{source} failed for {entity_name!r} ({type(exc).__name__}: {exc})", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return {"source": source, "query": query, "error": f"{type(exc).__name__}: {exc}", "results": ""}


async def _run_searches(entity_name: str, entity_type: str, state: str | None) -> list[dict]:
    print(f"  [*] Running {len(_DETERMINISTIC_SEARCHES)} enrichment searches for '{entity_name}'", file=sys.stderr)
    results = await asyncio.gather(*[
        _run_search(source, query_template, domains, neural, entity_name, entity_type, state)
        for source, query_template, domains, neural in _DETERMINISTIC_SEARCHES
    ])
    failures = sum(1 for result in results if result.get("error"))
    print(
        f"  [+] Enrichment searches complete for '{entity_name}' ({len(results) - failures} ok, {failures} failed)",
        file=sys.stderr,
    )
    return list(results)


async def _synthesize(
    entity_name: str,
    entity_type: str,
    state: str | None,
    hints: dict,
    search_results: list[dict],
) -> dict:
    relevant_fields = _ENTITY_TYPE_FIELDS.get(entity_type, ["description"])
    combined = json.dumps(search_results, indent=2)
    agent = Agent(
        name="enrichment_synthesizer",
        model="gpt-4o-mini",
        model_settings=ModelSettings(parallel_tool_calls=False),
        instructions=_SYNTHESIZER_INSTRUCTIONS,
    )
    prompt = (
        f"Entity: {entity_name}\n"
        f"Entity type: {entity_type}\n"
        f"State: {state or 'unknown'}\n"
        f"Relevant fields for this entity type: {', '.join(relevant_fields)}\n\n"
        f"Disambiguation hints: {json.dumps(hints, indent=2)}\n\n"
        f"Search results:\n{combined}"
    )
    result = await Runner.run(agent, prompt, max_turns=2)
    raw = _strip_fences(result.final_output)
    return json.loads(raw)


async def enrich_entity(
    entity_name: str,
    entity_type: str,
    state: str | None,
    hints: dict | None = None,
) -> dict:
    print(f"[*] Enriching '{entity_name}' (type={entity_type}, state={state})", file=sys.stderr)
    hints = hints or {"connected_entities": [], "source_domains": []}

    search_results = await _run_searches(entity_name, entity_type, state)
    if not any(result.get("results") and not result.get("error") for result in search_results):
        raise RuntimeError("All enrichment searches failed — no data available to synthesize")

    result = await _synthesize(entity_name, entity_type, state, hints, search_results)
    print(f"[+] Enrichment complete for '{entity_name}'", file=sys.stderr)
    return result
