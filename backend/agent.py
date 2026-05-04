#!/usr/bin/env python3
"""
Parallel political influence discovery system.
Usage: python agent.py "Koch Industries"
Prints unified JSON to stdout; progress messages go to stderr.
"""

import argparse
import asyncio
import json
import sys

from agents import Agent, ModelSettings, Runner, trace

from search_tools import (
    web_search, multi_search,
    opensecrets_search, fec_search, influencewatch_search, propublica_search,
)

_SEM = asyncio.Semaphore(10)  # max concurrent agent calls


# ---------------------------------------------------------------------------
# Agent configs: (name, instructions, tools)
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
- Only extract a connection if the source explicitly names the relationship. \
Do not infer affiliation from donations, co-mentions, ideological alignment, or shared issue areas.
- Do not output attributes (industry, ideology, location, description, entity type) as connections. \
Only output relationships between two distinctly named real-world entities — a person, organization, PAC, committee, or company. \
target_name must be the proper name of such an entity, never an address, descriptor, attribute, or concept.
- Campaign contributions alone do not establish affiliation, control, employment, or sponsorship.
- evidence_quote must be a verbatim excerpt from the source page, not a paraphrase.
- source_url must be the specific page containing the evidence_quote.
- Return an empty connections array if no explicit relationship is found. Do not guess."""

_JSON_INSTRUCTION = (
    f"{_EXTRACTION_RULES}\n\n"
    f"Return ONLY valid JSON — no preamble, no markdown fences:\n{_CONNECTION_SCHEMA}"
)

_SUBAGENTS: list[tuple[str, str, list]] = [
    (
        "opensecrets",
        (
            "You are a campaign finance researcher. "
            "Use opensecrets_search to find donor networks and PAC relationships for the given entity. "
            "Use multi_search when you have several independent web queries to run at once. "
            "Use web_search only for single follow-up queries on specific leads. "
            + _JSON_INSTRUCTION
        ),
        [opensecrets_search, multi_search, web_search],
    ),
    (
        "fec",
        (
            "You are a federal elections researcher. "
            "Use fec_search to find committee registrations, treasurer names, and federal filings for the given entity. "
            "Use multi_search when you have several independent web queries to run at once. "
            "Use web_search only for single follow-up queries on specific leads. "
            + _JSON_INSTRUCTION
        ),
        [fec_search, multi_search, web_search],
    ),
    (
        "influencewatch",
        (
            "You are a dark money and nonprofit network researcher. "
            "Use influencewatch_search to find dark money connections and nonprofit affiliations for the given entity. "
            "Use multi_search when you have several independent web queries to run at once. "
            "Use web_search only for single follow-up queries on specific leads. "
            + _JSON_INSTRUCTION
        ),
        [influencewatch_search, multi_search, web_search],
    ),
    (
        "officers",
        (
            "You are a corporate records researcher. "
            "Use multi_search to run all your planned queries for board members, officers, registered agents, "
            "and trustees in parallel. Use web_search only for single follow-up queries. "
            + _JSON_INSTRUCTION
        ),
        [multi_search, web_search],
    ),
    (
        "funders",
        (
            "You are a financial sponsorship researcher. "
            "Use multi_search to run all your planned queries for funders, grants, and sponsors in parallel. "
            "A grant agreement, funding announcement, or 990 line item naming the entity is required. "
            "Use web_search only for single follow-up queries. "
            + _JSON_INSTRUCTION
        ),
        [multi_search, web_search],
    ),
    (
        "news",
        (
            "You are a media relationship researcher. "
            "Use multi_search to run all your planned queries in parallel. "
            "Find news articles where a source explicitly describes a formal relationship "
            "(e.g. 'X is a subsidiary of Y', 'X employs Y as treasurer', 'X was founded by Y'). "
            "Do not extract relationships implied only by co-mention or ideological framing. "
            + _JSON_INSTRUCTION
        ),
        [multi_search, web_search],
    ),
    (
        "corporate",
        (
            "You are a corporate structure researcher. "
            "Use multi_search to run all your planned queries for parent companies, subsidiaries, LLCs, "
            "and shell company relationships in parallel. "
            "Registration filings, official disclosures, or signed agreements are required. "
            "Use web_search only for single follow-up queries. "
            + _JSON_INSTRUCTION
        ),
        [multi_search, web_search],
    ),
    (
        "propublica",
        (
            "You are a nonprofit and investigative research specialist focused on ProPublica. "
            "Use propublica_search to find 990 filings, executive compensation records, nonprofit revenue sources, "
            "and investigative reporting that explicitly names a relationship between the given entity "
            "and political actors or dark money networks. "
            "Use multi_search when you have several independent web queries to run at once. "
            "Use web_search only for single follow-up queries on specific leads. "
            + _JSON_INSTRUCTION
        ),
        [propublica_search, multi_search, web_search],
    ),
]

# ---------------------------------------------------------------------------
# Synthesizer
# ---------------------------------------------------------------------------

_SYNTHESIZER_INSTRUCTIONS = """\
You are a political influence analyst. You receive JSON outputs from 8 research subagents.

