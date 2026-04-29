from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path


def iter_sse_events(payload: str):
    for block in payload.split("\n\n"):
        lines = [line[6:] for line in block.splitlines() if line.startswith("data: ")]
        if lines:
            yield json.loads("\n".join(lines))


def run_prompt(base_url: str, prompt: str, timeout: int) -> dict:
    return run_case(base_url, {"prompt": prompt}, timeout)


def run_case(base_url: str, case: dict, timeout: int) -> dict:
    body = json.dumps(
        {
            "question": case["prompt"],
            "messages": case.get("messages") or [],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/chat/companion/stream",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content = response.read().decode("utf-8")

    summary = {
        "mode": None,
        "assets": 0,
        "documents": 0,
        "answer": "",
        "first_asset_kind": None,
        "first_document_open_url": None,
        "memory_used": False,
    }
    for event in iter_sse_events(content):
        if event.get("type") == "route":
            summary["memory_used"] = bool((event.get("memory") or {}).get("used"))
        elif event.get("type") == "findings":
            findings = event.get("findings") or {}
            assets = findings.get("assets") or []
            documents = findings.get("documents") or []
            summary["mode"] = event.get("mode")
            summary["assets"] = len(assets)
            summary["documents"] = len(documents)
            summary["first_asset_kind"] = assets[0].get("asset_kind") if assets else None
            summary["first_document_open_url"] = documents[0].get("open_url") if documents else None
        elif event.get("type") == "chunk":
            summary["answer"] += event.get("content") or ""
        elif event.get("type") == "done":
            counts = event.get("counts") or {}
            summary["mode"] = event.get("mode") or summary["mode"]
            summary["assets"] = counts.get("assets", summary["assets"])
            summary["documents"] = counts.get("documents", summary["documents"])
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate companion route decisions.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--cases", default="docs/evals/companion_routes.jsonl")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    cases_path = Path(args.cases)
    failures = 0
    for line in cases_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        result = run_case(args.base_url, case, args.timeout)
        mode_ok = result["mode"] == case["expected_mode"]
        assets_ok = (result["assets"] > 0) == case["expected_assets"]
        docs_ok = (result["documents"] > 0) == case["expected_documents"]
        kind_ok = case.get("expected_first_asset_kind") in {None, result["first_asset_kind"]}
        memory_ok = case.get("expected_memory_used") in {None, result["memory_used"]}
        document_open_ok = not case.get("expected_document_open_url") or bool(
            result["first_document_open_url"]
        )
        answer_terms = case.get("answer_contains_any") or []
        answer_ok = not answer_terms or any(
            term.lower() in result["answer"].lower() for term in answer_terms
        )
        ok = mode_ok and assets_ok and docs_ok and kind_ok and memory_ok and document_open_ok and answer_ok
        failures += 0 if ok else 1
        status = "PASS" if ok else "FAIL"
        print(
            f"{status} | {case['prompt']} | mode={result['mode']} "
            f"assets={result['assets']} documents={result['documents']} "
            f"first_asset_kind={result['first_asset_kind']} memory={result['memory_used']}"
        )

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
