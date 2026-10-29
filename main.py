"""Download public CPD cooperative dashboard statistics to JSON and CSV.

Run: python main.py
No third-party packages are required (Python 3.9+).
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_BASE = "https://bigdata_api.cpd.go.th/apitest/"
ICT = timezone(timedelta(hours=7))
LOG = logging.getLogger("cpd")

# Derived from the Angular CoopServiceService in the supplied main.*.js.
# mode=none: the website does NOT append year or sector parameters.
# mode=numeric: sector is 0/1/2; mode=text: sector is Thai text/null.
ENDPOINTS = {
    "cooperatives": ("api/CoopProfile/GetCoopOracleCountNEW", "none"),
    "members": ("api/Member/GetCoopSumMemberNew", "numeric"),
    "committees": ("api/CoopCommittee/GetCoopSumCommitteeNew", "numeric"),
    "officers": ("api/ProfileData/GetCoopSumOfficer", "text"),
    "types": ("api/CoopProfile/GetCoopOracleTypesNEW", "numeric"),
    "strength": ("api/CoopProfile/GetCoopTypeLevelCount", "numeric"),
    "provinces": ("api/ProfileData/GetOracleSumProvinceYearSearch", "none"),
}
CORE = ("cooperatives", "members", "committees", "officers")
TYPE_NAMES = {
    "1": "สหกรณ์การเกษตร", "2": "สหกรณ์ประมง", "3": "สหกรณ์นิคม",
    "4": "สหกรณ์ออมทรัพย์", "5": "สหกรณ์ร้านค้า", "6": "สหกรณ์บริการ",
    "7": "สหกรณ์เครดิตยูเนี่ยน",
}
TEXT_SECTORS = {"0": "null", "1": "สหกรณ์ภาคการเกษตร", "2": "สหกรณ์นอกภาคการเกษตร"}
SUMMARY_FIELDS = [
    "selected_year_be", "sector", "scope", "coop_total", "coop_active",
    "coop_inactive", "member_male", "member_female", "member_total",
    "committee_male", "committee_female", "committee_total",
    "officer_male", "officer_female", "officer_total",
    "coop_year_sector_filtered", "retrieved_at_ict", "source_base_url",
]


def current_year_be() -> int:
    """Match the dashboard's default: previous Gregorian year + 543."""
    return datetime.now(ICT).year + 542


def build_url(base: str, name: str, year: int, sector: str) -> str:
    path, mode = ENDPOINTS[name]
    url = base.rstrip("/") + "/" + path
    if mode == "none":
        return url
    params = {"year": str(year), "sector": TEXT_SECTORS[sector] if mode == "text" else sector}
    return url + "?" + urlencode(params)


def parse_count(value: Any, field: str) -> int:
    """Never silently convert absent or non-integral counts to zero."""
    if value is None or isinstance(value, bool):
        raise ValueError(f"missing/invalid {field}: {value!r}")
    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"non-integral {field}: {value!r}")
        number = int(value)
    elif isinstance(value, str) and re.fullmatch(r"[0-9][0-9,]*", value.strip()):
        number = int(value.strip().replace(",", ""))
    else:
        raise ValueError(f"invalid {field}: {value!r}")
    if number < 0:
        raise ValueError(f"negative {field}: {number}")
    return number


def require_rows(payload: Any, endpoint: str) -> list[dict[str, Any]]:
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"{endpoint}: expected nonempty JSON array, got {type(payload).__name__}")
    if not all(isinstance(x, dict) for x in payload):
        raise ValueError(f"{endpoint}: array contains non-object entries")
    return payload


def gender_totals(rows: list[dict[str, Any]], name: str) -> dict[str, int]:
    result = {"male": 0, "female": 0, "total": 0}
    for index, item in enumerate(rows):
        result["male"] += parse_count(item.get("dataM"), f"{name}[{index}].dataM")
        result["female"] += parse_count(item.get("dataFm"), f"{name}[{index}].dataFm")
        result["total"] += parse_count(item.get("sum"), f"{name}[{index}].sum")
    if result["male"] + result["female"] != result["total"]:
        LOG.warning("%s: male + female differs from total; retaining source values", name)
    return result


def coop_totals(rows: list[dict[str, Any]]) -> dict[str, int]:
    # The website assigns from each row, leaving the *last* row shown.
    item = rows[-1]
    if len(rows) != 1:
        LOG.warning("cooperatives: %s rows returned; using last row like dashboard", len(rows))
    result = {
        "total": parse_count(item.get("coopCount"), "coopCount"),
        "active": parse_count(item.get("active"), "active"),
        "inactive": parse_count(item.get("nonActive"), "nonActive"),
    }
    if result["active"] + result["inactive"] != result["total"]:
        LOG.warning("cooperatives: active + inactive differs from coopCount")
    return result