Deduplication and merging rules:
1. Group connections by target_name (case-insensitive). Merge records for the same target.
2. Merge all evidence_quotes into a list and all source_urls into a list.
3. Set evidence_strength to "direct" only if 2 or more DISTINCT source_domains independently \
support the relationship with direct evidence. Otherwise keep the strongest individual rating.
4. Be skeptical of single-source claims from the funders, news, and corporate subagents — \
these are most prone to inferring relationships from weak co-mentions. Only include their \
findings if evidence_quote is a verbatim explicit statement of the relationship.
5. Discard any connection where no subagent provided a verbatim evidence_quote.
5a. Discard any connection whose target_name is not a proper named entity (person, organization, PAC, committee, or company). Addresses, descriptors, attributes, and concepts are not valid targets.
6. Write relationship_type as a single plain sentence summarizing the relationship, incorporating the strongest evidence.
7. Do not promote evidence_strength based on subagent count alone — only distinct domains count.

Add "suggested_expansions": up to 5 target_name values most worth investigating further.
Prefer entities with direct evidence, opaque/dark-money structures, and non-obvious relationships.
Only include proper named entities (people, organizations, PACs, committees, companies) — never addresses or attributes.
Exclude the seed entity itself. Return [] if nothing is interesting enough to expand.

Return ONLY valid JSON — no preamble, no markdown fences:
{
  "entity": "<seed entity name>",
  "connections": [
    {
      "target_name": "string",
      "target_type": "individual|organization|committee|pac|nonprofit",
      "relationship_type": "One plain sentence describing the relationship.",
      "evidence_quotes": ["verbatim quote 1", "verbatim quote 2"],
      "source_urls": ["url1", "url2"],
      "source_domains": ["domain1", "domain2"],
      "evidence_strength": "direct|indirect|weak",
      "found_by": ["subagent1", "subagent2"]
    }
  ],
  "suggested_expansions": ["Entity A", "Entity B"]
}"""

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


async def _run_subagent(name: str, instructions: str, tools: list, entity: str) -> dict:
    _EMPTY = {"subagent": name, "connections": []}
    try:
        async with _SEM:
            agent = Agent(
                name=name,
                model="gpt-5-mini",
                model_settings=ModelSettings(reasoning={"effort": "low"}, parallel_tool_calls=True, max_tokens=4096),
                instructions=instructions,
                tools=tools,
            )
            result = await Runner.run(agent, f"Find connections for: {entity}", max_turns=10)
        raw = _strip_fences(result.final_output)
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f"  [!] {name}: JSON parse failed — {raw}", file=sys.stderr)
        return _EMPTY
    except Exception as exc:
        print(f"  [!] {name}: failed ({type(exc).__name__}: {exc})", file=sys.stderr)
        return _EMPTY


async def _synthesize(entity: str, subagent_results: list[dict]) -> dict:
    combined = json.dumps(subagent_results, indent=2)
    agent = Agent(
        name="synthesizer",
        model="gpt-5.5",
        model_settings=ModelSettings(reasoning={"effort": "low"}, parallel_tool_calls=False, max_tokens=8192),
        instructions=_SYNTHESIZER_INSTRUCTIONS,
    )
    result = await Runner.run(
        agent,
        f"Entity: {entity}\n\nSubagent outputs:\n{combined}",
        max_turns=2,
    )
    raw = _strip_fences(result.final_output)
    return json.loads(raw)


async def _scan_entity(entity: str) -> dict:
    """Run all 7 subagents + synthesizer for a single entity."""
    print(f"  [*] Scanning '{entity}'...", file=sys.stderr)
    tasks = [
        _run_subagent(name, instructions, tools, entity)
        for name, instructions, tools in _SUBAGENTS
    ]
    subagent_results: list[dict] = await asyncio.gather(*tasks)

    useful = [r for r in subagent_results if r.get("connections")]
    if not useful:
        print(f"  [!] All subagents failed for '{entity}' — skipping synthesis", file=sys.stderr)
        return {"entity": entity, "connections": [], "suggested_expansions": []}

    result = await _synthesize(entity, subagent_results)
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
