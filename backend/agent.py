#!/usr/bin/env python3
"""
Political influence discovery pipeline.
Usage: python agent.py "Koch Industries"
Prints unified JSON to stdout; progress messages go to stderr.
"""

import argparse
import asyncio
import json
import os
import sys
import traceback

from agents import Agent, ModelSettings, Runner, trace
from anthropic import AsyncAnthropic

from search_tools import exa_search, multi_search, web_search

_SEM = asyncio.Semaphore(6)


# ---------------------------------------------------------------------------
# Schemas and instructions
# ---------------------------------------------------------------------------

_CONNECTION_SCHEMA = """\
{
  "subagent": "<your name>",
  "connections": [
    {
      "target_name": "string",
      "target_type": "individual|organization|committee|pac|nonprofit",
      "relationship_type": "One plain sentence describing the relationship, e.g. 'John Smith serves as treasurer of Empower Texans PAC.'",
      "evidence_quote": "verbatim text from the source page supporting this connection",
      "source_url": "the page containing the evidence_quote — not a search page or homepage",
      "source_domain": "domain of source_url",
      "evidence_strength": "direct|indirect|weak",
      "notes": "optional context or caveats"
    }
  ]
}"""

_EXTRACTION_RULES = """\
Extraction rules — apply strictly:
- Only extract a connection if the source explicitly names the relationship. Do not infer affiliation from donations, co-mentions, ideological alignment, or shared issue areas.
- Do not output attributes (industry, ideology, location, description, entity type) as connections. Only output relationships between two distinctly named real-world entities — a person, organization, PAC, committee, or company. target_name must be the proper name of such an entity, never an address, descriptor, attribute, or concept.
- Campaign contributions alone do not establish affiliation, control, employment, or sponsorship.
- evidence_quote must be a verbatim excerpt from the source page, not a paraphrase.
- source_url must be the specific page containing the evidence_quote.
- Return an empty connections array if no explicit relationship is found. Do not guess."""

_EXA_SEARCH_GUIDANCE = """\
Search guidance:
- web_search and multi_search use Exa neural search, not Google-style keyword search. Write natural-language queries that describe the evidence you want to find.
- Prefer longer, specific phrases such as "records showing <entity> board members officers trustees political committee" over Boolean strings.
- Do not use Google operators like site:, OR, quotes-for-exact-match, plus/minus operators, or parenthesized Boolean syntax.
- For deterministic OpenSecrets, FEC, InfluenceWatch, and ProPublica results, assume those domains have already been searched separately.
- Vary intent across parallel queries: official filings, named officers, treasurer registrations, parent/subsidiary relationships, grants, 990s, and direct relationship evidence."""

_ENTITY_TRIAGE_GUIDANCE = """\
Entity triage before searching:
- First infer from the name whether the seed is most likely an individual person, organization, PAC/committee, company, nonprofit, or too ambiguous.
- If the seed is an individual person, do not search for who founded them, what organization sponsors them, registered agents, parent companies, subsidiaries, or 990 mission statements. Search for explicit roles instead: employer, campaign/committee office, treasurer role, board membership, organizational leadership, official biography, or named affiliation.
- If the seed is an organization, PAC, committee, company, or nonprofit, search for founders, officers, treasurers, sponsors/funders, parent/subsidiary relationships, board members, filings, and mission where relevant.
- If the seed name is too generic to narrow to a specific real-world entity, or could refer to many unrelated people/organizations, return an empty connections array instead of guessing. Do not search broad generic names unless a unique political/organizational identity is clear from the name itself.
- Tailor every query to the inferred entity type. Avoid person-nonsense queries like "who founded <person>" and org-nonsense queries like "<organization> employer biography"."""

_NEURAL_RESEARCHER_INSTRUCTIONS = (
    "You are the only exploratory web research agent in this pipeline. "
    "Use Exa neural search to look for explicit relationships involving the seed entity. "
    "Do not duplicate deterministic searches for OpenSecrets, FEC, InfluenceWatch, or ProPublica unless a specific lead requires follow-up. "
    "Use at most one multi_search call with up to 4 natural-language queries, then at most one web_search follow-up if needed. "
    "Prefer official pages, filings, biographies, staff pages, board/officer pages, news articles, and pages with direct evidence.\n\n"
    f"{_ENTITY_TRIAGE_GUIDANCE}\n\n"
    f"{_EXA_SEARCH_GUIDANCE}\n\n"
    f"{_EXTRACTION_RULES}\n\n"
    f"Return ONLY valid JSON — no preamble, no markdown fences:\n{_CONNECTION_SCHEMA}"
)