def build_summary(data: dict[str, list[dict[str, Any]]], year: int, sector: str, at: str, base: str) -> dict[str, Any]:
    summary: dict[str, Any] = {key: "" for key in SUMMARY_FIELDS}
    summary.update({"selected_year_be": year, "sector": sector, "scope": "nationwide",
                    "coop_year_sector_filtered": "no", "retrieved_at_ict": at,
                    "source_base_url": base.rstrip("/") + "/"})
    if "cooperatives" in data:
        coops = coop_totals(require_rows(data["cooperatives"], "cooperatives"))
        summary.update({"coop_total": coops["total"], "coop_active": coops["active"],
                        "coop_inactive": coops["inactive"]})
    for endpoint, prefix in (("members", "member"), ("committees", "committee"), ("officers", "officer")):
        if endpoint in data:
            totals = gender_totals(require_rows(data[endpoint], endpoint), endpoint)
            summary[f"{prefix}_male"] = totals["male"]
            summary[f"{prefix}_female"] = totals["female"]
            summary[f"{prefix}_total"] = totals["total"]
    return summary


def detail_rows(name: str, payload: Any, year: int, sector: str, at: str) -> tuple[list[str], list[dict[str, Any]]]:
    rows = require_rows(payload, name)
    metadata = ["selected_year_be", "sector", "year_sector_filter_applied", "retrieved_at_ict"]
    filtered = name not in ("provinces", "cooperatives")
    prefix = {"selected_year_be": year, "sector": sector,
              "year_sector_filter_applied": "yes" if filtered else "no", "retrieved_at_ict": at}
    if name == "provinces":
        fields = ["province_name", "coop_total", "coop_active", "coop_inactive"]
        def transform(r: dict[str, Any], i: int) -> dict[str, Any]:
            if not r.get("provinceName"):
                raise ValueError(f"provinces[{i}]: missing provinceName")
            return {"province_name": r["provinceName"],
                    "coop_total": parse_count(r.get("sum"), f"provinces[{i}].sum"),
                    "coop_active": parse_count(r.get("active"), f"provinces[{i}].active"),
                    "coop_inactive": parse_count(r.get("nonActive"), f"provinces[{i}].nonActive")}
    elif name == "types":
        fields = ["coop_type", "coop_type_name", "coop_active", "coop_inactive", "coop_total"]
        def transform(r: dict[str, Any], i: int) -> dict[str, Any]:
            code = str(r.get("coopType", ""))
            active = parse_count(r.get("active"), f"types[{i}].active")
            inactive = parse_count(r.get("nonActive"), f"types[{i}].nonActive")
            return {"coop_type": code, "coop_type_name": TYPE_NAMES.get(code, ""),
                    "coop_active": active, "coop_inactive": inactive, "coop_total": active + inactive}
    elif name == "strength":
        fields = ["coop_type", "coop_type_name", "strength_level", "coop_count"]
        def transform(r: dict[str, Any], i: int) -> dict[str, Any]:
            code = str(r.get("type", ""))
            return {"coop_type": code, "coop_type_name": TYPE_NAMES.get(code, ""),
                    "strength_level": r.get("level", ""),
                    "coop_count": parse_count(r.get("count"), f"strength[{i}].count")}
    else:
        raise ValueError(f"unsupported details endpoint: {name}")
    return metadata + fields, [dict(prefix, **transform(item, i)) for i, item in enumerate(rows)]


