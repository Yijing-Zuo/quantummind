from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from scripts.datasets.algowiki_common import (  # noqa: E402
    load_jsonl,
    normalize_whitespace,
    short_sha256,
    strip_html,
    write_jsonl,
)

BASE_URL = "https://algorithm-wiki.org"
USER_AGENT = "QuantumMindLite AlgorithmWiki adapter; public metadata curation"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Optionally enrich Algorithm Wiki records from public Algorithm Wiki pages.")
    parser.add_argument("--records", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--max-pages", type=int, default=1901)
    parser.add_argument("--out-report", default="corpus/algorithm_wiki/reports/algowiki_page_enrichment_report.json")
    parser.add_argument("--disable-network", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=0.2)
    args = parser.parse_args(argv)

    records = load_jsonl(Path(args.records))
    if args.disable_network:
        enriched = [with_disabled_page(record) for record in records]
        report = build_report(records, enriched, "network disabled by flag")
    else:
        enriched, report = enrich_records(
            records=records,
            cache_dir=Path(args.cache_dir),
            max_pages=int(args.max_pages),
            sleep_seconds=float(args.sleep_seconds),
        )
    write_jsonl(Path(args.out), enriched)
    report_path = Path(args.out_report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def enrich_records(
    records: list[dict[str, object]],
    cache_dir: Path,
    max_pages: int,
    sleep_seconds: float,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    try:
        download_html = fetch_url(BASE_URL + "/download", cache_dir, sleep_seconds)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        failed_records = [with_fetch_failed(record, str(exc)) for record in records]
        return failed_records, build_report(records, failed_records, f"download page fetch failed: {exc}")

    route_index = build_route_index(download_html, [str(record.get("name", "")) for record in records])
    pages: dict[str, tuple[str, str]] = {}
    enriched: list[dict[str, object]] = []
    page_fetches = 0
    for record in records:
        name = str(record.get("name", ""))
        route = route_index.get(name_key(name), "")
        if not route:
            enriched.append(with_not_found(record))
            continue
        page_url = BASE_URL + route
        if page_url not in pages:
            if page_fetches >= max_pages:
                enriched.append(with_disabled_page(record, page_url, "max page limit reached"))
                continue
            try:
                pages[page_url] = (fetch_url(page_url, cache_dir, sleep_seconds), "found")
                page_fetches += 1
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                pages[page_url] = ("", f"fetch_failed:{exc}")
        html, status = pages[page_url]
        if status != "found":
            enriched.append(with_fetch_failed(record, status, page_url))
            continue
        enriched.append(enrich_from_page(record, page_url, html))
    return enriched, build_report(records, enriched, "ok")


def fetch_url(url: str, cache_dir: Path, sleep_seconds: float) -> str:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{short_sha256(url)}.html"
    if cache_path.exists():
        return str(cache_path.read_text(encoding="utf-8"))
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=20) as response:
        body = str(response.read().decode("utf-8", "replace"))
    cache_path.write_text(body, encoding="utf-8")
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    return body


def build_route_index(download_html: str, names: list[str]) -> dict[str, str]:
    routes = [(match.start(), match.group(1)) for match in re.finditer(r'href="(/domains/[^"]+)"', download_html)]
    if not routes:
        return {}
    lower_html = download_html.lower()
    index: dict[str, str] = {}
    for name in names:
        key = name_key(name)
        if not key or key in index:
            continue
        escaped_name = re.escape(name.lower())
        match = re.search(rf">\s*{escaped_name}\s*<", lower_html)
        if not match:
            match = re.search(escaped_name, lower_html)
        if not match:
            continue
        preceding = [route for position, route in routes if position <= match.start()]
        if preceding:
            index[key] = preceding[-1]
    return index


def enrich_from_page(record: dict[str, object], page_url: str, page_html: str) -> dict[str, object]:
    domain, family, variation = parse_route(page_url)
    text = normalize_whitespace(strip_html(page_html))
    enriched = dict(record)
    enriched.update(
        {
            "page_url": page_url,
            "page_fetch_status": "found",
            "page_digest": short_sha256(page_html),
            "extracted_description": page_description(text, variation),
            "page_domain": domain,
            "page_family": family,
            "page_variation": variation,
            "page_problem": humanize_slug(variation or family or domain),
        }
    )
    return enriched


def parse_route(page_url: str) -> tuple[str, str, str]:
    match = re.search(r"/domains/([^/]+)/families/([^/]+)/variations/([^/?#]+)", page_url)
    if not match:
        return "", "", ""
    return tuple(humanize_slug(match.group(index)) for index in (1, 2, 3))  # type: ignore[return-value]


def page_description(text: str, variation: str) -> str:
    if not text:
        return ""
    if variation:
        position = text.lower().find(variation.lower())
        if position >= 0:
            return normalize_whitespace(text[position : position + 900])
    return normalize_whitespace(text[:900])


def humanize_slug(value: str) -> str:
    return normalize_whitespace(re.sub(r"[-_]+", " ", value)).title()


def name_key(name: str) -> str:
    return normalize_whitespace(re.sub(r"\s+", " ", name.strip().lower()))


def with_disabled_page(record: dict[str, object], page_url: str = "", reason: str = "") -> dict[str, object]:
    enriched = dict(record)
    enriched.update(
        {
            "page_url": page_url,
            "page_fetch_status": "disabled",
            "page_digest": "",
            "extracted_description": "",
            "page_domain": "",
            "page_family": "",
            "page_variation": "",
            "page_problem": "",
            "page_enrichment_note": reason,
        }
    )
    return enriched


def with_not_found(record: dict[str, object]) -> dict[str, object]:
    enriched = dict(record)
    enriched.update(
        {
            "page_url": "",
            "page_fetch_status": "not_found",
            "page_digest": "",
            "extracted_description": "",
            "page_domain": "",
            "page_family": "",
            "page_variation": "",
            "page_problem": "",
        }
    )
    return enriched


def with_fetch_failed(record: dict[str, object], error: str, page_url: str = "") -> dict[str, object]:
    enriched = dict(record)
    enriched.update(
        {
            "page_url": page_url,
            "page_fetch_status": "fetch_failed",
            "page_digest": "",
            "extracted_description": "",
            "page_domain": "",
            "page_family": "",
            "page_variation": "",
            "page_problem": "",
            "page_enrichment_error": error,
        }
    )
    return enriched


def build_report(records: list[dict[str, object]], enriched: list[dict[str, object]], note: str) -> dict[str, object]:
    counts: dict[str, int] = {}
    for record in enriched:
        status = str(record.get("page_fetch_status", "disabled"))
        counts[status] = counts.get(status, 0) + 1
    return {
        "input_records": len(records),
        "output_records": len(enriched),
        "status_counts": counts,
        "note": note,
    }


if __name__ == "__main__":
    raise SystemExit(main())