_DETERMINISTIC_SEARCHES: list[tuple[str, str, list[str], bool]] = [
    (
        "opensecrets",
        "{entity} donor network PAC committee campaign finance relationships",
        ["opensecrets.org"],
        False,
    ),
    (
        "fec",
        "{entity} committee treasurer statement of organization federal filing",
        ["fec.gov"],
        False,
    ),
    (
        "influencewatch",
        "{entity} nonprofit affiliations donors officers political network",
        ["influencewatch.org"],
        False,
    ),
    (
        "propublica",
        "{entity} nonprofit 990 officers grants revenue political activity",
        ["propublica.org"],
        False,
    ),
]

_SYNTHESIZER_INSTRUCTIONS = f"""\
You are a political influence analyst. You receive raw deterministic search results plus one neural researcher JSON output.

Your job:
1. Read deterministic source results and the neural researcher output.
2. Extract only explicit relationships between two distinctly named real-world entities.
3. Deduplicate by target_name, merging evidence across deterministic and neural sources.
4. Preserve verbatim evidence quotes from source result highlights when possible. If a highlight does not support an explicit relationship, discard it.
5. Do not infer relationships from donations, co-mentions, ideological alignment, shared location, or generic descriptions.
6. Discard targets that are addresses, topics, attributes, office titles, generic descriptors, or ambiguous non-entities.
7. Set evidence_strength to "direct" only when a source directly states the relationship; use "indirect" or "weak" sparingly and only with explicit evidence.
8. Add suggested_expansions with up to 5 proper named entities worth investigating next. Exclude the seed entity itself.

{_ENTITY_TRIAGE_GUIDANCE}

Return ONLY valid JSON — no preamble, no markdown fences:
{{
  "entity": "<seed entity name>",
  "connections": [
    {{
      "target_name": "string",
      "target_type": "individual|organization|committee|pac|nonprofit",
      "relationship_type": "One plain sentence describing the relationship.",
      "evidence_quotes": ["verbatim quote 1", "verbatim quote 2"],
      "source_urls": ["url1", "url2"],
      "source_domains": ["domain1", "domain2"],
      "evidence_strength": "direct|indirect|weak",
      "found_by": ["deterministic:opensecrets", "neural"]
    }}
  ],
  "suggested_expansions": ["Entity A", "Entity B"]
}}"""

_NEURAL_EMPTY = {"subagent": "neural", "connections": []}


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


