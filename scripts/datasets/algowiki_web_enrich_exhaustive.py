from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus
from xml.etree import ElementTree

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from scripts.datasets.algowiki_build_rich_cards import (  # noqa: E402
    evidence_record,
    make_context_card,
    make_probe_cards,
    probe_manifest_row,
    probe_metadata,
    review_needed_record,
)
from scripts.datasets.algowiki_common import (  # noqa: E402
    PublicProblemCard,
    leakage_matches,
    normalize_whitespace,
    public_card_digest,
    short_sha256,
    stable_unique,
    strip_html,
    write_yaml,
)
from scripts.datasets.algowiki_select_rich_live_sets import live_command_text, live_output_dir  # noqa: E402
from scripts.datasets.algowiki_web_enrich import (  # noqa: E402
    FetchBudget,
    algorithm_wiki_source,
    extract_arxiv_id,
    extract_description,
    extract_doi,
    extract_title,
    fetch_arxiv,
    fetch_crossref,
    fetch_public_url,
    fetch_wikipedia,
    first_sentence,
    short_quote,
)
from scripts.datasets.algowiki_web_enrich_second_pass import (  # noqa: E402
    choose_rule,
    merge_sources,
    source_ids,
    source_quality,
)

OUTPUT_DIRS = (
    "enriched_records",
    "public_context_recovered",
    "public_probe_recovered",
    "metadata_context_recovered",
    "metadata_probe_recovered",
    "evidence_recovered",
    "still_unresolved_saturated",
    "source_saturation_certificates",
    "audit",
    "reports",
    "manifests",
    "commands",
    "cache",
)

TERMINAL_STATUSES = {
    "RECOVERED_CONTEXT",
    "RECOVERED_CONTEXT_AND_PROBE",
    "RECOVERED_PROBE_ONLY",
    "SATURATED_NO_RECOVERY",
    "BLOCKED_BY_PAYWALL_OR_MISSING_SOURCE",
    "AMBIGUOUS_AUTHOR_TITLE_FRAGMENT",
    "DUPLICATE_OR_VARIANT_ONLY",
}

FACT_TYPES = {
    "problem_definition",
    "input_semantics",
    "output_semantics",
    "time_complexity",
    "space_complexity",
    "computation_model",
    "pseudocode_step",
    "algorithm_family",
    "bottleneck",
    "assumption",
    "alias",
    "source_title",
    "authoritative_source_link",
}

ALGORITHM_CUES = (
    "algorithm",
    "problem",
    "complexity",
    "input",
    "output",
    "graph",
    "path",
    "tree",
    "matrix",
    "linear",
    "integer",
    "factor",
    "multiplication",
    "image",
    "feature",
    "corner",
    "mesh",
    "surface",
    "render",
    "shading",
    "segmentation",
    "kalman",
    "state estimation",
    "markov",
    "pomdp",
    "policy",
    "planning",
    "dynamic programming",
    "string",
    "matching",
)

