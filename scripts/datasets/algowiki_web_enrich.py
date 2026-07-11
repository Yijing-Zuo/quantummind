from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from scripts.datasets.algowiki_common import (  # noqa: E402
    load_yaml_mapping,
    normalize_whitespace,
    short_sha256,
    strip_html,
)

USER_AGENT = "QuantumMindLite AlgorithmWiki rich corpus builder; polite public metadata enrichment"
API_HOSTS = {"api.crossref.org", "export.arxiv.org", "en.wikipedia.org"}
PDF_MARKERS = (".pdf", "/pdf/", "type=pdf")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build source-backed enriched AlgorithmWiki records for rich discovery cards.")
    parser.add_argument("--metadata-dir", required=True)
    parser.add_argument("--precard-dir", required=True)
    parser.add_argument("--review-needed", required=True)
    parser.add_argument("--out-jsonl", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--out-report", required=True)
    parser.add_argument("--out-manifest", required=True)
    parser.add_argument("--max-rows", type=int, default=1901)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=0.08)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--max-source-fetches", type=int, default=900)
    args = parser.parse_args(argv)

    out_jsonl = Path(args.out_jsonl)
    out_report = Path(args.out_report)
    out_manifest = Path(args.out_manifest)
    cache_dir = Path(args.cache_dir)
    if not internet_available(cache_dir, float(args.timeout_seconds)):
        write_blocked(out_report, out_manifest, "internet connectivity check failed; enrichment was not fabricated")
        return 2

    metadata_paths = sorted(Path(args.metadata_dir).glob("AW-*.meta.yaml"))[: int(args.max_rows)]
    review_ids = read_review_ids(Path(args.review_needed))
    existing = load_existing(out_jsonl) if bool(args.resume) else {}
    fetch_budget = FetchBudget(remaining=int(args.max_source_fetches))
    robots: dict[str, RobotFileParser | None] = {}
    records: list[dict[str, Any]] = []
    for metadata_path in metadata_paths:
        algorithm_id = metadata_path.stem.removesuffix(".meta")
        if algorithm_id in existing:
            records.append(existing[algorithm_id])
            continue
        metadata = load_yaml_mapping(metadata_path)
        precard_path = Path(args.precard_dir) / f"{algorithm_id}.precard.yaml"
        precard = load_yaml_mapping(precard_path) if precard_path.exists() else {}
        records.append(
            enrich_record(
                metadata=metadata,
                precard=precard,
                review_ids=review_ids,
                cache_dir=cache_dir,
                fetch_budget=fetch_budget,
                robots=robots,
                sleep_seconds=float(args.sleep_seconds),
                timeout_seconds=float(args.timeout_seconds),
            )
        )

    write_jsonl(out_jsonl, records)
    report = build_report(records, metadata_paths, fetch_budget)
    write_text(out_report, markdown_report(report))
    write_json(out_manifest, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


class FetchBudget:
    def __init__(self, remaining: int) -> None:
        self.remaining = remaining
        self.used = 0

    def consume(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        self.used += 1
        return True


def read_review_ids(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {row["algorithm_id"] for row in csv.DictReader(handle)}


def load_existing(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    records: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            data = json.loads(line)
            if isinstance(data, dict) and data.get("algorithm_id"):
                records[str(data["algorithm_id"])] = data
    return records


def internet_available(cache_dir: Path, timeout_seconds: float) -> bool:
    url = "https://api.crossref.org/works?rows=0"
    result = fetch_public_url(url, cache_dir, {}, timeout_seconds, 0.0, None)
    return str(result.get("status", "")) == "fetched"


def enrich_record(
    metadata: dict[str, Any],
    precard: dict[str, Any],
    review_ids: set[str],
    cache_dir: Path,
    fetch_budget: FetchBudget,
    robots: dict[str, RobotFileParser | None],
    sleep_seconds: float,
    timeout_seconds: float,
) -> dict[str, Any]:
    algorithm_id = str(metadata.get("algorithm_id", ""))
    name = text_value(metadata, "canonical_name")
    source_link = text_value(metadata, "source_link")
    attempts = query_attempts(name, source_link, text_value(metadata, "domain"), algorithm_id in review_ids)
    source_records = [algorithm_wiki_source(metadata, precard)]

    doi = extract_doi(source_link)
    if doi:
        attempts.append({"query": doi, "method": "crossref_doi_metadata", "status": "attempted"})
        crossref = fetch_crossref(doi, cache_dir, fetch_budget, sleep_seconds, timeout_seconds)
        if crossref is not None:
            attempts[-1]["status"] = crossref["access_status"]
            source_records.append(crossref)
        else:
            attempts[-1]["status"] = "failed"

    arxiv_id = extract_arxiv_id(source_link)
    if arxiv_id:
        attempts.append({"query": arxiv_id, "method": "arxiv_abstract_metadata", "status": "attempted"})
        arxiv = fetch_arxiv(arxiv_id, cache_dir, fetch_budget, sleep_seconds, timeout_seconds)
        if arxiv is not None:
            attempts[-1]["status"] = arxiv["access_status"]
            source_records.append(arxiv)
        else:
            attempts[-1]["status"] = "failed"

    if source_link and should_fetch_source_page(source_link):
        attempts.append({"query": source_link, "method": "source_link_html_metadata", "status": "attempted"})
        source = fetch_source_page(source_link, cache_dir, fetch_budget, robots, sleep_seconds, timeout_seconds)
        if source is not None:
            attempts[-1]["status"] = source["access_status"]
            source_records.append(source)
        else:
            attempts[-1]["status"] = "failed_or_skipped"

    if should_try_wikipedia(name, source_records):
        attempts.append({"query": f"{name} algorithm", "method": "wikipedia_summary_search", "status": "attempted"})
        wiki = fetch_wikipedia(name, cache_dir, fetch_budget, sleep_seconds, timeout_seconds)
        if wiki is not None:
            attempts[-1]["status"] = wiki["access_status"]
            source_records.append(wiki)
        else:
            attempts[-1]["status"] = "failed_or_not_relevant"

    extracted = infer_extracted_fields(metadata, precard, source_records)
    confidence = confidence_score(metadata, source_records, extracted)
    return {
        "algorithm_id": algorithm_id,
        "canonical_name": name,
        "original_algorithm_name": name,
        "source_link": source_link,
        "source_link_type": text_value(metadata, "source_link_type") or "unknown",
        "existing_metadata": metadata,
        "web_query_attempts": attempts,
        "source_records": source_records,
        "extracted_problem_statement": extracted["problem_statement"],
        "extracted_algorithm_summary": extracted["algorithm_summary"],
        "extracted_pseudocode_or_steps": extracted["pseudocode_or_steps"],
        "extracted_input_semantics": extracted["input_semantics"],
        "extracted_output_semantics": extracted["output_semantics"],
        "extracted_classical_time_complexity": extracted["time_complexity"],
        "extracted_space_complexity": extracted["space_complexity"],
        "extracted_computation_model": extracted["computation_model"],
        "extracted_bottleneck": extracted["bottleneck"],
        "extracted_assumptions": extracted["assumptions"],
        "extracted_domain": extracted["domain"],
        "extracted_family": extracted["family"],
        "confidence_score": confidence,
        "enrichment_status": enrichment_status(extracted, source_records, confidence),
    }


def query_attempts(name: str, source_link: str, domain: str, review_needed: bool) -> list[dict[str, str]]:
    variants = [
        f"{name} algorithm input output complexity",
        f"{name} algorithm pseudocode",
        f"{name} problem definition",
    ]
    if domain and domain != "unknown":
        variants.append(f"{name} {domain.replace('_', ' ')} algorithm")
    variants.extend([f"{name} site:nist.gov DADS", f"{name} algorithm wiki"])
    if source_link:
        variants.append(source_link)
    minimum = 3 if review_needed else 1
    return [{"query": query, "method": "search_plan", "status": "recorded"} for query in variants[: max(minimum, len(variants))]]


def algorithm_wiki_source(metadata: dict[str, Any], precard: dict[str, Any]) -> dict[str, Any]:
    facts = [
        fact("AlgorithmWiki row name", text_value(metadata, "canonical_name")),
        fact("domain", text_value(metadata, "domain")),
        fact("time complexity", text_value(metadata, "time_complexity")),
        fact("space complexity", text_value(metadata, "space_complexity")),
        fact("computational model", text_value(metadata, "computational_model")),
        fact("parameter definitions", text_value(metadata, "parameter_definitions")),
        fact("precard summary", text_value(precard, "public_summary")),
    ]
    return {
        "source_id": f"{text_value(metadata, 'algorithm_id')}:algorithm_wiki_metadata",
        "url": text_value(metadata, "source_link"),
        "title": f"AlgorithmWiki metadata for {text_value(metadata, 'canonical_name')}",
        "source_type": "algorithm_wiki",
        "access_status": "metadata_only",
        "reliability": "HIGH",
        "extracted_facts": [item for item in facts if item],
        "short_quote": "",
        "digest": short_sha256({"algorithm_id": metadata.get("algorithm_id"), "metadata": facts}),
    }


def fact(label: str, value: str) -> str:
    return f"{label}: {value}" if value else ""


def fetch_crossref(
    doi: str,
    cache_dir: Path,
    fetch_budget: FetchBudget,
    sleep_seconds: float,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    if not fetch_budget.consume():
        return skipped_source("doi_metadata", f"https://doi.org/{doi}", "fetch budget exhausted")
    url = f"https://api.crossref.org/works/{quote(doi, safe='')}"
    payload = fetch_public_url(url, cache_dir, {}, timeout_seconds, sleep_seconds, None)
    if payload["status"] != "fetched":
        return failed_source("doi_metadata", f"https://doi.org/{doi}", str(payload.get("error", "fetch failed")))
    try:
        data = json.loads(str(payload.get("text", "{}")))
    except json.JSONDecodeError:
        return failed_source("doi_metadata", f"https://doi.org/{doi}", "Crossref response was not JSON")
    message = data.get("message", {})
    if not isinstance(message, dict):
        return failed_source("doi_metadata", f"https://doi.org/{doi}", "Crossref response lacked message metadata")
    title = first_text(message.get("title")) or f"DOI metadata {doi}"
    abstract = strip_html(first_text(message.get("abstract")) or "")
    facts = stable_facts(
        [
            fact("DOI title", title),
            fact("published year", year_from_crossref(message)),
            fact("container title", first_text(message.get("container-title"))),
            fact("abstract summary", first_sentence(abstract)),
        ]
    )
    return {
        "source_id": f"crossref:{short_sha256(doi)}",
        "url": f"https://doi.org/{doi}",
        "title": title,
        "source_type": "doi_metadata",
        "access_status": "fetched",
        "reliability": "HIGH",
        "extracted_facts": facts,
        "short_quote": short_quote(first_sentence(abstract)),
        "digest": short_sha256({"doi": doi, "facts": facts}),
    }


def fetch_arxiv(
    arxiv_id: str,
    cache_dir: Path,
    fetch_budget: FetchBudget,
    sleep_seconds: float,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    if not fetch_budget.consume():
        return skipped_source("arxiv_abstract", f"https://arxiv.org/abs/{arxiv_id}", "fetch budget exhausted")
    url = f"https://export.arxiv.org/api/query?id_list={quote_plus(arxiv_id)}"
    payload = fetch_public_url(url, cache_dir, {}, timeout_seconds, sleep_seconds, None)
    if payload["status"] != "fetched":
        return failed_source("arxiv_abstract", f"https://arxiv.org/abs/{arxiv_id}", str(payload.get("error", "fetch failed")))
    try:
        root = ElementTree.fromstring(str(payload.get("text", "")))
    except ElementTree.ParseError:
        return failed_source("arxiv_abstract", f"https://arxiv.org/abs/{arxiv_id}", "arXiv response was not XML")
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entry = root.find("atom:entry", ns)
    if entry is None:
        return failed_source("arxiv_abstract", f"https://arxiv.org/abs/{arxiv_id}", "no arXiv entry found")
    title = normalize_whitespace(entry.findtext("atom:title", default="", namespaces=ns))
    summary = normalize_whitespace(entry.findtext("atom:summary", default="", namespaces=ns))
    facts = stable_facts([fact("arXiv title", title), fact("abstract summary", first_sentence(summary))])
    return {
        "source_id": f"arxiv:{arxiv_id}",
        "url": f"https://arxiv.org/abs/{arxiv_id}",
        "title": title or f"arXiv metadata {arxiv_id}",
        "source_type": "arxiv_abstract",
        "access_status": "fetched",
        "reliability": "HIGH",
        "extracted_facts": facts,
        "short_quote": short_quote(first_sentence(summary)),
        "digest": short_sha256({"arxiv_id": arxiv_id, "facts": facts}),
    }


def fetch_source_page(
    url: str,
    cache_dir: Path,
    fetch_budget: FetchBudget,
    robots: dict[str, RobotFileParser | None],
    sleep_seconds: float,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    if not fetch_budget.consume():
        return skipped_source(classify_source_type(url), url, "fetch budget exhausted")
    if not robots_allows(url, cache_dir, robots, timeout_seconds):
        return skipped_source(classify_source_type(url), url, "robots.txt disallowed fetch")
    payload = fetch_public_url(url, cache_dir, robots, timeout_seconds, sleep_seconds, None)
    if payload["status"] != "fetched":
        return failed_source(classify_source_type(url), url, str(payload.get("error", "fetch failed")))
    text = str(payload.get("text", ""))
    content_type = str(payload.get("content_type", ""))
    if "pdf" in content_type.lower():
        return skipped_source(classify_source_type(url), url, "PDF body was not stored")
    title = extract_title(text) or url
    description = extract_description(text)
    facts = stable_facts([fact("source page title", title), fact("source page description", first_sentence(description))])
    return {
        "source_id": f"source:{short_sha256(url)}",
        "url": url,
        "title": title,
        "source_type": classify_source_type(url),
        "access_status": "fetched",
        "reliability": reliability_for_url(url),
        "extracted_facts": facts,
        "short_quote": short_quote(first_sentence(description)),
        "digest": short_sha256({"url": url, "facts": facts}),
    }


def fetch_wikipedia(
    name: str,
    cache_dir: Path,
    fetch_budget: FetchBudget,
    sleep_seconds: float,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    if not fetch_budget.consume():
        return skipped_source("wikipedia", f"https://en.wikipedia.org/wiki/{quote(name.replace(' ', '_'))}", "fetch budget exhausted")
    search_url = "https://en.wikipedia.org/w/api.php?action=opensearch&limit=1&namespace=0&format=json&search=" + quote_plus(
        name + " algorithm"
    )
    payload = fetch_public_url(search_url, cache_dir, {}, timeout_seconds, sleep_seconds, None)
    if payload["status"] != "fetched":
        return None
    try:
        data = json.loads(str(payload.get("text", "[]")))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list) or len(data) < 4 or not data[1]:
        return None
    title = str(data[1][0])
    page_url = str(data[3][0])
    if not wikipedia_title_relevant(name, title):
        return None
    summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(title.replace(' ', '_'))}"
    summary_payload = fetch_public_url(summary_url, cache_dir, {}, timeout_seconds, sleep_seconds, None)
    if summary_payload["status"] != "fetched":
        return None
    try:
        summary = json.loads(str(summary_payload.get("text", "{}")))
    except json.JSONDecodeError:
        return None
    extract = normalize_whitespace(str(summary.get("extract", "")))
    if not source_text_has_algorithm_cue(f"{title} {extract}"):
        return None
    facts = stable_facts([fact("Wikipedia page", title), fact("summary", first_sentence(extract))])
    return {
        "source_id": f"wikipedia:{short_sha256(page_url)}",
        "url": page_url,
        "title": title,
        "source_type": "wikipedia",
        "access_status": "fetched",
        "reliability": "MEDIUM",
        "extracted_facts": facts,
        "short_quote": short_quote(first_sentence(extract)),
        "digest": short_sha256({"url": page_url, "facts": facts}),
    }


def fetch_public_url(
    url: str,
    cache_dir: Path,
    robots: dict[str, RobotFileParser | None],
    timeout_seconds: float,
    sleep_seconds: float,
    max_chars: int | None,
) -> dict[str, Any]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{short_sha256(url)}.json"
    payload: dict[str, Any]
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, dict):
                return cached
        except json.JSONDecodeError:
            pass
    if is_pdf_url(url):
        payload = {
            "url": url,
            "status": "skipped",
            "access_status": "skipped",
            "error": "PDF download skipped",
            "fetched_at": datetime.now(UTC).isoformat(),
        }
        write_json(cache_path, payload)
        return payload
    host = urlparse(url).netloc.lower()
    if host not in API_HOSTS and robots and not robots_allows(url, cache_dir, robots, timeout_seconds):
        payload = {
            "url": url,
            "status": "skipped",
            "access_status": "skipped",
            "error": "robots.txt disallowed fetch",
            "fetched_at": datetime.now(UTC).isoformat(),
        }
        write_json(cache_path, payload)
        return payload
    try:
        request = Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json,application/xml,text/xml,*/*;q=0.5"}
        )
        with urlopen(request, timeout=timeout_seconds) as response:
            content_type = response.headers.get("Content-Type", "")
            raw = response.read(max_chars or 700_000)
            text = raw.decode("utf-8", "replace")
            status_code = int(getattr(response, "status", 200))
        payload = {
            "url": url,
            "status": "fetched",
            "status_code": status_code,
            "content_type": content_type,
            "text": text,
            "fetched_at": datetime.now(UTC).isoformat(),
        }
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        payload = {
            "url": url,
            "status": "failed",
            "error": str(exc),
            "fetched_at": datetime.now(UTC).isoformat(),
        }
    write_json(cache_path, payload)
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    return payload


def robots_allows(url: str, cache_dir: Path, robots: dict[str, RobotFileParser | None], timeout_seconds: float) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if not host or host in API_HOSTS:
        return True
    if host not in robots:
        robots_url = f"{parsed.scheme or 'https'}://{host}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        payload = fetch_public_url(robots_url, cache_dir, {}, timeout_seconds, 0.0, 100_000)
        if payload["status"] != "fetched":
            robots[host] = None
        else:
            parser.parse(str(payload.get("text", "")).splitlines())
            robots[host] = parser
    parser_or_none = robots.get(host)
    return True if parser_or_none is None else bool(parser_or_none.can_fetch(USER_AGENT, url))


def infer_extracted_fields(metadata: dict[str, Any], precard: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    name = text_value(metadata, "canonical_name")
    source_text = combined_source_text(metadata, precard, sources)
    domain = infer_domain(text_value(metadata, "domain"), source_text)
    input_semantics = infer_input_semantics(domain, name, metadata, source_text)
    output_semantics = infer_output_semantics(domain, name, metadata, source_text)
    problem_statement = infer_problem_statement(domain, name, input_semantics, output_semantics, source_text)
    algorithm_summary = infer_algorithm_summary(name, metadata, source_text, domain)
    return {
        "problem_statement": problem_statement,
        "algorithm_summary": algorithm_summary,
        "pseudocode_or_steps": infer_steps(domain, name, source_text),
        "input_semantics": input_semantics,
        "output_semantics": output_semantics,
        "time_complexity": text_value(metadata, "time_complexity") or "unknown",
        "space_complexity": text_value(metadata, "space_complexity") or "unknown",
        "computation_model": text_value(metadata, "computational_model") or "not stated",
        "bottleneck": infer_bottleneck(domain, output_semantics),
        "assumptions": infer_assumptions(metadata, sources),
        "domain": domain,
        "family": infer_family(metadata, domain, source_text),
    }


def combined_source_text(metadata: dict[str, Any], precard: dict[str, Any], sources: list[dict[str, Any]]) -> str:
    parts = [
        text_value(metadata, "canonical_name"),
        text_value(metadata, "domain"),
        text_value(metadata, "family"),
        text_value(metadata, "parameter_definitions"),
        text_value(metadata, "time_complexity"),
        text_value(precard, "public_summary"),
        text_value(precard, "likely_problem"),
    ]
    for source in sources:
        parts.append(str(source.get("title", "")))
        parts.extend(str(item) for item in source.get("extracted_facts", []) if item)
    return normalize_whitespace(" ".join(parts))


def infer_domain(existing: str, text: str) -> str:
    if existing and existing != "unknown":
        return existing
    lowered = text.lower()
    checks = (
        ("sorting", ("sort", "sorting", "selection", "quickselect", "median", "order statistic")),
        ("graph", ("graph", "vertex", "vertices", "edge", "shortest path", "spanning tree", "nearest neighbor", "network")),
        ("matrix_linear_algebra", ("matrix", "linear system", "linear algebra", "cholesky", "gaussian", "strassen")),
        ("string", ("string", "sequence alignment", "edit distance", "motif", "pattern matching", "blast")),
        ("dynamic_programming", ("dynamic programming", "subset sum", "knapsack", "rod cutting", "coin change")),
        ("computational_geometry", ("convex hull", "line segment", "polygon", "voronoi", "delaunay", "clipping", "geometric")),
        ("data_structures", ("data structure", "priority queue", "tree", "heap", "dictionary")),
        ("optimization", ("optimization", "assignment", "scheduling", "knapsack")),
        ("randomized_sampling", ("sampling", "monte carlo", "gibbs")),
        ("numerical_analysis", ("approximation", "numerical", "integration", "root", "entropy")),
        ("combinatorics", ("subset sum", "cycle", "permutation", "n-queens", "queens")),
    )
    for domain, needles in checks:
        if any(needle in lowered for needle in needles):
            return domain
    return "unknown"


def infer_input_semantics(domain: str, name: str, metadata: dict[str, Any], text: str) -> str:
    params = text_value(metadata, "parameter_definitions")
    lowered = f"{name} {text} {params}".lower()
    if "subset sum" in lowered or "target sum" in lowered:
        return "A finite set or multiset of integers with a target sum parameter."
    if "nearest neighbor" in lowered or "hnsw" in lowered:
        return "A metric or vector data set, query points, and graph/search parameters for nearest-neighbor lookup."
    if "cycle" in lowered and any(term in lowered for term in ("lambda", "period", "mu")):
        return "An iterated function or sequence representation with parameters for the preperiod and cycle length."
    mapping = {
        "sorting": "A finite array or list of comparable keys or records.",
        "graph": "An explicit graph instance with vertices, edges, weights, labels, or local adjacency as required by the named task.",
        "matrix_linear_algebra": "One or more explicit matrices or linear systems over the stated arithmetic domain.",
        "string": "One or more finite strings, sequences, patterns, or alphabets.",
        "computational_geometry": "Explicit geometric objects such as points, line segments, polygons, or planar subdivisions.",
        "data_structures": "A set of records plus update/query operations for the named data structure.",
        "dynamic_programming": "An explicit optimization or recurrence instance with overlapping subproblems.",
        "optimization": "An explicit feasible-region, objective, scheduling, assignment, or knapsack-style instance.",
        "numerical_analysis": "Numeric parameters, functions, samples, tolerances, or distributions for the stated numerical task.",
        "randomized_sampling": "A probability model, data set, or sampler description together with requested estimator parameters.",
        "image_processing": "An image, grid, point cloud, or signal representation with local or hierarchical processing parameters.",
        "robotics": "A robot state-estimation or planning instance with observations, controls, map, or configuration constraints.",
        "parallel_algorithms": "The classical input instance named by the row, together with processor/work/span parameters when stated.",
        "combinatorics": "A finite combinatorial object, integer set, board, recurrence, or witness-search instance.",
    }
    return mapping.get(domain, "")


def infer_output_semantics(domain: str, name: str, metadata: dict[str, Any], text: str) -> str:
    lowered = f"{name} {text}".lower()
    if "subset sum" in lowered or "target sum" in lowered:
        return (
            "A decision result, feasible subset witness, count, or optimized subset value for the target-sum instance, "
            "depending on the row."
        )
    if "nearest neighbor" in lowered or "hnsw" in lowered:
        return "Nearest-neighbor or approximate nearest-neighbor identifiers and distances for the query points."
    if "quickselect" in lowered or "selection" in lowered and "sort" not in lowered:
        return "The selected order statistic or item of requested rank."
    if "shortest path" in lowered or "a*" in lowered:
        return "A path, path cost, or predecessor structure connecting the requested graph states."
    if "minimum spanning" in lowered or "kruskal" in lowered or "spanning tree" in lowered:
        return "A minimum spanning tree or forest for the weighted graph."
    if "edit distance" in lowered or "wagner" in lowered:
        return "An edit-distance value, alignment, or dynamic-programming table information for the input strings."
    if "pattern" in lowered or "matching" in lowered or "string-search" in lowered or "boyer" in lowered:
        return "Pattern occurrence positions, matches, or the associated string-search report."
    if "matrix multiplication" in lowered or "matrix product" in lowered or "strassen" in lowered:
        return "The matrix product or bilinear multiplication output."
    if "gaussian" in lowered or "linear system" in lowered:
        return "A solved linear system, echelon form, inverse, or elimination-derived matrix output."
    if "cholesky" in lowered:
        return "A Cholesky factorization of the input positive-definite matrix."
    mapping = {
        "sorting": "The same items returned in nondecreasing order, usually as a full reordered sequence.",
        "graph": (
            "The graph-specific object requested by the named problem, such as a path, tree, matching, flow, "
            "component labeling, or traversal result."
        ),
        "matrix_linear_algebra": "The requested matrix, decomposition, solution vector, or other linear-algebraic output.",
        "string": "The requested string matching, alignment, indexing, distance, or transformation result.",
        "computational_geometry": (
            "The requested geometric structure, simplified curve, clipping result, intersection set, hull, or diagram."
        ),
        "data_structures": "A maintained data structure representation and answers to its supported queries.",
        "dynamic_programming": "The optimal value, witness, schedule, segmentation, or table-derived solution for the recurrence.",
        "optimization": "An optimal or approximate feasible solution with its objective value or schedule/assignment representation.",
        "numerical_analysis": "An exact or approximate numerical value, estimate, approximation, or fitted representation.",
        "randomized_sampling": "A sample, estimate, or approximate value with the stated randomized or statistical semantics.",
        "image_processing": "A transformed image, segmentation, quantization, feature set, or detected structure.",
        "robotics": "A state estimate, map, path, configuration sequence, or control-relevant output.",
        "parallel_algorithms": "The same mathematical output as the underlying classical task, annotated by work/span when available.",
        "combinatorics": "A count, witness, construction, ordering, subset, cycle, or other finite combinatorial output.",
    }
    return mapping.get(domain, "")


def infer_problem_statement(domain: str, name: str, input_semantics: str, output_semantics: str, text: str) -> str:
    if not input_semantics or not output_semantics or domain == "unknown":
        return ""
    task = named_task_phrase(name, domain, text)
    return normalize_whitespace(
        f"{name} is treated as a classical {domain.replace('_', ' ')} task for rich AlgorithmWiki discovery. "
        f"Problem/task: {task} Input semantics: {input_semantics} Output semantics: {output_semantics}"
    )


def named_task_phrase(name: str, domain: str, text: str) -> str:
    lowered = f"{name} {text}".lower()
    if "subset sum" in lowered or "target sum" in lowered:
        return "solve a subset-sum or target-sum dynamic-programming/search problem."
    if "nearest neighbor" in lowered or "hnsw" in lowered:
        return "answer approximate nearest-neighbor search queries using a navigable small-world graph structure."
    if domain == "sorting":
        return "sort the input sequence using the named classical sorting method."
    if domain == "graph" and ("shortest path" in lowered or "a*" in lowered):
        return "find a low-cost or shortest path in a graph or state-space search instance."
    if domain == "matrix_linear_algebra" and ("strassen" in lowered or "multiplication" in lowered):
        return "multiply matrices using the named bilinear or algebraic multiplication method."
    if domain == "string" and ("edit" in lowered or "wagner" in lowered):
        return "compute edit distance or alignment structure for two strings."
    if domain == "computational_geometry" and "clipping" in lowered:
        return "clip geometric primitives against a polygonal or rectangular clipping region."
    return f"analyze the concrete classical task associated with {name}."


def infer_algorithm_summary(name: str, metadata: dict[str, Any], text: str, domain: str) -> str:
    baseline = complexity_summary(metadata)
    model = text_value(metadata, "computational_model")
    model_part = f" The stated classical model is {model}." if model else ""
    first = first_sentence(text)
    source_part = f" Public metadata/source text adds: {first}" if first else ""
    return normalize_whitespace(f"{name} is a {domain.replace('_', ' ')} algorithm record. {baseline}.{model_part}{source_part}")


def infer_steps(domain: str, name: str, text: str) -> str:
    lowered = f"{name} {text}".lower()
    if "hnsw" in lowered:
        return (
            "Build layered proximity graphs, greedily descend from coarse layers, and search neighbors in the base layer "
            "for approximate nearest neighbors."
        )
    if "kruskal" in lowered:
        return "Sort or bucket edges by weight, scan candidate edges, and use connectivity tests to add safe edges to the spanning forest."
    if "a*" in lowered:
        return (
            "Maintain a frontier ordered by path cost plus heuristic estimate, expand states, and return the recovered "
            "path when the target is reached."
        )
    if domain == "sorting":
        return "Compare, partition, merge, count, distribute, or otherwise reorder records according to the named sorting method."
    if domain == "matrix_linear_algebra":
        return "Apply the named arithmetic decomposition, elimination, or multiplication recurrence to produce the requested matrix output."
    if domain == "dynamic_programming":
        return (
            "Define subproblems, evaluate recurrence transitions, store table values, and reconstruct the requested value "
            "or witness when applicable."
        )
    return ""


def infer_bottleneck(domain: str, output_semantics: str) -> str:
    if "full reordered sequence" in output_semantics or domain == "sorting":
        return "comparison/distribution work plus writing the full ordered sequence."
    if domain == "graph":
        return "graph traversal, priority/frontier maintenance, and materializing graph outputs."
    if domain == "matrix_linear_algebra":
        return "arithmetic over dense or structured matrices and the cost of producing matrix-sized outputs."
    if domain == "string":
        return "string scanning, dynamic-programming table size, preprocessing, and match reporting."
    if domain == "computational_geometry":
        return "geometric predicates, event ordering, and output-sensitive structure size."
    if domain == "data_structures":
        return "update/query costs, balancing, and representation size."
    if domain in {"numerical_analysis", "randomized_sampling"}:
        return "precision, convergence, sample complexity, and estimator variance."
    if domain == "parallel_algorithms":
        return "work, span/depth, processor count, and communication/synchronization assumptions."
    return "dominant bottleneck remains uncertain from the available public source metadata."


def infer_assumptions(metadata: dict[str, Any], sources: list[dict[str, Any]]) -> list[str]:
    assumptions: list[str] = []
    if text_value(metadata, "approximate") in {"1", "true", "yes", "Yes"}:
        assumptions.append("The AlgorithmWiki row marks the classical method as approximate.")
    if text_value(metadata, "randomized") in {"1", "true", "yes", "Yes"}:
        assumptions.append("The AlgorithmWiki row marks the classical method as randomized.")
    if not any(source.get("source_type") != "algorithm_wiki" and source.get("access_status") == "fetched" for source in sources):
        assumptions.append(
            "No independent fetched public metadata source resolved this row beyond AlgorithmWiki metadata/source-link facts."
        )
    return assumptions


def infer_family(metadata: dict[str, Any], domain: str, text: str) -> str:
    existing = text_value(metadata, "family")
    if existing and existing != "unknown":
        return existing
    lowered = text.lower()
    if "subset sum" in lowered:
        return "subset_sum"
    if "nearest neighbor" in lowered:
        return "nearest_neighbor_search"
    if "minimum spanning" in lowered or "kruskal" in lowered:
        return "minimum_spanning_tree"
    if "shortest path" in lowered or "a*" in lowered:
        return "shortest_path_search"
    return domain


def confidence_score(metadata: dict[str, Any], sources: list[dict[str, Any]], extracted: dict[str, Any]) -> int:
    score = int(metadata.get("quality_score", 0) or 0)
    if extracted["problem_statement"]:
        score += 15
    if extracted["input_semantics"] and extracted["output_semantics"]:
        score += 15
    for source in sources:
        if source.get("source_type") != "algorithm_wiki" and source.get("access_status") == "fetched":
            score += 10 if source.get("reliability") == "HIGH" else 5
    return min(score, 100)


def enrichment_status(extracted: dict[str, Any], sources: list[dict[str, Any]], confidence: int) -> str:
    has_independent = any(source.get("source_type") != "algorithm_wiki" and source.get("access_status") == "fetched" for source in sources)
    if confidence >= 70 and extracted["problem_statement"] and has_independent:
        return "READY_WEB_ENRICHED"
    if confidence >= 65 and extracted["problem_statement"]:
        return "READY_METADATA_WITH_SOURCE"
    return "WEB_INSUFFICIENT"


def complexity_summary(metadata: dict[str, Any]) -> str:
    parts = []
    for label, key in (
        ("time", "time_complexity"),
        ("space", "space_complexity"),
        ("work", "work"),
        ("span/depth", "span_depth"),
        ("processors", "number_of_processors"),
    ):
        value = text_value(metadata, key)
        if value:
            parts.append(f"{label} {value}")
    return "Classical complexity metadata: " + "; ".join(parts) if parts else "Classical complexity is not stated"


def extract_doi(url_or_doi: str) -> str:
    value = unquote(url_or_doi.strip())
    if not value or value == "-":
        return ""
    match = re.search(r"(10\.\d{4,9}/[^\s\"<>]+)", value, flags=re.IGNORECASE)
    if not match:
        return ""
    doi = match.group(1).rstrip(").,;")
    doi = doi.split("?")[0]
    return doi


def extract_arxiv_id(url: str) -> str:
    match = re.search(r"arxiv\.org/(?:abs|pdf)/([^?#]+)", url, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"arxiv:([0-9.]+)", url, flags=re.IGNORECASE)
    if not match:
        return ""
    return match.group(1).removesuffix(".pdf")


def should_fetch_source_page(url: str) -> bool:
    if not url or url == "-" or is_pdf_url(url):
        return False
    return url.startswith(("http://", "https://"))


def is_pdf_url(url: str) -> bool:
    lowered = url.lower()
    return any(marker in lowered for marker in PDF_MARKERS)


def should_try_wikipedia(name: str, sources: list[dict[str, Any]]) -> bool:
    if any(
        source.get("source_type") in {"doi_metadata", "arxiv_abstract"} and source.get("access_status") == "fetched" for source in sources
    ):
        return False
    lowered = name.lower()
    return source_text_has_algorithm_cue(lowered) and len(name.split()) <= 6


def source_text_has_algorithm_cue(text: str) -> bool:
    lowered = text.lower()
    return any(
        cue in lowered
        for cue in (
            "algorithm",
            "sort",
            "search",
            "tree",
            "graph",
            "matrix",
            "string",
            "sampling",
            "dynamic programming",
            "nearest neighbor",
            "clipping",
        )
    )


def wikipedia_title_relevant(name: str, title: str) -> bool:
    name_tokens = {token for token in re.findall(r"[a-z0-9]+", name.lower()) if len(token) >= 3}
    title_tokens = {token for token in re.findall(r"[a-z0-9]+", title.lower()) if len(token) >= 3}
    return bool(name_tokens & title_tokens)


def classify_source_type(url: str) -> str:
    lowered = url.lower()
    if "wikipedia.org" in lowered:
        return "wikipedia"
    if "nist.gov" in lowered:
        return "nist_dads"
    if "cp-algorithms" in lowered:
        return "cp_algorithms"
    if "the-algorithms" in lowered or "github.com/thealgorithms" in lowered:
        return "the_algorithms"
    if "arxiv.org" in lowered:
        return "arxiv_abstract"
    if "doi.org" in lowered:
        return "doi_metadata"
    if any(host in lowered for host in ("dl.acm.org", "siam.org", "sciencedirect.com", "springer.com", "ieee.org")):
        return "publisher_abstract"
    if ".edu" in lowered:
        return "textbook_or_course_notes"
    return "other_public_source"


def reliability_for_url(url: str) -> str:
    source_type = classify_source_type(url)
    if source_type in {"nist_dads", "doi_metadata", "arxiv_abstract", "publisher_abstract"}:
        return "HIGH"
    if source_type in {"wikipedia", "cp_algorithms", "the_algorithms", "textbook_or_course_notes"}:
        return "MEDIUM"
    return "LOW"


def extract_title(html_text: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html_text)
    if match:
        return normalize_whitespace(strip_html(match.group(1)))[:240]
    return ""


def extract_description(html_text: str) -> str:
    patterns = (
        r'(?is)<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        r'(?is)<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
        r'(?is)<meta[^>]+name=["\']citation_abstract["\'][^>]+content=["\']([^"\']+)["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, html_text)
        if match:
            return normalize_whitespace(strip_html(match.group(1)))[:1200]
    return normalize_whitespace(strip_html(html_text))[:1200]


def first_text(value: Any) -> str:
    if isinstance(value, list) and value:
        return normalize_whitespace(str(value[0]))
    if isinstance(value, str):
        return normalize_whitespace(value)
    return ""


def year_from_crossref(message: dict[str, Any]) -> str:
    for key in ("published-print", "published-online", "created", "issued"):
        value = message.get(key)
        if isinstance(value, dict):
            date_parts = value.get("date-parts")
            if isinstance(date_parts, list) and date_parts and isinstance(date_parts[0], list) and date_parts[0]:
                return str(date_parts[0][0])
    return ""


def first_sentence(text: str) -> str:
    cleaned = normalize_whitespace(text)
    if not cleaned:
        return ""
    match = re.search(r"(.{40,420}?[.!?])\s", cleaned + " ")
    return normalize_whitespace(match.group(1)) if match else cleaned[:420]


def short_quote(text: str) -> str:
    words = re.findall(r"\S+", text)
    return " ".join(words[:24]) if words else ""


def stable_facts(items: list[str]) -> list[str]:
    seen: set[str] = set()
    facts: list[str] = []
    for item in items:
        cleaned = normalize_whitespace(item)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            facts.append(cleaned[:700])
    return facts


def skipped_source(source_type: str, url: str, reason: str) -> dict[str, Any]:
    return {
        "source_id": f"skipped:{short_sha256(url + reason)}",
        "url": url,
        "title": reason,
        "source_type": source_type,
        "access_status": "skipped",
        "reliability": "LOW",
        "extracted_facts": [reason],
        "short_quote": "",
        "digest": short_sha256({"url": url, "reason": reason}),
    }


def failed_source(source_type: str, url: str, reason: str) -> dict[str, Any]:
    return {
        "source_id": f"failed:{short_sha256(url + reason)}",
        "url": url,
        "title": reason,
        "source_type": source_type,
        "access_status": "failed",
        "reliability": "LOW",
        "extracted_facts": [reason[:300]],
        "short_quote": "",
        "digest": short_sha256({"url": url, "reason": reason}),
    }


def text_value(record: dict[str, Any], key: str) -> str:
    return normalize_whitespace(str(record.get(key, "") or ""))


def build_report(records: list[dict[str, Any]], metadata_paths: list[Path], fetch_budget: FetchBudget) -> dict[str, Any]:
    status_counts = Counter(str(record.get("enrichment_status", "")) for record in records)
    source_type_counts: Counter[str] = Counter()
    access_counts: Counter[str] = Counter()
    quality_counts: Counter[str] = Counter()
    for record in records:
        for source in record.get("source_records", []):
            source_type_counts[str(source.get("source_type", ""))] += 1
            access_counts[str(source.get("access_status", ""))] += 1
            quality_counts[str(source.get("reliability", ""))] += 1
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "input_metadata_count": len(metadata_paths),
        "output_records": len(records),
        "status_counts": dict(sorted(status_counts.items())),
        "source_type_counts": dict(sorted(source_type_counts.items())),
        "source_access_counts": dict(sorted(access_counts.items())),
        "source_reliability_counts": dict(sorted(quality_counts.items())),
        "network_fetches_used": fetch_budget.used,
        "network_fetches_remaining": fetch_budget.remaining,
        "note": "PDF bodies were skipped; fetched sources are public metadata, abstract pages, API metadata, or AlgorithmWiki metadata.",
    }


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# AlgorithmWiki Rich Web Enrichment Report",
        "",
        f"- Input metadata count: {report['input_metadata_count']}",
        f"- Output records: {report['output_records']}",
        f"- Enrichment status counts: {report['status_counts']}",
        f"- Source type counts: {report['source_type_counts']}",
        f"- Source access counts: {report['source_access_counts']}",
        f"- Source reliability counts: {report['source_reliability_counts']}",
        f"- Network fetches used: {report['network_fetches_used']}",
        f"- Network fetches remaining: {report['network_fetches_remaining']}",
        "",
        str(report["note"]),
    ]
    return "\n".join(lines) + "\n"


def write_blocked(report_path: Path, manifest_path: Path, reason: str) -> None:
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "blocked": True,
        "reason": reason,
        "confirmation": "No enrichment records were fabricated without internet access.",
    }
    write_text(report_path, "# AlgorithmWiki Rich Web Enrichment Blocked\n\n" + reason + "\n")
    write_json(manifest_path, payload)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=True) + "\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
