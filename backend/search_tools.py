"""Shared Exa search tools used by agent.py and enrich.py."""

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any

from dotenv import load_dotenv
from agents import function_tool
from exa_py import Exa

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

_exa = Exa(api_key=os.environ["EXA_API_KEY"])


def exa_search(
    query: str,
    num_results: int,
    include_domains: list[str] | None = None,
    neural: bool = True,
) -> str:
    kwargs: dict[str, Any] = {
        "num_results": num_results,
        "type": "neural" if neural else "keyword",
        "contents": {"highlights": {"query": query}},
    }
    if include_domains:
        kwargs["include_domains"] = include_domains
    domain_tag = f" [{','.join(include_domains)}]" if include_domains else ""
    print(f"    [exa{domain_tag}] {query!r}", file=sys.stderr)
    resp = _exa.search(query, **kwargs)
    if not resp.results:
        return "No results found."
    parts = []
    for r in resp.results:
        highlights = " | ".join(r.highlights) if r.highlights else "(no highlights)"
        parts.append(
            f"URL: {r.url}\n"
            f"Title: {r.title or '(no title)'}\n"
            f"Published: {getattr(r, 'published_date', None) or 'unknown'}\n"
            f"Highlights: {highlights}"
        )
    return "\n\n---\n\n".join(parts)


def fmt_similar(resp: Any) -> str:
    if not resp.results:
        return "No results found."
    parts = []
    for r in resp.results:
        highlights = " | ".join(r.highlights) if r.highlights else "(no highlights)"
        parts.append(
            f"URL: {r.url}\n"
            f"Title: {r.title or '(no title)'}\n"
            f"Highlights: {highlights}"
        )
    return "\n\n---\n\n".join(parts)


@function_tool
def web_search(
    query: Annotated[str, "Search query"],
    num_results: Annotated[int, "Number of results, 1-10"] = 5,
) -> str:
    """Search the open web with Exa neural search. Use for single targeted queries."""
    return exa_search(query, num_results, neural=True)


@function_tool
def multi_search(
    queries: Annotated[list[str], "List of independent search queries to run in parallel, max 8"],
    num_results: Annotated[int, "Results per query, 1-10"] = 5,
) -> str:
    """Run multiple open-web searches in parallel. Use when you have several independent queries planned upfront."""
    queries = queries[:8]
    print(f"    [multi_search x{len(queries)}]", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        results = list(pool.map(lambda q: exa_search(q, num_results, neural=True), queries))
    return "\n\n".join(f"=== Query: {q!r} ===\n{r}" for q, r in zip(queries, results))


@function_tool
def opensecrets_search(
    query: Annotated[str, "Search query"],
    num_results: Annotated[int, "Number of results, 1-10"] = 5,
) -> str:
    """Search opensecrets.org for donor networks, PAC relationships, and campaign finance records."""
    return exa_search(query, num_results, ["opensecrets.org"], neural=False)


@function_tool
def fec_search(
    query: Annotated[str, "Search query"],
    num_results: Annotated[int, "Number of results, 1-10"] = 5,
) -> str:
    """Search fec.gov for federal filings, committee registrations, and treasurer names."""
    return exa_search(query, num_results, ["fec.gov"], neural=False)


@function_tool
def influencewatch_search(
    query: Annotated[str, "Search query"],
    num_results: Annotated[int, "Number of results, 1-10"] = 5,
) -> str:
    """Search influencewatch.org for dark money connections and nonprofit network relationships."""
    return exa_search(query, num_results, ["influencewatch.org"], neural=False)


@function_tool
def propublica_search(
    query: Annotated[str, "Search query"],
    num_results: Annotated[int, "Number of results, 1-10"] = 5,
) -> str:
    """Search propublica.org for nonprofit 990 filings, campaign finance investigations, and political reporting."""
    return exa_search(query, num_results, ["propublica.org"], neural=False)


@function_tool
def find_similar_pages(
    url: Annotated[str, "URL of a page already found — returns pages similar to it"],
    num_results: Annotated[int, "Number of results, 1-10"] = 5,
) -> str:
    """Find pages similar to a URL. Use after a primary search surfaces a strong lead."""
    print(f"    [similar] {url!r}", file=sys.stderr)
    resp = _exa.find_similar(url, num_results=num_results, contents={"highlights": True})
    return fmt_similar(resp)