async def _run_deterministic_search(
    source: str,
    query_template: str,
    domains: list[str],
    neural: bool,
    entity: str,
) -> dict:
    query = query_template.format(entity=entity)
    try:
        result = await asyncio.to_thread(exa_search, query, 4, domains, neural)
        return {"source": source, "query": query, "error": None, "results": result}
    except Exception as exc:
        print(f"  [!] deterministic:{source} failed for {entity!r} ({type(exc).__name__}: {exc})", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return {"source": source, "query": query, "error": f"{type(exc).__name__}: {exc}", "results": ""}


async def _run_deterministic_searches(entity: str) -> list[dict]:
    print(f"  [*] Running {len(_DETERMINISTIC_SEARCHES)} deterministic searches for '{entity}'", file=sys.stderr)
    results = await asyncio.gather(*[
        _run_deterministic_search(source, query_template, domains, neural, entity)
        for source, query_template, domains, neural in _DETERMINISTIC_SEARCHES
    ])
    failures = sum(1 for result in results if result.get("error"))
    print(
        f"  [+] Deterministic searches complete for '{entity}' ({len(results) - failures} ok, {failures} failed)",
        file=sys.stderr,
    )
    return list(results)


async def _run_neural_researcher(entity: str) -> dict:
    try:
        async with _SEM:
            agent = Agent(
                name="neural_researcher",
                model="gpt-5-mini",
                model_settings=ModelSettings(reasoning={"effort": "low"}, parallel_tool_calls=True, max_tokens=4096),
                instructions=_NEURAL_RESEARCHER_INSTRUCTIONS,
                tools=[multi_search, web_search],
            )
            result = await Runner.run(agent, f"Find explicit connections for: {entity}", max_turns=6)
        raw = _strip_fences(result.final_output)
        parsed = json.loads(raw)
        parsed["subagent"] = "neural"
        return parsed
    except json.JSONDecodeError:
        print(f"  [!] neural: JSON parse failed — {raw}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return _NEURAL_EMPTY
    except Exception as exc:
        print(f"  [!] neural: failed ({type(exc).__name__}: {exc})", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return _NEURAL_EMPTY


async def _synthesize(entity: str, deterministic_results: list[dict], neural_result: dict) -> dict:
    combined = json.dumps(
        {
            "deterministic_searches": deterministic_results,
            "neural_researcher": neural_result,
        },
        indent=2,
    )
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for discovery synthesis")

    client = AsyncAnthropic(api_key=api_key)
    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=_SYNTHESIZER_INSTRUCTIONS,
        messages=[
            {
                "role": "user",
                "content": f"Entity: {entity}\n\nResearch inputs:\n{combined}",
            }
        ],
    )
    raw = _strip_fences(
        "\n".join(
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
        )
    )
    return json.loads(raw)


async def _scan_entity(entity: str) -> dict:
    print(f"  [*] Scanning '{entity}' with deterministic searches + one neural researcher", file=sys.stderr)
    deterministic_task = asyncio.create_task(_run_deterministic_searches(entity))
    neural_task = asyncio.create_task(_run_neural_researcher(entity))
    deterministic_results, neural_result = await asyncio.gather(deterministic_task, neural_task)

    try:
        result = await _synthesize(entity, deterministic_results, neural_result)
    except json.JSONDecodeError:
        print(f"  [!] synthesizer: JSON parse failed for '{entity}'", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return {"entity": entity, "connections": [], "suggested_expansions": []}
    except Exception as exc:
        print(f"  [!] synthesizer: failed for '{entity}' ({type(exc).__name__}: {exc})", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return {"entity": entity, "connections": [], "suggested_expansions": []}

    n = len(result.get("connections", []))
    expansions = result.get("suggested_expansions", [])
    print(f"  [+] '{entity}': {n} connection(s), {len(expansions)} suggested expansion(s)", file=sys.stderr)
    return result


async def main(entity: str, depth: int, max_expand: int) -> dict:
    print(
        f"[*] Starting: '{entity}'  depth={depth}  max_expand={max_expand}",
        file=sys.stderr,
    )

    visited: set[str] = {entity.lower()}
    queue: list[str] = [entity]
    all_results: list[dict] = []
    depth_reached = 0

    with trace("Political influence discovery"):
        for current_depth in range(1, depth + 1):
            if not queue:
                break
            depth_reached = current_depth
            print(f"\n[*] Depth {current_depth} — {len(queue)} node(s) to scan", file=sys.stderr)

            depth_results: list[dict] = await asyncio.gather(
                *[_scan_entity(e) for e in queue]
            )

            next_queue: list[str] = []
            for result in depth_results:
                for conn in result.get("connections", []):
                    conn["depth"] = current_depth
                    conn["found_from"] = result.get("entity", entity)
                all_results.append(result)

                for candidate in result.get("suggested_expansions", []):
                    if candidate.lower() not in visited and len(next_queue) < max_expand:
                        visited.add(candidate.lower())
                        next_queue.append(candidate)

            queue = next_queue
            if not queue:
                print(f"[*] No interesting expansions at depth {current_depth}, stopping early.", file=sys.stderr)
                break

    all_connections = [
        conn
        for result in all_results
        for conn in result.get("connections", [])
    ]

    return {
        "seed_entity": entity,
        "depth_reached": depth_reached,
        "nodes_scanned": [r.get("entity", "") for r in all_results],
        "connections": all_connections,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Political influence discovery")
    parser.add_argument("entity", nargs="+", help="Seed entity name")
    parser.add_argument("--depth", type=int, default=1, help="Hops to explore (default: 1)")
    parser.add_argument("--max-expand", type=int, default=3, help="Max nodes to expand per depth level (default: 3)")
    args = parser.parse_args()
    result = asyncio.run(main(" ".join(args.entity), args.depth, args.max_expand))
    print(json.dumps(result, indent=2))