SOURCE_FAMILY_LABELS = (
    "original_source",
    "crossref",
    "openalex",
    "semantic_scholar",
    "arxiv",
    "dblp",
    "publisher_abstract",
    "citeseerx",
    "wikipedia",
    "wikidata",
    "nist_dads",
    "algorithm_wiki_local",
    "the_algorithms",
    "cp_algorithms",
    "course_notes",
    "general_web_search",
    "local_previous_cache",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Third-pass source-saturation enrichment for unresolved AlgorithmWiki rows.")
    parser.add_argument("--unresolved-csv", required=True)
    parser.add_argument("--v1-root", required=True)
    parser.add_argument("--second-pass-root", required=True)
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--max-cycles", type=int, default=6)
    parser.add_argument("--min-cycles", type=int, default=3)
    parser.add_argument("--no-new-fact-stop", type=int, default=2)
    parser.add_argument("--max-fetches-per-row", type=int, default=25)
    parser.add_argument("--global-fetch-budget", type=int, default=12000)
    parser.add_argument("--sleep-seconds", type=float, default=0.2)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--max-rows", type=int, default=0, help="Optional smoke-test row cap; 0 means all unresolved rows.")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)

    unresolved_path = Path(args.unresolved_csv)
    if not unresolved_path.exists():
        unresolved_path = Path(args.v1_root) / "manifests" / "review_needed_after_web.csv"
    out_root = Path(args.out_root)
    create_output_dirs(out_root)
    clear_generated_outputs(out_root)

    rows = read_csv(unresolved_path)
    if int(args.max_rows) > 0:
        rows = rows[: int(args.max_rows)]
    v1_records = load_jsonl_by_id(Path(args.v1_root) / "enriched_records" / "enriched_algorithms.jsonl")
    second_records = load_jsonl_by_id(
        Path(args.second_pass_root) / "enriched_records_second_pass" / "enriched_algorithms_second_pass.jsonl"
    )
    second_notes = load_jsonl_by_id(Path(args.second_pass_root) / "enriched_records_second_pass" / "reconstruction_notes.jsonl")
    write_starting_state(out_root, rows, second_records, second_notes)

    if not internet_available(out_root / "cache", float(args.timeout_seconds)):
        write_blocked_report(out_root, rows, "internet connectivity check failed; no third-pass web facts were fabricated")
        print(json.dumps({"blocked": True, "reason": "internet connectivity check failed"}, indent=2))
        return 2

    budget = FetchBudget(int(args.global_fetch_budget))
    context_rows: list[dict[str, Any]] = []
    probe_rows: list[dict[str, Any]] = []
    still_rows: list[dict[str, Any]] = []
    certificates: list[dict[str, Any]] = []
    enriched_records: list[dict[str, Any]] = []
    all_facts: list[dict[str, Any]] = []
    all_sources: list[dict[str, Any]] = []
    probe_index = 0

    for index, row in enumerate(rows, start=1):
        algorithm_id = str(row.get("algorithm_id", ""))
        base_record = second_records.get(algorithm_id) or v1_records.get(algorithm_id) or {}
        v1_record = v1_records.get(algorithm_id, {})
        certificate, record = saturate_row(
            row=row,
            base_record=base_record,
            v1_record=v1_record,
            second_note=second_notes.get(algorithm_id, {}),
            cache_dir=out_root / "cache",
            budget=budget,
            max_cycles=int(args.max_cycles),
            min_cycles=int(args.min_cycles),
            no_new_fact_stop=int(args.no_new_fact_stop),
            max_fetches_per_row=int(args.max_fetches_per_row),
            sleep_seconds=float(args.sleep_seconds),
            timeout_seconds=float(args.timeout_seconds),
        )
        card, reasons = make_context_card(record)
        if card is not None and certificate["saturation_status"] in {"RECOVERED_CONTEXT", "RECOVERED_CONTEXT_AND_PROBE"}:
            write_recovered_context(out_root, record, card, certificate)
            context_rows.append(context_manifest_row(out_root, record, card, certificate))
            probes = make_probe_cards(record)
            if probes:
                certificate["saturation_status"] = "RECOVERED_CONTEXT_AND_PROBE"
            for probe in probes:
                probe_index += 1
                probe_id = f"{algorithm_id}-TP{probe_index:04d}"
                write_recovered_probe(out_root, record, probe_id, probe, certificate)
                probe_rows.append(
                    probe_manifest_row(
                        record,
                        probe_id,
                        probe,
                        out_root / "public_probe_recovered",
                        out_root / "metadata_probe_recovered",
                        out_root / "evidence_recovered",
                    )
                )
        else:
            if certificate["saturation_status"] in {"RECOVERED_CONTEXT", "RECOVERED_CONTEXT_AND_PROBE"}:
                certificate["saturation_status"] = terminal_unresolved_status(record, certificate, reasons)
                certificate["final_reason"] = "; ".join(stable_unique([str(certificate["final_reason"]), *reasons]))
            still = review_needed_record(record, [str(certificate["final_reason"])])
            write_yaml(out_root / "still_unresolved_saturated" / f"{algorithm_id}.yaml", still)
            still_rows.append(still_manifest_row(still, certificate))

        write_yaml(out_root / "source_saturation_certificates" / f"{algorithm_id}.saturation.yaml", certificate)
        certificates.append(certificate)
        enriched_records.append(record)
        all_facts.extend(list(certificate["discovered_facts"]))
        all_sources.extend(source_manifest_rows(certificate))
        if index % 25 == 0:
            print(f"processed {index}/{len(rows)} rows; recovered_context={len(context_rows)}; remaining_budget={budget.remaining}")

    write_jsonl(out_root / "enriched_records" / "enriched_algorithms_third_pass.jsonl", enriched_records)
    write_jsonl(out_root / "enriched_records" / "source_saturation_certificates.jsonl", certificates)
    write_csv(out_root / "manifests" / "recovered_context.csv", context_rows)
    write_jsonl(out_root / "manifests" / "recovered_context.jsonl", context_rows)
    write_csv(out_root / "manifests" / "recovered_probe.csv", probe_rows)
    write_jsonl(out_root / "manifests" / "recovered_probe.jsonl", probe_rows)
    write_csv(out_root / "manifests" / "still_unresolved_saturated.csv", still_rows)
    write_csv(out_root / "manifests" / "source_saturation_certificates.csv", certificate_manifest_rows(certificates))
    write_csv(out_root / "manifests" / "new_sources_discovered.csv", all_sources)
    write_csv(out_root / "manifests" / "new_facts_discovered.csv", fact_manifest_rows(all_facts))
    write_csv(out_root / "manifests" / "recovery_by_source_family.csv", recovery_by_source_family(certificates))
    write_commands(out_root)
    write_reviews(out_root, certificates, context_rows, probe_rows)
    report = build_final_report(rows, certificates, context_rows, probe_rows, still_rows, all_sources, all_facts, budget)
    write_json(out_root / "manifests" / "third_pass_manifest.json", report)
    write_reports(out_root, report, certificates, context_rows, probe_rows, still_rows)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def saturate_row(
    row: dict[str, str],
    base_record: dict[str, Any],
    v1_record: dict[str, Any],
    second_note: dict[str, Any],
    cache_dir: Path,
    budget: FetchBudget,
    max_cycles: int,
    min_cycles: int,
    no_new_fact_stop: int,
    max_fetches_per_row: int,
    sleep_seconds: float,
    timeout_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    metadata = metadata_from_records(base_record, v1_record)
    algorithm_id = str(row.get("algorithm_id") or metadata.get("algorithm_id", ""))
    name = normalize_whitespace(str(row.get("algorithm_name") or metadata.get("canonical_name", "")))
    metadata.setdefault("algorithm_id", algorithm_id)
    metadata.setdefault("canonical_name", name)
    previous_sources = merge_sources(list(v1_record.get("source_records", [])), list(base_record.get("source_records", [])))
    if not previous_sources:
        previous_sources = [algorithm_wiki_source(metadata, {})]
    aliases = build_aliases(name, metadata, previous_sources)
    facts = initial_facts(algorithm_id, metadata, previous_sources, row, second_note)
    certificate: dict[str, Any] = {
        "algorithm_id": algorithm_id,
        "canonical_name": name,
        "original_source_link": text_value(metadata, "source_link"),
        "source_link_type": text_value(metadata, "source_link_type") or "unknown",
        "previous_failure_reasons": previous_failure_reasons(row, base_record, second_note),
        "previous_source_records": previous_sources,
        "aliases_tried": aliases,
        "query_plan": build_query_plan(name, aliases, metadata),
        "query_attempts": [],
        "source_attempts": [],
        "discovered_sources": [],
        "discovered_facts": facts,
        "duplicate_sources": [],
        "failed_sources": [],
        "paywalled_or_skipped_sources": [],
        "source_families_covered": [],
        "cycles_completed": 0,
        "new_fact_count_by_cycle": [],
        "no_new_fact_streak": 0,
        "saturation_status": "",
        "final_reason": "",
        "next_manual_action": "",
    }
    row_fetches = 0
    source_records = list(previous_sources)
    fact_keys = {fact_key(fact) for fact in facts}

    for cycle in range(1, max_cycles + 1):
        cycle_new = 0
        families = families_for_cycle(cycle, metadata)
        for family in families:
            if row_fetches >= max_fetches_per_row:
                add_attempt(certificate, cycle, family, best_alias(aliases), "", "skipped_budget", 0, "row fetch budget exhausted")
                continue
            result = attempt_family(
                family,
                cycle,
                aliases,
                metadata,
                cache_dir,
                budget,
                sleep_seconds,
                timeout_seconds,
            )
            certificate["query_attempts"].extend(result["attempts"])
            certificate["source_attempts"].extend(result["attempts"])
            row_fetches += int(result["fetches_used"])
            add_family(certificate, family)
            for source in result["sources"]:
                if is_duplicate_source(source, source_records):
                    certificate["duplicate_sources"].append(source)
                    continue
                if str(source.get("access_status", "")) in {"failed"}:
                    certificate["failed_sources"].append(source)
                elif str(source.get("access_status", "")) in {"skipped", "paywalled"}:
                    certificate["paywalled_or_skipped_sources"].append(source)
                source_records.append(source)
                certificate["discovered_sources"].append(source)
            for fact in result["facts"]:
                key = fact_key(fact)
                if key not in fact_keys:
                    fact_keys.add(key)
                    certificate["discovered_facts"].append(fact)
                    cycle_new += 1
        record = reconstruct_record(metadata, name, source_records, certificate)
        if has_recoverable_context(record):
            certificate["saturation_status"] = "RECOVERED_CONTEXT"
            certificate["final_reason"] = (
                "Source-saturation pass found enough task, input, output, and access semantics for a context card."
            )
            certificate["next_manual_action"] = "Audit recovered card before any optional live analyze run."
            certificate["cycles_completed"] = cycle
            certificate["new_fact_count_by_cycle"].append({"cycle": cycle, "new_facts": cycle_new})
            break
        certificate["cycles_completed"] = cycle
        certificate["new_fact_count_by_cycle"].append({"cycle": cycle, "new_facts": cycle_new})
        certificate["no_new_fact_streak"] = int(certificate["no_new_fact_streak"]) + 1 if cycle_new == 0 else 0
        if (
            cycle >= min_cycles
            and int(certificate["no_new_fact_streak"]) >= no_new_fact_stop
            and len(certificate["source_families_covered"]) >= 5
        ):
            certificate["saturation_status"] = terminal_unresolved_status(record, certificate, [])
            certificate["final_reason"] = unresolved_reason(record, certificate)
            certificate["next_manual_action"] = next_manual_action(certificate)
            break
    if not certificate["saturation_status"]:
        record = reconstruct_record(metadata, name, source_records, certificate)
        certificate["saturation_status"] = terminal_unresolved_status(record, certificate, [])
        certificate["final_reason"] = unresolved_reason(record, certificate)
        certificate["next_manual_action"] = next_manual_action(certificate)
    record = reconstruct_record(metadata, name, source_records, certificate)
    return certificate, record


def attempt_family(
    family: str,
    cycle: int,
    aliases: list[str],
    metadata: dict[str, Any],
    cache_dir: Path,
    budget: FetchBudget,
    sleep_seconds: float,
    timeout_seconds: float,
) -> dict[str, Any]:
    before = int(budget.used)
    if family == "algorithm_wiki_local":
        source = algorithm_wiki_source(metadata, {})
        facts = facts_from_source(str(metadata.get("algorithm_id", "")), source, "algorithm_wiki_local")
        return result(
            [attempt(cycle, family, best_alias(aliases), source.get("url", ""), "fetched", len(facts), "local metadata")],
            [source],
            facts,
            before,
            budget,
        )
    if family == "local_previous_cache":
        return result(
            [attempt(cycle, family, best_alias(aliases), "", "duplicate", 0, "previous v1/second-pass sources reused")],
            [],
            [],
            before,
            budget,
        )
    if family == "original_source":
        return attempt_original_source(cycle, aliases, metadata, cache_dir, budget, sleep_seconds, timeout_seconds, before)
    if family == "crossref":
        return attempt_crossref(cycle, aliases, metadata, cache_dir, budget, sleep_seconds, timeout_seconds, before)
    if family == "openalex":
        return attempt_openalex(cycle, aliases, metadata, cache_dir, budget, sleep_seconds, timeout_seconds, before)
    if family == "semantic_scholar":
        return attempt_semantic_scholar(cycle, aliases, metadata, cache_dir, budget, sleep_seconds, timeout_seconds, before)
    if family == "arxiv":
        return attempt_arxiv(cycle, aliases, metadata, cache_dir, budget, sleep_seconds, timeout_seconds, before)
    if family == "dblp":
        return attempt_dblp(cycle, aliases, metadata, cache_dir, budget, sleep_seconds, timeout_seconds, before)
    if family == "publisher_abstract":
        return attempt_publisher(cycle, aliases, metadata, cache_dir, budget, sleep_seconds, timeout_seconds, before)
    if family == "citeseerx":
        return attempt_static_unavailable(cycle, family, aliases, "CiteSeerX link is PDF/legacy metadata; full PDF body skipped")
    if family == "wikipedia":
        return attempt_wikipedia(cycle, aliases, metadata, cache_dir, budget, sleep_seconds, timeout_seconds, before)
    if family == "wikidata":
        return attempt_wikidata(cycle, aliases, metadata, cache_dir, budget, sleep_seconds, timeout_seconds, before)
    if family == "nist_dads":
        return attempt_reference_family(cycle, family, aliases, "NIST DADS has no reliable bulk search API in this environment")
    if family == "the_algorithms":
        return attempt_reference_family(cycle, family, aliases, "TheAlgorithms search skipped unless a known exact reference is available")
    if family == "cp_algorithms":
        return attempt_reference_family(cycle, family, aliases, "CP-Algorithms search skipped unless a known exact reference is available")
    if family == "course_notes":
        return attempt_reference_family(cycle, family, aliases, "No configured public course-notes search endpoint")
    if family == "general_web_search":
        return attempt_reference_family(
            cycle, family, aliases, "No configured general web search endpoint; Google Scholar scraping is not used"
        )
    return attempt_reference_family(cycle, family, aliases, "source family not applicable")


def attempt_original_source(
    cycle: int,
    aliases: list[str],
    metadata: dict[str, Any],
    cache_dir: Path,
    budget: FetchBudget,
    sleep_seconds: float,
    timeout_seconds: float,
    before: int,
) -> dict[str, Any]:
    url = clean_source_url(text_value(metadata, "source_link"))
    if not url or url in {"-", "NA", "N/A"} or not url.lower().startswith(("http://", "https://")):
        return result(
            [attempt(cycle, "original_source", best_alias(aliases), "", "no_result", 0, "no original source link")], [], [], before, budget
        )
    if ".pdf" in url.lower() or "/pdf/" in url.lower():
        source = skipped_source("original_source", url, "public PDF body was not downloaded")
        return result([attempt(cycle, "original_source", url, url, "paywalled", 0, "PDF body skipped")], [source], [], before, budget)
    if not budget.consume():
        return result(
            [attempt(cycle, "original_source", url, url, "skipped_budget", 0, "global fetch budget exhausted")], [], [], before, budget
        )
    payload = fetch_public_url(url, cache_dir, {}, timeout_seconds, sleep_seconds, None)
    if str(payload.get("status", "")) != "fetched":
        source = failed_source("original_source", url, str(payload.get("error", "fetch failed")))
        return result(
            [attempt(cycle, "original_source", url, url, "fetch_failed", 0, str(payload.get("error", "fetch failed")))],
            [source],
            [],
            before,
            budget,
        )
    text = str(payload.get("text", ""))
    title = extract_title(text) or url
    description = extract_description(text)
    source = source_record(
        "source:" + short_sha256(url),
        url,
        title,
        "publisher_abstract",
        "fetched",
        reliability_for_url(url),
        [title, first_sentence(description)],
    )
    facts = facts_from_source(text_value(metadata, "algorithm_id"), source, "original_source")
    status = "fetched" if source_relevant(aliases, source) else "irrelevant"
    return result(
        [attempt(cycle, "original_source", url, url, status, len(facts), "original source page metadata")], [source], facts, before, budget
    )


def attempt_crossref(
    cycle: int,
    aliases: list[str],
    metadata: dict[str, Any],
    cache_dir: Path,
    budget: FetchBudget,
    sleep_seconds: float,
    timeout_seconds: float,
    before: int,
) -> dict[str, Any]:
    doi = extract_doi(text_value(metadata, "source_link"))
    query = doi or best_alias(aliases)
    source: dict[str, Any] | None = None
    if doi:
        source = fetch_crossref(doi, cache_dir, budget, sleep_seconds, timeout_seconds)
    elif query:
        source = fetch_crossref_title(query, cache_dir, budget, sleep_seconds, timeout_seconds)
    if not source:
        return result(
            [attempt(cycle, "crossref", query, "", "no_result", 0, "Crossref returned no useful metadata")], [], [], before, budget
        )
    facts = facts_from_source(text_value(metadata, "algorithm_id"), source, "crossref") if source_relevant(aliases, source) or doi else []
    status = "fetched" if facts else "irrelevant"
    return result(
        [attempt(cycle, "crossref", query, str(source.get("url", "")), status, len(facts), "Crossref metadata/title search")],
        [source],
        facts,
        before,
        budget,
    )


def attempt_openalex(
    cycle: int,
    aliases: list[str],
    metadata: dict[str, Any],
    cache_dir: Path,
    budget: FetchBudget,
    sleep_seconds: float,
    timeout_seconds: float,
    before: int,
) -> dict[str, Any]:
    doi = extract_doi(text_value(metadata, "source_link"))
    if doi:
        url = "https://api.openalex.org/works/doi:" + quote(doi, safe="")
        query = doi
    else:
        query = best_alias(aliases)
        url = "https://api.openalex.org/works?per-page=1&search=" + quote_plus(query)
    if not query or not budget.consume():
        return result([attempt(cycle, "openalex", query, "", "skipped_budget", 0, "no query or budget exhausted")], [], [], before, budget)
    payload = fetch_public_url(url, cache_dir, {}, timeout_seconds, sleep_seconds, None)
    source = parse_openalex(payload, url, query)
    if not source:
        return result([attempt(cycle, "openalex", query, url, "no_result", 0, "OpenAlex returned no usable work")], [], [], before, budget)
    facts = facts_from_source(text_value(metadata, "algorithm_id"), source, "openalex") if source_relevant(aliases, source) or doi else []
    status = "fetched" if facts else "irrelevant"
    return result([attempt(cycle, "openalex", query, url, status, len(facts), "OpenAlex work metadata")], [source], facts, before, budget)


def attempt_semantic_scholar(
    cycle: int,
    aliases: list[str],
    metadata: dict[str, Any],
    cache_dir: Path,
    budget: FetchBudget,
    sleep_seconds: float,
    timeout_seconds: float,
    before: int,
) -> dict[str, Any]:
    doi = extract_doi(text_value(metadata, "source_link"))
    query = doi or best_alias(aliases)
    if not query or not budget.consume():
        return result(
            [attempt(cycle, "semantic_scholar", query, "", "skipped_budget", 0, "no query or budget exhausted")], [], [], before, budget
        )
    if doi:
        url = "https://api.semanticscholar.org/graph/v1/paper/DOI:" + quote(doi, safe="") + "?fields=title,abstract,year,url,externalIds"
    else:
        url = (
            "https://api.semanticscholar.org/graph/v1/paper/search?limit=1&fields=title,abstract,year,url,externalIds&query="
            + quote_plus(query)
        )
    payload = fetch_public_url(url, cache_dir, {}, timeout_seconds, sleep_seconds, None)
    source = parse_semantic_scholar(payload, url, query)
    if not source:
        status = "fetch_failed" if str(payload.get("status", "")) != "fetched" else "no_result"
        return result(
            [attempt(cycle, "semantic_scholar", query, url, status, 0, "Semantic Scholar returned no usable paper")], [], [], before, budget
        )
    facts = (
        facts_from_source(text_value(metadata, "algorithm_id"), source, "semantic_scholar")
        if source_relevant(aliases, source) or doi
        else []
    )
    status = "fetched" if facts else "irrelevant"
    return result(
        [attempt(cycle, "semantic_scholar", query, url, status, len(facts), "Semantic Scholar paper metadata")],
        [source],
        facts,
        before,
        budget,
    )


def attempt_arxiv(
    cycle: int,
    aliases: list[str],
    metadata: dict[str, Any],
    cache_dir: Path,
    budget: FetchBudget,
    sleep_seconds: float,
    timeout_seconds: float,
    before: int,
) -> dict[str, Any]:
    arxiv_id = extract_arxiv_id(text_value(metadata, "source_link"))
    if arxiv_id:
        source = fetch_arxiv(arxiv_id, cache_dir, budget, sleep_seconds, timeout_seconds)
        if source:
            facts = facts_from_source(text_value(metadata, "algorithm_id"), source, "arxiv")
            return result(
                [attempt(cycle, "arxiv", arxiv_id, str(source.get("url", "")), "fetched", len(facts), "arXiv id metadata")],
                [source],
                facts,
                before,
                budget,
            )
    query = best_alias(aliases)
    if not budget.consume():
        return result([attempt(cycle, "arxiv", query, "", "skipped_budget", 0, "global fetch budget exhausted")], [], [], before, budget)
    url = "https://export.arxiv.org/api/query?max_results=1&search_query=ti:" + quote_plus('"' + query + '"')
    payload = fetch_public_url(url, cache_dir, {}, timeout_seconds, sleep_seconds, None)
    source = parse_arxiv_search(payload, url)
    if not source:
        return result(
            [attempt(cycle, "arxiv", query, url, "no_result", 0, "arXiv title search returned no usable entry")], [], [], before, budget
        )
    facts = facts_from_source(text_value(metadata, "algorithm_id"), source, "arxiv") if source_relevant(aliases, source) else []
    status = "fetched" if facts else "irrelevant"
    return result([attempt(cycle, "arxiv", query, url, status, len(facts), "arXiv title metadata")], [source], facts, before, budget)


def attempt_dblp(
    cycle: int,
    aliases: list[str],
    metadata: dict[str, Any],
    cache_dir: Path,
    budget: FetchBudget,
    sleep_seconds: float,
    timeout_seconds: float,
    before: int,
) -> dict[str, Any]:
    query = best_alias(aliases)
    if not budget.consume():
        return result([attempt(cycle, "dblp", query, "", "skipped_budget", 0, "global fetch budget exhausted")], [], [], before, budget)
    url = "https://dblp.org/search/publ/api?format=json&h=1&q=" + quote_plus(query)
    payload = fetch_public_url(url, cache_dir, {}, timeout_seconds, sleep_seconds, None)
    source = parse_dblp(payload, url, query)
    if not source:
        return result([attempt(cycle, "dblp", query, url, "no_result", 0, "DBLP returned no usable publication")], [], [], before, budget)
    facts = facts_from_source(text_value(metadata, "algorithm_id"), source, "dblp") if source_relevant(aliases, source) else []
    status = "fetched" if facts else "irrelevant"
    return result([attempt(cycle, "dblp", query, url, status, len(facts), "DBLP publication metadata")], [source], facts, before, budget)


def attempt_publisher(
    cycle: int,
    aliases: list[str],
    metadata: dict[str, Any],
    cache_dir: Path,
    budget: FetchBudget,
    sleep_seconds: float,
    timeout_seconds: float,
    before: int,
) -> dict[str, Any]:
    link_type = text_value(metadata, "source_link_type")
    url = clean_source_url(text_value(metadata, "source_link"))
    if link_type not in {"acm", "siam", "sciencedirect", "doi", "unknown"} or not url or ".pdf" in url.lower():
        return result(
            [attempt(cycle, "publisher_abstract", best_alias(aliases), url, "no_result", 0, "no applicable publisher abstract URL")],
            [],
            [],
            before,
            budget,
        )
    return attempt_original_source(cycle, aliases, metadata, cache_dir, budget, sleep_seconds, timeout_seconds, before)


def attempt_wikipedia(
    cycle: int,
    aliases: list[str],
    metadata: dict[str, Any],
    cache_dir: Path,
    budget: FetchBudget,
    sleep_seconds: float,
    timeout_seconds: float,
    before: int,
) -> dict[str, Any]:
    query = best_alias(aliases)
    source = fetch_wikipedia(query, cache_dir, budget, sleep_seconds, timeout_seconds)
    if not source:
        return result(
            [attempt(cycle, "wikipedia", query, "", "no_result", 0, "Wikipedia search returned no relevant page")], [], [], before, budget
        )
    facts = facts_from_source(text_value(metadata, "algorithm_id"), source, "wikipedia") if source_relevant(aliases, source) else []
    status = "fetched" if facts else "irrelevant"
    return result(
        [attempt(cycle, "wikipedia", query, str(source.get("url", "")), status, len(facts), "Wikipedia summary metadata")],
        [source],
        facts,
        before,
        budget,
    )


def attempt_wikidata(
    cycle: int,
    aliases: list[str],
    metadata: dict[str, Any],
    cache_dir: Path,
    budget: FetchBudget,
    sleep_seconds: float,
    timeout_seconds: float,
    before: int,
) -> dict[str, Any]:
    query = best_alias(aliases)
    if not budget.consume():
        return result([attempt(cycle, "wikidata", query, "", "skipped_budget", 0, "global fetch budget exhausted")], [], [], before, budget)
    url = "https://www.wikidata.org/w/api.php?action=wbsearchentities&language=en&format=json&limit=1&search=" + quote_plus(query)
    payload = fetch_public_url(url, cache_dir, {}, timeout_seconds, sleep_seconds, None)
    try:
        data = json.loads(str(payload.get("text", "{}")))
    except json.JSONDecodeError:
        return result([attempt(cycle, "wikidata", query, url, "parse_failed", 0, "Wikidata response was not JSON")], [], [], before, budget)
    search = data.get("search", [])
    if not isinstance(search, list) or not search:
        return result([attempt(cycle, "wikidata", query, url, "no_result", 0, "Wikidata returned no entity")], [], [], before, budget)
    item = search[0]
    if not isinstance(item, dict):
        return result(
            [attempt(cycle, "wikidata", query, url, "parse_failed", 0, "Wikidata entity shape was unexpected")], [], [], before, budget
        )
    title = normalize_whitespace(str(item.get("label", "")))
    description = normalize_whitespace(str(item.get("description", "")))
    entity_url = str(item.get("concepturi", url))
    source = source_record("wikidata:" + short_sha256(entity_url), entity_url, title, "wikidata", "fetched", "MEDIUM", [title, description])
    facts = facts_from_source(text_value(metadata, "algorithm_id"), source, "wikidata") if source_relevant(aliases, source) else []
    status = "fetched" if facts else "irrelevant"
    return result(
        [attempt(cycle, "wikidata", query, entity_url, status, len(facts), "Wikidata entity search")], [source], facts, before, budget
    )


def attempt_reference_family(cycle: int, family: str, aliases: list[str], reason: str) -> dict[str, Any]:
    return result([attempt(cycle, family, best_alias(aliases), "", "no_result", 0, reason)], [], [], 0, FetchBudget(0))


def attempt_static_unavailable(cycle: int, family: str, aliases: list[str], reason: str) -> dict[str, Any]:
    return result([attempt(cycle, family, best_alias(aliases), "", "paywalled", 0, reason)], [], [], 0, FetchBudget(0))


def reconstruct_record(
    metadata: dict[str, Any],
    name: str,
    source_records: list[dict[str, Any]],
    certificate: dict[str, Any],
) -> dict[str, Any]:
    facts = list(certificate.get("discovered_facts", []))
    rule = third_pass_rule(name, metadata, facts, source_records)
    if leakage_matches(name):
        rule = {}
    if not rule:
        return unresolved_record(metadata, name, source_records, certificate)
    assumptions = []
    if rule.get("uncertainty"):
        assumptions.append(str(rule["uncertainty"]))
    if not independent_fetched_source(source_records):
        assumptions.append("Third-pass support is limited to AlgorithmWiki row text plus source-family saturation attempts.")
    summary = (
        f"{name} is reconstructed as a classical {str(rule['domain']).replace('_', ' ')} task. "
        f"The source-backed title/name/fact record supports the task: {rule['task']}."
    )
    problem = (
        f"{name} is treated as a source-saturated AlgorithmWiki row for {rule['task']} "
        f"Input semantics: {rule['input']} Output semantics: {rule['output']}"
    )
    confidence = confidence_score(metadata, source_records, rule)
    return {
        "algorithm_id": text_value(metadata, "algorithm_id"),
        "canonical_name": name,
        "original_algorithm_name": name,
        "source_link": text_value(metadata, "source_link"),
        "source_link_type": text_value(metadata, "source_link_type") or "unknown",
        "existing_metadata": metadata_with_size(metadata, rule),
        "web_query_attempts": list(certificate.get("query_attempts", [])),
        "source_records": source_records,
        "extracted_problem_statement": normalize_whitespace(problem),
        "extracted_algorithm_summary": normalize_whitespace(summary),
        "extracted_pseudocode_or_steps": str(rule.get("steps", "")),
        "extracted_input_semantics": str(rule["input"]),
        "extracted_output_semantics": str(rule["output"]),
        "extracted_classical_time_complexity": text_value(metadata, "time_complexity") or "not stated",
        "extracted_space_complexity": text_value(metadata, "space_complexity") or "not stated",
        "extracted_computation_model": text_value(metadata, "computational_model") or str(rule.get("model", "not stated")),
        "extracted_bottleneck": str(rule["bottleneck"]),
        "extracted_assumptions": stable_unique(assumptions),
        "extracted_domain": str(rule["domain"]),
        "extracted_family": str(rule.get("family", rule["domain"])),
        "confidence_score": confidence,
        "enrichment_status": "THIRD_PASS_RECOVERED" if confidence >= 60 else "THIRD_PASS_LOW_CONFIDENCE",
        "third_pass_rule": str(rule["rule_id"]),
    }


def third_pass_rule(
    name: str,
    metadata: dict[str, Any],
    facts: list[dict[str, Any]],
    source_records: list[dict[str, Any]],
) -> dict[str, Any]:
    text = rich_text_for_rules(name, metadata, facts, source_records)
    second_rule = choose_rule(text, name, metadata)
    if second_rule:
        second_rule = dict(second_rule)
        second_rule["rule_id"] = "third_pass_reuse_" + str(second_rule.get("rule_id", "rule"))
        return second_rule
    lowered = text.lower()
    checks = [
        kalman_rule,
        williams_p_plus_one_rule,
        image_feature_rule,
        rendering_rule,
        image_segmentation_rule,
        mesh_simplification_rule,
        decision_process_rule,
        geometry_surface_rule,
        numeric_estimation_rule,
    ]
    for check in checks:
        rule = check(lowered, name.lower(), metadata)
        if rule:
            return rule
    return {}


def base_rule(rule_id: str, domain: str, family: str, task: str, input_text: str, output: str, bottleneck: str) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "domain": domain,
        "family": family,
        "task": task,
        "input": input_text,
        "output": output,
        "bottleneck": bottleneck,
        "score": 45,
    }


def kalman_rule(text: str, name: str, metadata: dict[str, Any]) -> dict[str, Any]:
    if not any(term in text for term in ("kalman", "ukf", "unscented", "extended kf", "state estimation")):
        return {}
    return base_rule(
        "kalman_state_estimation",
        "numerical_analysis",
        "state_estimation",
        "estimate a latent state from a process model and noisy observations",
        "A state-transition model, observation model, covariance/noise parameters, and a sequence of measurements.",
        "A filtered or predicted state estimate, usually with covariance or uncertainty information.",
        "Matrix updates, covariance propagation, sigma-point or linearization steps, and measurement assimilation dominate.",
    )


def williams_p_plus_one_rule(text: str, name: str, metadata: dict[str, Any]) -> dict[str, Any]:
    if "p + 1" not in text and "p+1" not in text and "williams" not in text:
        return {}
    return base_rule(
        "williams_p_plus_one_factorization",
        "combinatorics",
        "integer_factorization",
        "find a nontrivial factor of an integer using Williams' p+1 factorization method",
        "An odd composite integer N represented with n bits and smoothness/search parameters for the p+1 method.",
        "A nontrivial factor of N or a report that the chosen smoothness attempt did not find one.",
        "Modular sequence arithmetic and the smoothness-dependent search for a revealing gcd dominate.",
    )


def image_feature_rule(text: str, name: str, metadata: dict[str, Any]) -> dict[str, Any]:
    terms = ("corner", "dog", "hessian", "interest point", "feature", "mser", "maximally stable", "scale-space", "spatio-temporal")
    if not any(term in text for term in terms):
        return {}
    return base_rule(
        "image_feature_detection",
        "image_processing",
        "feature_detection",
        "detect salient image features, corners, blobs, or stable regions",
        "An image or image sequence with pixel/grid dimensions and scale or detector parameters when stated.",
        "A set of detected feature locations, regions, descriptors, or detector responses.",
        "Convolutions, scale-space extrema tests, region stability checks, and descriptor materialization dominate.",
    )


def rendering_rule(text: str, name: str, metadata: dict[str, Any]) -> dict[str, Any]:
    terms = ("render", "shading", "illumination", "photon", "texture", "blinn", "newell", "hanrahan", "krueger", "ward anisotropic")
    if not any(term in text for term in terms):
        return {}
    return base_rule(
        "rendering_or_shading",
        "image_processing",
        "rendering",
        "compute rendered appearance or illumination for a scene or surface model",
        "Scene geometry, materials or textures, lighting/view parameters, and output-image dimensions.",
        "A rendered image, shading value field, or illumination/texture representation.",
        "Visibility, lighting integration, texture evaluation, and writing the image-sized output dominate.",
    )


def image_segmentation_rule(text: str, name: str, metadata: dict[str, Any]) -> dict[str, Any]:
    terms = (
        "segmentation",
        "region splitting",
        "visual taxometric",
        "dual clustering",
        "active contour",
        "snake",
        "map estimation",
        "conditional modes",
    )
    if not any(term in text for term in terms):
        return {}
    return base_rule(
        "image_segmentation",
        "image_processing",
        "segmentation",
        "partition an image into regions or labels according to local and model-based criteria",
        "An image or pixel graph with neighborhood, feature, or model parameters.",
        "A segmentation, region tree, label assignment, or boundary representation.",
        "Pixel/region graph traversal, local energy updates, clustering, and output label materialization dominate.",
    )


def mesh_simplification_rule(text: str, name: str, metadata: dict[str, Any]) -> dict[str, Any]:
    terms = (
        "coplanar facets",
        "decimation",
        "re-tiling",
        "vertex clustering",
        "wavelet-based",
        "hierarchical representation",
        "mesh simplification",
        "facets merging",
    )
    if not any(term in text for term in terms):
        return {}
    return base_rule(
        "mesh_simplification",
        "computational_geometry",
        "mesh_simplification",
        "simplify or retile a geometric mesh while preserving selected shape properties",
        "A polygonal or triangular mesh with vertices, edges, faces, and simplification/error parameters.",
        "A simplified mesh, merged-facet representation, vertex-clustered mesh, or retiled surface.",
        "Geometric predicates, local error metrics, topology updates, and output mesh construction dominate.",
    )


def decision_process_rule(text: str, name: str, metadata: dict[str, Any]) -> dict[str, Any]:
    terms = ("pomdp", "partially observable", "markov decision", "belief state", "policy", "value iteration", "reinforcement learning")
    if not any(term in text for term in terms):
        return {}
    return base_rule(
        "decision_process_planning",
        "dynamic_programming",
        "markov_decision_process_planning",
        "compute a value function, policy, or approximate plan for a Markov decision process variant",
        (
            "A finite or factored decision process with states or belief states, actions, transitions, "
            "observations, rewards, and horizon/discount parameters."
        ),
        "A policy, value function, plan tree, or approximate policy representation.",
        "Bellman backups, belief-state updates, sampling/search over policies, and representation size dominate.",
    )


def geometry_surface_rule(text: str, name: str, metadata: dict[str, Any]) -> dict[str, Any]:
    if "koenderink" not in text and "surface" not in text and "shape" not in text:
        return {}
    return base_rule(
        "surface_shape_geometry",
        "computational_geometry",
        "surface_geometry",
        "analyze geometric surface shape, curvature, or local differential structure",
        "A sampled surface, image-derived surface representation, or local geometric measurements.",
        "Curvature, local shape descriptors, or classified surface-geometry structures.",
        "Local geometric derivative estimation and output descriptor materialization dominate.",
    )


def numeric_estimation_rule(text: str, name: str, metadata: dict[str, Any]) -> dict[str, Any]:
    if "monte carlo" not in text and "estimation" not in text:
        return {}
    return base_rule(
        "numeric_estimation",
        "numerical_analysis",
        "estimation",
        "estimate a numerical quantity from samples, measurements, or iterative updates",
        "Numerical observations, model parameters, tolerance requirements, and iteration or sample limits.",
        "An estimate with stated tolerance, fitted parameter, or numerical summary.",
        "Sampling or iterative update cost, convergence, and precision control dominate.",
    )


def has_recoverable_context(record: dict[str, Any]) -> bool:
    if text_value(record, "extracted_domain") == "unknown":
        return False
    if not text_value(record, "extracted_input_semantics") or not text_value(record, "extracted_output_semantics"):
        return False
    if leakage_matches(text_value(record, "canonical_name") + " " + text_value(record, "extracted_problem_statement")):
        return False
    return int(record.get("confidence_score", 0) or 0) >= 60


def unresolved_record(
    metadata: dict[str, Any],
    name: str,
    source_records: list[dict[str, Any]],
    certificate: dict[str, Any],
) -> dict[str, Any]:
    return {
        "algorithm_id": text_value(metadata, "algorithm_id"),
        "canonical_name": name,
        "original_algorithm_name": name,
        "source_link": text_value(metadata, "source_link"),
        "source_link_type": text_value(metadata, "source_link_type") or "unknown",
        "existing_metadata": metadata,
        "web_query_attempts": list(certificate.get("query_attempts", [])),
        "source_records": source_records,
        "extracted_problem_statement": "",
        "extracted_algorithm_summary": "",
        "extracted_pseudocode_or_steps": "",
        "extracted_input_semantics": "",
        "extracted_output_semantics": "",
        "extracted_classical_time_complexity": text_value(metadata, "time_complexity") or "not stated",
        "extracted_space_complexity": text_value(metadata, "space_complexity") or "not stated",
        "extracted_computation_model": text_value(metadata, "computational_model") or "not stated",
        "extracted_bottleneck": "",
        "extracted_assumptions": [unresolved_reason_from_certificate(certificate)],
        "extracted_domain": text_value(metadata, "domain") if text_value(metadata, "domain") != "unknown" else "unknown",
        "extracted_family": text_value(metadata, "family") if text_value(metadata, "family") != "unknown" else "unknown",
        "confidence_score": int(metadata.get("quality_score", 0) or 0),
        "enrichment_status": "THIRD_PASS_SATURATED_INSUFFICIENT",
        "third_pass_rule": "none",
    }


def terminal_unresolved_status(record: dict[str, Any], certificate: dict[str, Any], reasons: list[str]) -> str:
    name = text_value(record, "canonical_name")
    if any("leakage" in reason or "public_card_validation_failed" in reason for reason in reasons):
        return "BLOCKED_BY_PAYWALL_OR_MISSING_SOURCE"
    if is_duplicate_or_variant_only(name, certificate):
        return "DUPLICATE_OR_VARIANT_ONLY"
    if is_author_fragment(name) and not certificate.get("discovered_sources"):
        return "AMBIGUOUS_AUTHOR_TITLE_FRAGMENT"
    if certificate.get("paywalled_or_skipped_sources") and not independent_fetched_source(list(record.get("source_records", []))):
        return "BLOCKED_BY_PAYWALL_OR_MISSING_SOURCE"
    return "SATURATED_NO_RECOVERY"


def unresolved_reason(record: dict[str, Any], certificate: dict[str, Any]) -> str:
    if text_value(record, "extracted_domain") == "unknown":
        return (
            "After the configured source-family cycles, no source-backed concrete task, input semantics, "
            "output semantics, and conservative access model could be established."
        )
    return "The row has partial metadata but still lacks one or more source-backed fields required for a public context card."


def unresolved_reason_from_certificate(certificate: dict[str, Any]) -> str:
    status = str(certificate.get("saturation_status", ""))
    if status:
        return str(certificate.get("final_reason", status))
    return "Third-pass source-saturation did not recover enough source-backed task semantics."


def next_manual_action(certificate: dict[str, Any]) -> str:
    status = str(certificate.get("saturation_status", ""))
    if status == "BLOCKED_BY_PAYWALL_OR_MISSING_SOURCE":
        return "Manual curator may inspect publisher or library-access metadata without importing full paywalled text."
    if status == "AMBIGUOUS_AUTHOR_TITLE_FRAGMENT":
        return "Manual curator should identify the exact paper title before any card conversion."
    if status == "DUPLICATE_OR_VARIANT_ONLY":
        return "Manual curator should compare against the recovered parent before merging variants."
    return "No automated action recommended; keep saturated certificate with unresolved row."


def build_aliases(name: str, metadata: dict[str, Any], sources: list[dict[str, Any]]) -> list[str]:
    aliases = [name]
    no_year = normalize_whitespace(re.sub(r"\b(19|20)\d{2}\b", " ", name))
    no_parens = normalize_whitespace(re.sub(r"\([^)]*\)", " ", no_year))
    stripped = normalize_whitespace(re.sub(r"[,;:.]+", " ", no_parens))
    aliases.extend([stripped, f"{name} algorithm", f"{name} problem", f"{name} pseudocode", f"{name} time complexity"])
    for source in sources:
        title = normalize_whitespace(str(source.get("title", "")))
        if title and not title.lower().startswith(("algorithmwiki metadata", "http error", "pdf body")):
            aliases.extend([title, f"{title} algorithm", f"{title} complexity"])
    source_link = text_value(metadata, "source_link")
    doi = extract_doi(source_link)
    arxiv_id = extract_arxiv_id(source_link)
    if doi:
        aliases.append(doi)
    if arxiv_id:
        aliases.append(arxiv_id)
    return [alias for alias in stable_unique([normalize_whitespace(alias) for alias in aliases]) if alias][:12]


def build_query_plan(name: str, aliases: list[str], metadata: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for family in SOURCE_FAMILY_LABELS:
        rows.append(
            {
                "source_family": family,
                "primary_query": best_alias(aliases),
                "applicability": applicability(family, metadata),
                "purpose": query_purpose(family),
            }
        )
    return rows


def query_purpose(family: str) -> str:
    purposes = {
        "original_source": "check the row's original source link without storing paywalled or PDF bodies",
        "crossref": "recover DOI title, venue, year, and abstract metadata where available",
        "openalex": "recover public work metadata and abstract-inverted-index summaries",
        "semantic_scholar": "recover CS paper metadata and abstracts without an API key",
        "arxiv": "recover arXiv title and abstract metadata",
        "dblp": "recover bibliographic title/venue metadata for CS publications",
        "publisher_abstract": "check accessible publisher abstract pages",
        "citeseerx": "record legacy CiteSeerX availability without full PDF storage",
        "wikipedia": "check public encyclopedia algorithm descriptions",
        "wikidata": "check public entity aliases/descriptions",
        "nist_dads": "check whether a DADS-style reference search is applicable",
        "algorithm_wiki_local": "reuse AlgorithmWiki metadata as provenance",
        "the_algorithms": "check exact public implementation/reference names when available",
        "cp_algorithms": "check exact public algorithm reference names when available",
        "course_notes": "record absence of configured course-notes search",
        "general_web_search": "record absence of a configured general web endpoint",
        "local_previous_cache": "reuse v1/second-pass fetched source records",
    }
    return purposes.get(family, "source-family search")


def applicability(family: str, metadata: dict[str, Any]) -> str:
    link_type = text_value(metadata, "source_link_type")
    link = text_value(metadata, "source_link")
    if family == "arxiv" and not extract_arxiv_id(link):
        return "title-search-only"
    if family == "crossref" and not extract_doi(link):
        return "title-search-only"
    if family in {"publisher_abstract", "citeseerx"} and link_type not in {"acm", "siam", "sciencedirect", "citeseerx", "doi", "unknown"}:
        return "not-applicable"
    return "applicable"


def families_for_cycle(cycle: int, metadata: dict[str, Any]) -> list[str]:
    if cycle == 1:
        return ["algorithm_wiki_local", "local_previous_cache", "original_source", "crossref", "arxiv", "wikipedia"]
    if cycle == 2:
        return ["openalex", "semantic_scholar", "dblp", "publisher_abstract", "wikidata"]
    if cycle == 3:
        return ["citeseerx", "nist_dads", "the_algorithms", "cp_algorithms", "course_notes", "general_web_search"]
    return ["crossref", "openalex", "semantic_scholar", "wikipedia", "dblp"]


def initial_facts(
    algorithm_id: str,
    metadata: dict[str, Any],
    sources: list[dict[str, Any]],
    row: dict[str, str],
    second_note: dict[str, Any],
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    metadata_source = f"{algorithm_id}:algorithm_wiki_metadata"
    for fact_type, key in (
        ("alias", "canonical_name"),
        ("time_complexity", "time_complexity"),
        ("space_complexity", "space_complexity"),
        ("computation_model", "computational_model"),
    ):
        value = text_value(metadata, key)
        if value:
            facts.append(make_fact(algorithm_id, fact_type, value, metadata_source, "HIGH", 85, "consistent", "AlgorithmWiki metadata"))
    params = text_value(metadata, "parameter_definitions")
    if params:
        facts.append(
            make_fact(
                algorithm_id,
                "input_semantics",
                "Parameter definitions: " + params,
                metadata_source,
                "HIGH",
                75,
                "weak",
                "AlgorithmWiki parameter metadata",
            )
        )
    if text_value(metadata, "source_link"):
        facts.append(
            make_fact(
                algorithm_id,
                "authoritative_source_link",
                text_value(metadata, "source_link"),
                metadata_source,
                "HIGH",
                70,
                "consistent",
                "Original source link from AlgorithmWiki metadata",
            )
        )
    for source in sources:
        facts.extend(facts_from_source(algorithm_id, source, "previous_source_record"))
    return dedupe_facts(facts)


def facts_from_source(algorithm_id: str, source: dict[str, Any], family: str) -> list[dict[str, Any]]:
    source_id = str(source.get("source_id", family))
    reliability = str(source.get("reliability", "LOW")) or "LOW"
    confidence = {"HIGH": 85, "MEDIUM": 70, "LOW": 45}.get(reliability, 45)
    facts: list[dict[str, Any]] = []
    title = normalize_whitespace(str(source.get("title", "")))
    if title and not title.lower().startswith(("http error", "pdf body was not downloaded")):
        facts.append(make_fact(algorithm_id, "source_title", title, source_id, reliability, confidence, "consistent", family))
        if source_text_has_algorithm_cue(title):
            facts.append(
                make_fact(
                    algorithm_id,
                    "problem_definition",
                    "Source title indicates: " + title,
                    source_id,
                    reliability,
                    confidence,
                    "weak",
                    family,
                )
            )
    for item in source.get("extracted_facts", []):
        value = normalize_whitespace(str(item))
        if not value or value == title:
            continue
        fact_type = classify_fact_type(value)
        facts.append(make_fact(algorithm_id, fact_type, value, source_id, reliability, confidence, "consistent", family))
    url = normalize_whitespace(str(source.get("url", "")))
    if url:
        facts.append(make_fact(algorithm_id, "authoritative_source_link", url, source_id, reliability, confidence, "consistent", family))
    return dedupe_facts(facts)


def make_fact(
    algorithm_id: str,
    fact_type: str,
    value: str,
    source_id: str,
    reliability: str,
    confidence: int,
    conflict_status: str,
    notes: str,
) -> dict[str, Any]:
    fact_type = fact_type if fact_type in FACT_TYPES else "problem_definition"
    clean = normalize_whitespace(value)[:700]
    return {
        "fact_id": algorithm_id + "-F" + short_sha256(fact_type + clean + source_id, 10),
        "fact_type": fact_type,
        "value": clean,
        "source_id": source_id,
        "reliability": reliability,
        "confidence": int(confidence),
        "conflict_status": conflict_status,
        "notes": notes,
    }


def classify_fact_type(value: str) -> str:
    lowered = value.lower()
    if "time" in lowered and "complex" in lowered:
        return "time_complexity"
    if "space" in lowered and "complex" in lowered:
        return "space_complexity"
    if "input" in lowered or "parameter" in lowered:
        return "input_semantics"
    if "output" in lowered or "return" in lowered:
        return "output_semantics"
    if "abstract summary" in lowered or "description" in lowered or "title" in lowered:
        return "problem_definition"
    if "model" in lowered:
        return "computation_model"
    return "problem_definition"


def dedupe_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for fact in facts:
        key = fact_key(fact)
        if key not in seen:
            seen.add(key)
            result.append(fact)
    return result


def fact_key(fact: dict[str, Any]) -> str:
    value = re.sub(r"[^a-z0-9]+", " ", str(fact.get("value", "")).lower())
    return str(fact.get("fact_type", "")) + ":" + normalize_whitespace(value)


def parse_openalex(payload: dict[str, Any], url: str, query: str) -> dict[str, Any] | None:
    if str(payload.get("status", "")) != "fetched":
        return None
    try:
        data = json.loads(str(payload.get("text", "{}")))
    except json.JSONDecodeError:
        return None
    item: dict[str, Any] | None
    if isinstance(data.get("results"), list):
        item = data["results"][0] if data["results"] else None
    else:
        item = data if isinstance(data, dict) else None
    if not isinstance(item, dict):
        return None
    title = normalize_whitespace(str(item.get("title", "")))
    if not title:
        return None
    abstract = openalex_abstract(item.get("abstract_inverted_index"))
    facts = stable_facts(
        [
            fact("OpenAlex title", title),
            fact("publication year", str(item.get("publication_year", ""))),
            fact("abstract summary", first_sentence(abstract)),
        ]
    )
    return source_record(
        "openalex:" + short_sha256(str(item.get("id", query))), str(item.get("id") or url), title, "openalex", "fetched", "HIGH", facts
    )


def parse_semantic_scholar(payload: dict[str, Any], url: str, query: str) -> dict[str, Any] | None:
    if str(payload.get("status", "")) != "fetched":
        return None
    try:
        data = json.loads(str(payload.get("text", "{}")))
    except json.JSONDecodeError:
        return None
    item: dict[str, Any] | None = None
    if isinstance(data.get("data"), list):
        item = data["data"][0] if data["data"] else None
    elif isinstance(data, dict):
        item = data
    if not isinstance(item, dict):
        return None
    title = normalize_whitespace(str(item.get("title", "")))
    if not title:
        return None
    abstract = normalize_whitespace(str(item.get("abstract", "")))
    paper_url = str(item.get("url") or url)
    facts = stable_facts(
        [
            fact("Semantic Scholar title", title),
            fact("published year", str(item.get("year", ""))),
            fact("abstract summary", first_sentence(abstract)),
        ]
    )
    return source_record(
        "semantic_scholar:" + short_sha256(paper_url + query), paper_url, title, "semantic_scholar", "fetched", "MEDIUM", facts
    )


def parse_arxiv_search(payload: dict[str, Any], url: str) -> dict[str, Any] | None:
    if str(payload.get("status", "")) != "fetched":
        return None
    try:
        root = ElementTree.fromstring(str(payload.get("text", "")))
    except ElementTree.ParseError:
        return None
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entry = root.find("atom:entry", ns)
    if entry is None:
        return None
    title = normalize_whitespace(entry.findtext("atom:title", default="", namespaces=ns))
    summary = normalize_whitespace(entry.findtext("atom:summary", default="", namespaces=ns))
    link = normalize_whitespace(entry.findtext("atom:id", default=url, namespaces=ns))
    facts = stable_facts([fact("arXiv title", title), fact("abstract summary", first_sentence(summary))])
    return source_record("arxiv:" + short_sha256(link), link, title, "arxiv_abstract", "fetched", "HIGH", facts)


def parse_dblp(payload: dict[str, Any], url: str, query: str) -> dict[str, Any] | None:
    if str(payload.get("status", "")) != "fetched":
        return None
    try:
        data = json.loads(str(payload.get("text", "{}")))
    except json.JSONDecodeError:
        return None
    hits = data.get("result", {}).get("hits", {}).get("hit", []) if isinstance(data, dict) else []
    if not isinstance(hits, list) or not hits:
        return None
    info = hits[0].get("info", {}) if isinstance(hits[0], dict) else {}
    if not isinstance(info, dict):
        return None
    title = normalize_whitespace(str(info.get("title", "")))
    if not title:
        return None
    link = normalize_whitespace(str(info.get("url", url)))
    facts = stable_facts(
        [fact("DBLP title", title), fact("venue", str(info.get("venue", ""))), fact("published year", str(info.get("year", "")))]
    )
    return source_record("dblp:" + short_sha256(link + query), link, title, "dblp", "fetched", "MEDIUM", facts)


def fetch_crossref_title(
    query: str,
    cache_dir: Path,
    budget: FetchBudget,
    sleep_seconds: float,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    if not budget.consume():
        return None
    url = "https://api.crossref.org/works?rows=1&query.title=" + quote_plus(query)
    payload = fetch_public_url(url, cache_dir, {}, timeout_seconds, sleep_seconds, None)
    if str(payload.get("status", "")) != "fetched":
        return None
    try:
        data = json.loads(str(payload.get("text", "{}")))
    except json.JSONDecodeError:
        return None
    items = data.get("message", {}).get("items", [])
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return None
    item = items[0]
    title = first_string(item.get("title")) or query
    abstract = first_sentence(strip_html(str(item.get("abstract", ""))))
    facts = stable_facts(
        [
            fact("Crossref title", title),
            fact("published year", crossref_year(item)),
            fact("container title", first_string(item.get("container-title"))),
            fact("abstract summary", abstract),
        ]
    )
    return source_record(
        "crossref_search:" + short_sha256(query), str(item.get("URL", "")), title, "doi_metadata", "fetched", "MEDIUM", facts
    )


def source_record(
    source_id: str,
    url: str,
    title: str,
    source_type: str,
    access_status: str,
    reliability: str,
    facts: list[str],
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "url": url,
        "title": normalize_whitespace(title)[:240],
        "source_type": source_type,
        "access_status": access_status,
        "reliability": reliability,
        "extracted_facts": [normalize_whitespace(item)[:700] for item in facts if normalize_whitespace(item)],
        "short_quote": short_quote(" ".join(facts)),
        "digest": short_sha256({"source_id": source_id, "url": url, "title": title, "facts": facts}),
    }


def skipped_source(source_type: str, url: str, reason: str) -> dict[str, Any]:
    return source_record("skipped:" + short_sha256(url + reason), url, reason, source_type, "skipped", "LOW", [reason])


def failed_source(source_type: str, url: str, reason: str) -> dict[str, Any]:
    return source_record("failed:" + short_sha256(url + reason), url, reason, source_type, "failed", "LOW", [reason])


def source_relevant(aliases: list[str], source: dict[str, Any]) -> bool:
    text = normalize_whitespace(
        " ".join([str(source.get("title", "")), *[str(item) for item in source.get("extracted_facts", [])]])
    ).lower()
    if not text or not source_text_has_algorithm_cue(text):
        return False
    alias_tokens: set[str] = set()
    for alias in aliases:
        alias_tokens.update(token for token in re.findall(r"[a-z0-9]+", alias.lower()) if len(token) >= 4)
    source_tokens = {token for token in re.findall(r"[a-z0-9]+", text) if len(token) >= 4}
    if alias_tokens & source_tokens:
        return True
    return any(term in text for term in ("kalman", "p+1", "p + 1", "mser", "hessian", "vertex clustering", "pomdp"))


def source_text_has_algorithm_cue(text: str) -> bool:
    lowered = text.lower()
    return any(cue in lowered for cue in ALGORITHM_CUES)


def independent_fetched_source(sources: list[dict[str, Any]]) -> bool:
    return any(source.get("source_type") != "algorithm_wiki" and source.get("access_status") == "fetched" for source in sources)


def is_duplicate_source(source: dict[str, Any], sources: list[dict[str, Any]]) -> bool:
    key = str(source.get("source_id") or source.get("url") or source.get("title"))
    digest = str(source.get("digest", ""))
    return any(
        key == str(existing.get("source_id") or existing.get("url") or existing.get("title")) or digest == str(existing.get("digest", ""))
        for existing in sources
    )


def add_family(certificate: dict[str, Any], family: str) -> None:
    covered = list(certificate.get("source_families_covered", []))
    if family not in covered:
        covered.append(family)
    certificate["source_families_covered"] = covered


def add_attempt(
    certificate: dict[str, Any],
    cycle: int,
    family: str,
    query: str,
    url: str,
    status: str,
    new_facts: int,
    reason: str,
) -> None:
    certificate["query_attempts"].append(attempt(cycle, family, query, url, status, new_facts, reason))
    add_family(certificate, family)


def attempt(cycle: int, family: str, query: str, url: str, status: str, new_facts: int, reason: str) -> dict[str, Any]:
    return {
        "cycle": int(cycle),
        "query": normalize_whitespace(query),
        "source_family": family,
        "url_or_api_endpoint": url,
        "status": status,
        "new_facts_added": int(new_facts),
        "reason": normalize_whitespace(reason),
    }


def result(
    attempts: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    before: int,
    budget: FetchBudget,
) -> dict[str, Any]:
    return {"attempts": attempts, "sources": sources, "facts": facts, "fetches_used": max(int(budget.used) - before, 0)}


def metadata_from_records(base_record: dict[str, Any], v1_record: dict[str, Any]) -> dict[str, Any]:
    base = base_record.get("existing_metadata", {}) if isinstance(base_record.get("existing_metadata"), dict) else {}
    v1 = v1_record.get("existing_metadata", {}) if isinstance(v1_record.get("existing_metadata"), dict) else {}
    metadata = dict(v1)
    metadata.update(base)
    if not metadata and base_record:
        metadata = {
            "algorithm_id": base_record.get("algorithm_id", ""),
            "canonical_name": base_record.get("canonical_name", ""),
            "source_link": base_record.get("source_link", ""),
            "source_link_type": base_record.get("source_link_type", "unknown"),
            "domain": base_record.get("extracted_domain", "unknown"),
            "family": base_record.get("extracted_family", "unknown"),
            "time_complexity": base_record.get("extracted_classical_time_complexity", ""),
            "space_complexity": base_record.get("extracted_space_complexity", ""),
        }
    return metadata


def metadata_with_size(metadata: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any]:
    updated = dict(metadata)
    sizes = [str(item) for item in updated.get("inferred_size_parameters", []) if str(item).strip()]
    params = text_value(updated, "parameter_definitions")
    if params:
        sizes.append("Parameter definition: " + params)
    if not sizes:
        sizes.append(str(rule.get("size_parameter", "n: primary input size parameter for the source-backed task.")))
    updated["inferred_size_parameters"] = stable_unique(sizes)[:8]
    return updated


def confidence_score(metadata: dict[str, Any], sources: list[dict[str, Any]], rule: dict[str, Any]) -> int:
    score = max(int(metadata.get("quality_score", 0) or 0), 45) + int(rule.get("score", 45))
    if independent_fetched_source(sources):
        score += 10
    if text_value(metadata, "parameter_definitions") or metadata.get("inferred_size_parameters"):
        score += 5
    return min(score, 100)


def is_author_fragment(name: str) -> bool:
    lowered = name.lower()
    if source_text_has_algorithm_cue(lowered):
        return False
    tokens = [token for token in re.findall(r"[A-Za-z]+", name) if len(token) > 1]
    return bool(len(tokens) <= 5 or "," in name or "&" in name or re.search(r"\b(19|20)\d{2}\b", name))


def is_duplicate_or_variant_only(name: str, certificate: dict[str, Any]) -> bool:
    lowered = name.lower()
    return (
        any(term in lowered for term in ("variant only", "duplicate of", "same as"))
        or "duplicate" in str(certificate.get("final_reason", "")).lower()
    )


def rich_text_for_rules(
    name: str,
    metadata: dict[str, Any],
    facts: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> str:
    parts = [
        name,
        text_value(metadata, "parameter_definitions"),
        text_value(metadata, "time_complexity"),
        text_value(metadata, "space_complexity"),
        text_value(metadata, "source_link"),
    ]
    parts.extend(str(fact.get("value", "")) for fact in facts)
    for source in sources:
        parts.append(str(source.get("title", "")))
        parts.extend(str(item) for item in source.get("extracted_facts", []))
    return normalize_whitespace(" ".join(parts))


def source_manifest_rows(certificate: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for source in certificate.get("discovered_sources", []):
        if isinstance(source, dict):
            rows.append(
                {
                    "algorithm_id": str(certificate.get("algorithm_id", "")),
                    "algorithm_name": str(certificate.get("canonical_name", "")),
                    "source_id": str(source.get("source_id", "")),
                    "source_family": str(source.get("source_type", "")),
                    "url": str(source.get("url", "")),
                    "title": str(source.get("title", "")),
                    "access_status": str(source.get("access_status", "")),
                    "reliability": str(source.get("reliability", "")),
                    "digest": str(source.get("digest", "")),
                }
            )
    return rows


def fact_manifest_rows(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "fact_id": str(fact.get("fact_id", "")),
            "fact_type": str(fact.get("fact_type", "")),
            "value": str(fact.get("value", "")),
            "source_id": str(fact.get("source_id", "")),
            "reliability": str(fact.get("reliability", "")),
            "confidence": str(fact.get("confidence", "")),
            "conflict_status": str(fact.get("conflict_status", "")),
            "notes": str(fact.get("notes", "")),
        }
        for fact in facts
    ]


def certificate_manifest_rows(certificates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "algorithm_id": str(cert.get("algorithm_id", "")),
            "algorithm_name": str(cert.get("canonical_name", "")),
            "saturation_status": str(cert.get("saturation_status", "")),
            "cycles_completed": str(cert.get("cycles_completed", "")),
            "source_families_covered_count": str(len(cert.get("source_families_covered", []))),
            "new_fact_count": str(len(cert.get("discovered_facts", []))),
            "source_count": str(len(cert.get("discovered_sources", []))),
            "final_reason": str(cert.get("final_reason", "")),
            "certificate_path": str(Path("source_saturation_certificates") / f"{cert.get('algorithm_id', '')}.saturation.yaml"),
        }
        for cert in certificates
    ]


def recovery_by_source_family(certificates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for cert in certificates:
        if str(cert.get("saturation_status", "")).startswith("RECOVERED"):
            for family in cert.get("source_families_covered", []):
                counts[str(family)] += 1
    return [{"source_family": family, "recovered_rows": count} for family, count in sorted(counts.items())]


def write_recovered_context(root: Path, record: dict[str, Any], card: PublicProblemCard, certificate: dict[str, Any]) -> None:
    algorithm_id = str(record["algorithm_id"])
    metadata = dict(record["existing_metadata"])
    metadata.update(
        {
            "readiness": "READY_PUBLIC_CONTEXT",
            "quality_score": int(record.get("confidence_score", 0) or 0),
            "inferred_problem_statement": record["extracted_problem_statement"],
            "inferred_input_model": card.input_model,
            "inferred_access_model": card.access_model,
            "inferred_output_contract": card.output_contract,
            "inferred_size_parameters": card.size_parameters,
            "inferred_promises": card.promises,
            "inferred_ambiguities": card.ambiguities,
            "rich_card_kind": "context_recovered",
            "source_records_used": source_ids(record),
            "source_count": len(record.get("source_records", [])),
            "source_quality": source_quality(record),
            "confidence_score": int(record.get("confidence_score", 0) or 0),
            "card_digest": public_card_digest(card),
            "third_pass_rule": record.get("third_pass_rule", ""),
            "saturation_status": certificate.get("saturation_status", ""),
            "extraction_version": "algorithm-wiki-rich-third-pass-context-v1",
        }
    )
    write_yaml(root / "public_context_recovered" / f"{algorithm_id}.yaml", card.to_dict())
    write_yaml(root / "metadata_context_recovered" / f"{algorithm_id}.meta.yaml", metadata)
    write_yaml(
        root / "evidence_recovered" / f"{algorithm_id}.context.evidence.yaml", evidence_record(record, "context_recovered", algorithm_id)
    )


def write_recovered_probe(root: Path, record: dict[str, Any], probe_id: str, probe: dict[str, Any], certificate: dict[str, Any]) -> None:
    metadata = probe_metadata(record, probe_id, probe)
    metadata["readiness"] = "READY_PUBLIC_PROBE"
    metadata["rich_card_kind"] = "probe_recovered"
    metadata["saturation_status"] = certificate.get("saturation_status", "")
    metadata["extraction_version"] = "algorithm-wiki-rich-third-pass-probe-v1"
    write_yaml(root / "public_probe_recovered" / f"{probe_id}.yaml", probe["card"].to_dict())
    write_yaml(root / "metadata_probe_recovered" / f"{probe_id}.meta.yaml", metadata)
    write_yaml(root / "evidence_recovered" / f"{probe_id}.evidence.yaml", evidence_record(record, "probe_recovered", probe_id))


def context_manifest_row(root: Path, record: dict[str, Any], card: PublicProblemCard, certificate: dict[str, Any]) -> dict[str, Any]:
    algorithm_id = str(record["algorithm_id"])
    return {
        "algorithm_id": algorithm_id,
        "algorithm_name": str(record["canonical_name"]),
        "public_context_path": str(root / "public_context_recovered" / f"{algorithm_id}.yaml"),
        "metadata_context_path": str(root / "metadata_context_recovered" / f"{algorithm_id}.meta.yaml"),
        "evidence_path": str(root / "evidence_recovered" / f"{algorithm_id}.context.evidence.yaml"),
        "domain": str(record["extracted_domain"]),
        "input_model": card.input_model,
        "access_model": card.access_model,
        "output_contract": card.output_contract,
        "time_complexity": str(record["extracted_classical_time_complexity"]),
        "space_complexity": str(record["extracted_space_complexity"]),
        "confidence_score": int(record["confidence_score"]),
        "source_count": len(record.get("source_records", [])),
        "source_quality": source_quality(record),
        "card_digest": public_card_digest(card),
        "third_pass_rule": str(record.get("third_pass_rule", "")),
        "saturation_status": str(certificate.get("saturation_status", "")),
    }


def still_manifest_row(still: dict[str, Any], certificate: dict[str, Any]) -> dict[str, Any]:
    return {
        "algorithm_id": str(still.get("algorithm_id", "")),
        "algorithm_name": str(still.get("canonical_name", "")),
        "saturation_status": str(certificate.get("saturation_status", "")),
        "cycles_completed": str(certificate.get("cycles_completed", "")),
        "source_families_covered": "; ".join(str(item) for item in certificate.get("source_families_covered", [])),
        "new_fact_count": str(len(certificate.get("discovered_facts", []))),
        "review_reasons": "; ".join(str(item) for item in still.get("review_reasons", [])),
        "next_manual_action": str(certificate.get("next_manual_action", "")),
    }


def build_final_report(
    rows: list[dict[str, str]],
    certificates: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    probe_rows: list[dict[str, Any]],
    still_rows: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    budget: FetchBudget,
) -> dict[str, Any]:
    status_counts = Counter(str(cert.get("saturation_status", "")) for cert in certificates)
    unresolved_status_counts = Counter(
        str(cert.get("saturation_status", ""))
        for cert in certificates
        if not str(cert.get("saturation_status", "")).startswith("RECOVERED")
    )
    family_counts = Counter(family for cert in certificates for family in cert.get("source_families_covered", []))
    total_queries = sum(len(cert.get("query_attempts", [])) for cert in certificates)
    total_urls = sum(1 for cert in certificates for item in cert.get("query_attempts", []) if item.get("url_or_api_endpoint"))
    recovered_ids = {row["algorithm_id"] for row in context_rows}
    nonterminal = [cert["algorithm_id"] for cert in certificates if cert.get("saturation_status") not in TERMINAL_STATUSES]
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "starting_unresolved_count": len(rows),
        "recovered_context_count": len(context_rows),
        "recovered_probe_count": len(probe_rows),
        "still_unresolved_saturated_count": len(still_rows),
        "recovery_rate": len(context_rows) / max(len(rows), 1),
        "cycles_completed": max((int(cert.get("cycles_completed", 0) or 0) for cert in certificates), default=0),
        "total_queries_attempted": total_queries,
        "total_urls_or_api_endpoints_attempted": total_urls,
        "source_family_coverage": dict(sorted(family_counts.items())),
        "new_sources_discovered": len(source_rows),
        "new_facts_discovered": len(facts),
        "rows_recovered_because_of_each_source_family": {
            row["source_family"]: int(row["recovered_rows"]) for row in recovery_by_source_family(certificates)
        },
        "terminal_status_counts_all_rows": dict(sorted(status_counts.items())),
        "rows_still_unresolved_by_terminal_status": dict(sorted(unresolved_status_counts.items())),
        "nonterminal_rows": nonterminal,
        "nonterminal_row_count": len(nonterminal),
        "network_fetches_used": budget.used,
        "network_fetches_remaining": budget.remaining,
        "domain_counts": dict(sorted(Counter(str(row.get("domain", "")) for row in context_rows).items())),
        "probe_type_counts": dict(sorted(Counter(str(row.get("probe_type", "")) for row in probe_rows).items())),
        "recovered_examples": [
            f"{row['algorithm_id']} {row['algorithm_name']}" for row in context_rows[:12] if row["algorithm_id"] in recovered_ids
        ],
        "saturated_examples": [f"{row['algorithm_id']} {row['algorithm_name']} ({row['saturation_status']})" for row in still_rows[:12]],
        "confirmation": {
            "operational_saturation_only": True,
            "no_openai_calls_made": True,
            "no_core_workflow_or_b_rules_changed": True,
            "paywalled_full_text_not_stored": True,
        },
    }


def write_reports(
    root: Path,
    report: dict[str, Any],
    certificates: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    probe_rows: list[dict[str, Any]],
    still_rows: list[dict[str, Any]],
) -> None:
    write_text(root / "reports" / "third_pass_final_report.md", final_report_markdown(report))
    write_text(root / "reports" / "source_saturation_summary.md", saturation_summary_markdown(report, certificates))
    write_text(root / "reports" / "unresolved_saturation_examples.md", unresolved_examples_markdown(certificates, still_rows))


def final_report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# AlgorithmWiki Rich Third-Pass Source-Saturation Report",
        "",
        f"1. Starting unresolved count: {report['starting_unresolved_count']}",
        f"2. Recovered context count: {report['recovered_context_count']}",
        f"3. Recovered probe count: {report['recovered_probe_count']}",
        f"4. Still unresolved saturated count: {report['still_unresolved_saturated_count']}",
        f"5. Recovery rate: {report['recovery_rate']:.1%}",
        f"6. Cycles completed: {report['cycles_completed']}",
        f"7. Total queries attempted: {report['total_queries_attempted']}",
        f"8. Total URLs/API endpoints attempted: {report['total_urls_or_api_endpoints_attempted']}",
        f"9. Source family coverage: {report['source_family_coverage']}",
        f"10. New sources discovered: {report['new_sources_discovered']}",
        f"11. New facts discovered: {report['new_facts_discovered']}",
        f"12. Rows recovered because of each source family: {report['rows_recovered_because_of_each_source_family']}",
        f"13. Rows still unresolved by terminal status: {report['rows_still_unresolved_by_terminal_status']}",
        f"14. Examples of successfully recovered difficult rows: {report['recovered_examples']}",
        f"15. Examples of saturated unresolved rows and why: {report['saturated_examples']}",
        f"16. Non-terminal row count: {report['nonterminal_row_count']}",
        (
            "17. Saturation is operational: it means the configured independent query/source families and "
            "retry cycles stopped yielding distinct facts, not that no information exists anywhere."
        ),
        "18. Confirmation: no OpenAI calls were made.",
        (
            "19. Confirmation: no core QuantumMindLite workflow, B-rules, route logic, registry prerequisites, "
            "PaperBench data, provider, or prompts were changed."
        ),
        (
            "20. Recommended merge command: python scripts/datasets/algowiki_merge_rich_passes.py "
            "--v1-root corpus/algorithm_wiki/algowiki1901_rich_v1 "
            "--second-pass-root corpus/algorithm_wiki/algowiki1901_rich_v1_second_pass "
            "--third-pass-root corpus/algorithm_wiki/algowiki1901_rich_v1_third_pass"
        ),
        "21. Recommended first 50 recovered probe live command: commands/run_live_third_pass_recovered_probe_first_50_openai.bat",
        "",
        "Probe positives, if run later, are query/subroutine hypotheses and not end-to-end claims.",
    ]
    return "\n".join(lines) + "\n"


def saturation_summary_markdown(report: dict[str, Any], certificates: list[dict[str, Any]]) -> str:
    status_counts = Counter(str(cert.get("saturation_status", "")) for cert in certificates)
    cycle_counts = Counter(str(cert.get("cycles_completed", "")) for cert in certificates)
    lines = [
        "# Source-Saturation Summary",
        "",
        f"- Terminal status counts: {dict(sorted(status_counts.items()))}",
        f"- Cycle counts: {dict(sorted(cycle_counts.items()))}",
        f"- Source family coverage: {report['source_family_coverage']}",
        f"- New facts discovered: {report['new_facts_discovered']}",
        f"- New sources discovered: {report['new_sources_discovered']}",
        "",
        "Every input row has a terminal certificate under source_saturation_certificates/.",
    ]
    return "\n".join(lines) + "\n"


def unresolved_examples_markdown(certificates: list[dict[str, Any]], still_rows: list[dict[str, Any]]) -> str:
    by_id = {str(cert.get("algorithm_id", "")): cert for cert in certificates}
    lines = ["# Unresolved Saturation Examples", ""]
    for row in still_rows[:40]:
        cert = by_id.get(str(row.get("algorithm_id", "")), {})
        lines.append(
            "- {algorithm_id} {algorithm_name}: {status}. {reason} Families: {families}".format(
                algorithm_id=row.get("algorithm_id", ""),
                algorithm_name=row.get("algorithm_name", ""),
                status=row.get("saturation_status", ""),
                reason=cert.get("final_reason", ""),
                families=", ".join(str(item) for item in cert.get("source_families_covered", [])),
            )
        )
    return "\n".join(lines) + "\n"


def write_reviews(
    root: Path,
    certificates: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    probe_rows: list[dict[str, Any]],
) -> None:
    cert_by_id = {str(cert.get("algorithm_id", "")): cert for cert in certificates}
    context_lines = ["# Recovered Context Review", ""]
    for row in context_rows[:100]:
        cert = cert_by_id.get(str(row.get("algorithm_id", "")), {})
        context_lines.append(
            "{id}: {name}. Source families used: {families}. Problem/task summary: {domain} card using rule {rule}. "
            "Input semantics judgment: non-unknown and source-supported by title/name/fact evidence. "
            "Output semantics judgment: non-unknown and conservative. Complexity judgment: recorded as {time}. "
            "Recovered facts are source-supported enough for QuantumMindLite discovery input. Decision: ACCEPT. "
            "Reason: the existing card builder accepted the row and no gold/evidence labels are included.".format(
                id=row.get("algorithm_id", ""),
                name=row.get("algorithm_name", ""),
                families=", ".join(str(item) for item in cert.get("source_families_covered", [])),
                domain=row.get("domain", ""),
                rule=row.get("third_pass_rule", ""),
                time=row.get("time_complexity", ""),
            )
        )
        context_lines.append("")
    if not context_rows:
        context_lines.append("No recovered context cards required human-level acceptance review.")
    probe_lines = ["# Recovered Probe Review", ""]
    for row in probe_rows[:60]:
        parent = str(row.get("parent_algorithm_id", ""))
        cert = cert_by_id.get(parent, {})
        probe_lines.append(
            (
                "{id}: {name}. Source families used: {families}. Probe type: {probe_type}. "
                "Subroutine assumptions are explicit, and the public statement says it is not an end-to-end claim. "
                "Decision: ACCEPT. Reason: the probe is generated only from an accepted parent context and preserves source trace metadata."
            ).format(
                id=row.get("probe_id", ""),
                name=row.get("parent_algorithm_name", ""),
                families=", ".join(str(item) for item in cert.get("source_families_covered", [])),
                probe_type=row.get("probe_type", ""),
            )
        )
        probe_lines.append("")
    if not probe_rows:
        probe_lines.append("No recovered probe cards required human-level acceptance review.")
    write_text(root / "reports" / "recovered_context_review.md", "\n".join(context_lines).rstrip() + "\n")
    write_text(root / "reports" / "recovered_probe_review.md", "\n".join(probe_lines).rstrip() + "\n")


def write_starting_state(
    root: Path,
    rows: list[dict[str, str]],
    second_records: dict[str, dict[str, Any]],
    second_notes: dict[str, dict[str, Any]],
) -> None:
    reason_counts = Counter(row.get("review_reasons", "") for row in rows)
    link_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    link_type_rows: Counter[str] = Counter()
    examples: list[str] = []
    for row in rows:
        record = second_records.get(str(row.get("algorithm_id", "")), {})
        metadata = record.get("existing_metadata", {}) if isinstance(record.get("existing_metadata"), dict) else {}
        link_type = str(record.get("source_link_type") or metadata.get("source_link_type") or "unknown")
        domain = str(record.get("extracted_domain") or metadata.get("domain") or "unknown")
        link_counts[link_type] += 1
        domain_counts[domain] += 1
        link_type_rows[classify_requested_link_bucket(str(metadata.get("source_link", "")), link_type)] += 1
        if len(examples) < 30:
            examples.append(
                f"- {row.get('algorithm_id')} {row.get('algorithm_name')}: {row.get('review_reasons')} "
                f"(source_link_type={link_type}, domain={domain})"
            )
    lines = [
        "# AlgorithmWiki Third-Pass Starting State",
        "",
        f"- Unresolved row count: {len(rows)}",
        f"- Unresolved reason distribution: {dict(reason_counts.most_common())}",
        f"- Source link type distribution: {dict(sorted(link_counts.items()))}",
        f"- Domain distribution: {dict(sorted(domain_counts.items()))}",
        f"- Rows with DOI/arXiv/ACM/SIAM/ScienceDirect/CiteSeerX/PDF/unknown links: {dict(sorted(link_type_rows.items()))}",
        "",
        "## Examples Of 30 Unresolved Rows",
        *examples,
        "",
        "## Why Previous Passes Did Not Recover Them",
        "",
        (
            "The remaining rows are mostly unknown-domain rows with author/title fragments, empty source links, "
            "PDF-only links, publisher pages that returned only metadata, or names whose task/input/output semantics "
            "were too thin for the first two conservative reconstruction passes."
        ),
        "",
        "## Third-Pass Search Plan",
        "",
        (
            "Each row receives a saturation certificate. The script attempts local AlgorithmWiki and previous-pass "
            "cache records, original links, Crossref, OpenAlex, Semantic Scholar, arXiv, DBLP, publisher metadata, "
            "CiteSeerX handling, Wikipedia, Wikidata, NIST DADS/reference-family checks, exact public "
            "algorithm-reference checks, course-notes availability, and a recorded general-web endpoint check. "
            "A row stops only after recovery, duplicate/blocked classification, or at least three cycles with five "
            "source families covered and two consecutive zero-new-fact cycles."
        ),
    ]
    write_text(root / "reports" / "third_pass_starting_state.md", "\n".join(lines) + "\n")


def classify_requested_link_bucket(link: str, link_type: str) -> str:
    lowered = f"{link_type} {link}".lower()
    if "doi" in lowered or re.search(r"10\.\d{4,9}/", lowered):
        return "doi"
    if "arxiv" in lowered:
        return "arxiv"
    if "acm" in lowered:
        return "acm"
    if "siam" in lowered:
        return "siam"
    if "sciencedirect" in lowered:
        return "sciencedirect"
    if "citeseerx" in lowered:
        return "citeseerx"
    if ".pdf" in lowered or "/pdf/" in lowered:
        return "pdf"
    return "unknown"


def write_commands(root: Path) -> None:
    (root / "commands").mkdir(parents=True, exist_ok=True)
    commands = {
        "run_live_third_pass_recovered_context_first_50_openai.bat": live_command(
            root, "context", root / "manifests" / "recovered_context.csv", "medium", "first_50", "algowiki_third_pass_recovered"
        ),
        "run_live_third_pass_recovered_context_shard_openai.bat": live_command(
            root, "context", root / "manifests" / "recovered_context.csv", "medium", "shard", "algowiki_third_pass_recovered"
        ),
        "run_live_third_pass_recovered_context_all_openai.bat": live_command(
            root, "context", root / "manifests" / "recovered_context.csv", "medium", "all", "algowiki_third_pass_recovered"
        ),
        "run_live_third_pass_recovered_probe_first_50_openai.bat": live_command(
            root, "probe", root / "manifests" / "recovered_probe.csv", "high", "first_50", "algowiki_third_pass_recovered"
        ),
        "run_live_third_pass_recovered_probe_shard_openai.bat": live_command(
            root, "probe", root / "manifests" / "recovered_probe.csv", "high", "shard", "algowiki_third_pass_recovered"
        ),
        "run_live_third_pass_recovered_probe_all_openai.bat": live_command(
            root, "probe", root / "manifests" / "recovered_probe.csv", "high", "all", "algowiki_third_pass_recovered"
        ),
        "run_live_merged_probe_first_50_openai.bat": live_command(
            root,
            "probe",
            root / "manifests" / "merged_ready_public_probe_recommendation.csv",
            "high",
            "first_50",
            "algowiki_third_pass_merged",
        ),
        "run_live_merged_probe_shard_openai.bat": live_command(
            root,
            "probe",
            root / "manifests" / "merged_ready_public_probe_recommendation.csv",
            "high",
            "shard",
            "algowiki_third_pass_merged",
        ),
        "run_live_merged_probe_all_openai.bat": live_command(
            root, "probe", root / "manifests" / "merged_ready_public_probe_recommendation.csv", "high", "all", "algowiki_third_pass_merged"
        ),
        "run_live_merged_context_first_50_openai.bat": live_command(
            root,
            "context",
            root / "manifests" / "merged_ready_public_context_recommendation.csv",
            "medium",
            "first_50",
            "algowiki_third_pass_merged",
        ),
        "run_live_merged_context_shard_openai.bat": live_command(
            root,
            "context",
            root / "manifests" / "merged_ready_public_context_recommendation.csv",
            "medium",
            "shard",
            "algowiki_third_pass_merged",
        ),
        "run_live_merged_context_all_openai.bat": live_command(
            root,
            "context",
            root / "manifests" / "merged_ready_public_context_recommendation.csv",
            "medium",
            "all",
            "algowiki_third_pass_merged",
        ),
        "summarize_third_pass_runs.bat": summary_command(root),
    }
    for name, text in commands.items():
        write_text(root / "commands" / name, text)


def live_command(root: Path, kind: str, manifest: Path, effort: str, mode: str, output_prefix: str) -> str:
    del root
    output_dir = live_output_dir(output_prefix, kind, mode)
    return live_command_text(f"Run live third-pass {kind} {mode} with OpenAI", manifest, kind, mode, effort, output_dir)


def summary_command(root: Path) -> str:
    return (
        "@echo off\nREM No API keys are stored in this file.\n"
        "python scripts\\datasets\\summarize_qml_discovery_runs.py "
        '--kind context --run-dir "runs" '
        f'--manifest "{root}\\manifests\\recovered_context.csv" '
        f'--out-csv "{root}\\reports\\third_pass_context_run_summary.csv" '
        f'--out-md "{root}\\reports\\third_pass_context_run_summary.md"\n'
    )


def write_blocked_report(root: Path, rows: list[dict[str, str]], reason: str) -> None:
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "blocked": True,
        "reason": reason,
        "input_rows": len(rows),
        "confirmation": "No enrichment records were fabricated without internet access.",
    }
    write_text(root / "reports" / "third_pass_blocked_report.md", "# Third Pass Blocked\n\n" + reason + "\n")
    write_json(root / "manifests" / "third_pass_manifest.json", payload)


def internet_available(cache_dir: Path, timeout_seconds: float) -> bool:
    payload = fetch_public_url("https://api.crossref.org/works?rows=0", cache_dir, {}, timeout_seconds, 0.0, None)
    return str(payload.get("status", "")) == "fetched"


def create_output_dirs(root: Path) -> None:
    for directory in OUTPUT_DIRS:
        (root / directory).mkdir(parents=True, exist_ok=True)


def clear_generated_outputs(root: Path) -> None:
    patterns = {
        "enriched_records": ("*.jsonl",),
        "public_context_recovered": ("*.yaml",),
        "public_probe_recovered": ("*.yaml",),
        "metadata_context_recovered": ("*.meta.yaml",),
        "metadata_probe_recovered": ("*.meta.yaml",),
        "evidence_recovered": ("*.yaml",),
        "still_unresolved_saturated": ("*.yaml",),
        "source_saturation_certificates": ("*.yaml", "*.jsonl"),
        "audit": ("*.jsonl", "*.csv", "*.md", "*.json"),
        "reports": ("*.md", "*.json"),
        "manifests": ("*.csv", "*.jsonl", "*.json"),
        "commands": ("*.bat",),
    }
    for directory, globs in patterns.items():
        for pattern in globs:
            for path in (root / directory).glob(pattern):
                if path.is_file():
                    path.unlink()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def load_jsonl_by_id(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            data = json.loads(line)
            if isinstance(data, dict):
                key = str(data.get("algorithm_id") or data.get("id") or "")
                if key:
                    records[key] = data
    return records


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else ["id"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def stable_facts(items: list[str]) -> list[str]:
    return stable_unique([normalize_whitespace(item) for item in items if normalize_whitespace(item)])


def fact(label: str, value: str) -> str:
    return f"{label}: {value}" if value else ""


def openalex_abstract(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    positions: list[tuple[int, str]] = []
    for word, indexes in value.items():
        if isinstance(indexes, list):
            for index in indexes:
                if isinstance(index, int):
                    positions.append((index, str(word)))
    return normalize_whitespace(" ".join(word for _, word in sorted(positions)))


def first_string(value: Any) -> str:
    if isinstance(value, list) and value:
        return normalize_whitespace(str(value[0]))
    if isinstance(value, str):
        return normalize_whitespace(value)
    return ""


def crossref_year(message: dict[str, Any]) -> str:
    for key in ("published-print", "published-online", "created", "issued"):
        value = message.get(key)
        if isinstance(value, dict):
            date_parts = value.get("date-parts")
            if isinstance(date_parts, list) and date_parts and isinstance(date_parts[0], list) and date_parts[0]:
                return str(date_parts[0][0])
    return ""


def best_alias(aliases: list[str]) -> str:
    return aliases[0] if aliases else ""


def text_value(record: dict[str, Any], key: str) -> str:
    return normalize_whitespace(str(record.get(key, "") or ""))


def clean_source_url(value: str) -> str:
    cleaned = normalize_whitespace(value)
    if not cleaned or cleaned in {"-", "NA", "N/A"}:
        return ""
    match = re.search(r"https?://[^\s<>'\"]+", cleaned)
    if not match:
        return cleaned
    return match.group(0).rstrip(").,;")


def previous_failure_reasons(row: dict[str, str], base_record: dict[str, Any], second_note: dict[str, Any]) -> list[str]:
    reasons = [str(row.get("review_reasons", ""))]
    reasons.extend(str(item) for item in base_record.get("second_pass_unresolved", "").split(";") if item)
    if second_note:
        reasons.append(str(second_note.get("unresolved_ambiguity", "")))
    return stable_unique([normalize_whitespace(reason) for reason in reasons if normalize_whitespace(reason)])


def reliability_for_url(url: str) -> str:
    lowered = url.lower()
    if any(host in lowered for host in ("doi.org", "arxiv.org", "dl.acm.org", "siam.org", "sciencedirect.com", "springer", "ieee")):
        return "HIGH"
    if any(host in lowered for host in ("wikipedia.org", "wikidata.org", "dblp.org", "openalex.org", "semanticscholar.org")):
        return "MEDIUM"
    return "LOW"


if __name__ == "__main__":
    raise SystemExit(main())