def write_csv(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def post_json(url: str, body: dict[str, str], timeout: float, retries: int) -> Any:
    req = Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST",
                  headers={"Accept": "application/json, text/plain, */*",
                           "Content-Type": "application/json;charset=UTF-8",
                           "Origin": "https://bigdata.cpd.go.th",
                           "Referer": "https://bigdata.cpd.go.th/",
                           "User-Agent": "CPD-Statistics-Extractor/1.0"})
    for attempt in range(retries + 1):
        try:
            with urlopen(req, timeout=timeout) as response:
                content_type = response.headers.get("Content-Type", "").lower()
                content = response.read()
                if "html" in content_type:
                    raise ValueError("server returned HTML instead of JSON (possible login/error page)")
                try:
                    return json.loads(content.decode("utf-8-sig"))
                except (ValueError, UnicodeError) as exc:
                    raise ValueError(f"invalid JSON response: {content[:160]!r}") from exc
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == retries:
                raise RuntimeError(f"HTTP {exc.code} for {url}") from exc
            delay = min(8.0, 2 ** attempt)
            retry_after = exc.headers.get("Retry-After")
            if retry_after and retry_after.isdecimal():
                delay = min(30.0, max(delay, float(retry_after)))
            LOG.warning("HTTP %s; retrying in %.1fs", exc.code, delay)
            time.sleep(delay)
        except (URLError, TimeoutError, ConnectionError) as exc:
            if attempt == retries:
                raise RuntimeError(f"network error for {url}: {exc}") from exc
            delay = min(8.0, 2 ** attempt)
            LOG.warning("network error %s; retrying in %.1fs", exc, delay)
            time.sleep(delay)
    raise RuntimeError("unreachable")


def run(args: argparse.Namespace) -> int:
    selected = CORE if args.summary_only else tuple(ENDPOINTS)
    body = {"OrgOrgId": "null", "PhakId": "null", "KhetId": "null"}
    if args.dry_run:
        for name in selected:
            print(f"POST {build_url(args.base_url, name, args.year, args.sector)}  body={json.dumps(body)}")
        return 0
    now = datetime.now(ICT)
    at = now.isoformat(timespec="seconds")
    run_id = now.strftime("%Y%m%dT%H%M%S%f+0700")
    out = Path(args.out)
    raw_dir = out / "raw" / run_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    data: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    logs: list[dict[str, str]] = []
    for i, name in enumerate(selected):
        if i and args.delay:
            time.sleep(args.delay)
        url = build_url(args.base_url, name, args.year, args.sector)
        LOG.info("[%d/%d] %s", i + 1, len(selected), name)
        try:
            payload = post_json(url, body, args.timeout, args.retries)
            rows = require_rows(payload, name)
            # Validate the response before treating the request as successful.
            if name == "cooperatives":
                coop_totals(rows)
            elif name in ("members", "committees", "officers"):
                gender_totals(rows, name)
            else:
                detail_rows(name, rows, args.year, args.sector, at)
            (raw_dir / f"{name}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            data[name] = rows
            logs.append({"endpoint": name, "status": "ok", "rows": str(len(rows)), "url": url, "error": ""})
        except (ValueError, RuntimeError, OSError) as exc:
            LOG.error("%s: %s", name, exc)
            errors.append(name)
            logs.append({"endpoint": name, "status": "error", "rows": "", "url": url, "error": str(exc)})
    if any(x in data for x in CORE):
        summary = build_summary(data, args.year, args.sector, at, args.base_url)
        write_csv(out / "cpd_summary.csv", SUMMARY_FIELDS, [summary])
        LOG.info("saved %s", out / "cpd_summary.csv")
    for name, filename in (("types", "cpd_type.csv"), ("strength", "cpd_strength.csv"), ("provinces", "cpd_province.csv")):
        if name in data:
            headers, rows = detail_rows(name, data[name], args.year, args.sector, at)
            write_csv(out / filename, headers, rows)
            LOG.info("saved %s (%d rows)", out / filename, len(rows))
    write_csv(out / "cpd_request_log.csv", ["endpoint", "status", "rows", "url", "error"], logs)
    LOG.info("raw JSON: %s", raw_dir)
    if errors:
        LOG.error("failed endpoints: %s; check cpd_request_log.csv", ", ".join(errors))
        return 1
    LOG.info("done: %s endpoints succeeded", len(selected))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract CPD cooperative dashboard data to CSV + raw JSON")
    parser.add_argument("--year", type=int, default=current_year_be(), help="Buddhist year (default: last year)")
    parser.add_argument("--sector", choices=("0", "1", "2"), default="0", help="0=all, 1=agricultural, 2=non-agricultural")
    parser.add_argument("--out", default="output", help="output directory (default: output)")
    parser.add_argument("--base-url", default=API_BASE, help="CPD API base URL")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout seconds")
    parser.add_argument("--retries", type=int, default=2, help="retries on network/429/5xx errors")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between API requests")
    parser.add_argument("--summary-only", action="store_true", help="only fetch dashboard headline totals")
    parser.add_argument("--dry-run", action="store_true", help="print requests without sending them")
    args = parser.parse_args(argv)
    if not (2500 <= args.year <= 2700) or args.timeout <= 0 or args.delay < 0 or not (0 <= args.retries <= 5):
        parser.error("invalid year, timeout, delay or retries")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stdout)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
