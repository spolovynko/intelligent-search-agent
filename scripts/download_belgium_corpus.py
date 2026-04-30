from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import httpx


ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIR = ROOT / "storage" / "assets" / "images" / "belgium" / "commons"
PDF_DIR = ROOT / "storage" / "assets" / "pdfs" / "belgian-history" / "jbh"
MANIFEST_DIR = ROOT / "storage" / "manifests"

USER_AGENT = (
    "IntelligentSearchAgent/0.1 "
    "(https://localhost.invalid/intelligent-search-agent; local development; contact: noreply@example.invalid)"
)
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
JBH_ARTICLES = "https://www.journalbelgianhistory.be/en/articles"

IMAGE_TERMS = [
    "Belgium history",
    "Belgian history",
    "history of Belgium",
    "Belgian Revolution",
    "Brussels history",
    "Antwerp history",
    "Ghent history",
    "Bruges history",
    "Belgium old map",
    "Belgium 19th century",
    "Belgium World War I",
    "Belgium World War II",
    "Belgian architecture historic",
    "Belgian monuments",
    "Belgian heritage",
]

EXCLUDE_TITLE_PATTERNS = [
    "paulding county",
    "ohio",
]


def slugify(value: str, *, max_len: int = 90) -> str:
    value = unquote(value)
    value = re.sub(r"^File:", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", value)
    value = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE)
    value = re.sub(r"_+", "_", value).strip("._")
    return (value or "item")[:max_len]


def extension_from_response(url: str, content_type: str | None, fallback: str) -> str:
    if content_type:
        if "jpeg" in content_type:
            return ".jpg"
        if "png" in content_type:
            return ".png"
        if "webp" in content_type:
            return ".webp"
        if "pdf" in content_type:
            return ".pdf"
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix else fallback


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def download_binary(client: httpx.Client, url: str, path: Path) -> tuple[bool, int, str | None]:
    if path.exists() and path.stat().st_size > 0:
        return False, path.stat().st_size, None

    last_error: Exception | None = None
    for attempt in range(4):
        try:
            response = client.get(url, follow_redirects=True)
            if response.status_code == 429:
                retry_after = response.headers.get("retry-after")
                wait_seconds = (
                    int(retry_after) if retry_after and retry_after.isdigit() else 20 + attempt * 10
                )
                print(f"rate limited; waiting {wait_seconds}s")
                time.sleep(wait_seconds)
                continue
            response.raise_for_status()
            content_type = response.headers.get("content-type")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(response.content)
            return True, len(response.content), content_type
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError) as exc:
            last_error = exc
            time.sleep(5 + attempt * 5)
    if last_error:
        raise last_error
    raise RuntimeError(f"Could not download {url}")


def commons_search(client: httpx.Client, term: str, limit: int = 50) -> list[dict[str, Any]]:
    response = client.get(
        COMMONS_API,
        params={
            "action": "query",
            "list": "search",
            "srsearch": term,
            "srnamespace": "6",
            "srlimit": str(limit),
            "format": "json",
            "formatversion": "2",
            "origin": "*",
        },
    )
    response.raise_for_status()
    search_rows = response.json().get("query", {}).get("search", [])
    pageids = [str(row["pageid"]) for row in search_rows if row.get("pageid")]
    if not pageids:
        return []

    detail_response = client.get(
        COMMONS_API,
        params={
            "action": "query",
            "pageids": "|".join(pageids),
            "prop": "imageinfo",
            "iiprop": "url|mime|size|extmetadata",
            "iiurlwidth": "600",
            "format": "json",
            "formatversion": "2",
            "origin": "*",
        },
    )
    detail_response.raise_for_status()
    return detail_response.json().get("query", {}).get("pages", [])


def should_skip_commons_title(title: str) -> bool:
    normalized = title.lower()
    return any(pattern in normalized for pattern in EXCLUDE_TITLE_PATTERNS)


def download_commons_images(client: httpx.Client, target_count: int) -> list[dict[str, Any]]:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    seen_titles: set[str] = set()
    manifest: list[dict[str, Any]] = []

    for term in IMAGE_TERMS:
        if len(manifest) >= target_count:
            break
        for page in commons_search(client, term):
            if len(manifest) >= target_count:
                break

            title = page.get("title") or ""
            if title in seen_titles:
                continue
            if should_skip_commons_title(title):
                continue
            seen_titles.add(title)

            image_info = (page.get("imageinfo") or [{}])[0]
            mime = image_info.get("mime") or ""
            if mime not in {"image/jpeg", "image/png", "image/webp"}:
                continue

            download_url = image_info.get("thumburl") or image_info.get("url")
            if not download_url:
                continue

            base_name = f"{len(manifest) + 1:03d}_{slugify(title)}"
            ext = extension_from_response(download_url, mime, ".jpg")
            local_path = IMAGE_DIR / f"{base_name}{ext}"

            try:
                _, size, content_type = download_binary(client, download_url, local_path)
            except Exception as exc:
                print(f"skip image {title}: {exc}")
                continue

            meta = image_info.get("extmetadata") or {}
            manifest.append(
                {
                    "local_path": str(local_path.relative_to(ROOT)).replace("\\", "/"),
                    "title": title,
                    "source": "Wikimedia Commons",
                    "source_url": image_info.get("descriptionurl"),
                    "download_url": download_url,
                    "search_term": term,
                    "mime": content_type or mime,
                    "bytes": size,
                    "width": image_info.get("thumbwidth") or image_info.get("width"),
                    "height": image_info.get("thumbheight") or image_info.get("height"),
                    "license": (meta.get("LicenseShortName") or {}).get("value"),
                    "license_url": (meta.get("LicenseUrl") or {}).get("value"),
                    "artist": (meta.get("Artist") or {}).get("value"),
                    "credit": (meta.get("Credit") or {}).get("value"),
                    "attribution": (meta.get("Attribution") or {}).get("value"),
                }
            )
            print(f"image {len(manifest):03d}/{target_count}: {title}")
            time.sleep(1.25)

    return manifest


def extract_pdf_links(html: str) -> list[str]:
    return [
        urljoin(JBH_ARTICLES, link.replace("&amp;", "&"))
        for link in re.findall(r'href="([^"]+\.pdf[^"]*)"', html, flags=re.IGNORECASE)
    ]


def download_jbh_pdfs(client: httpx.Client, target_count: int) -> list[dict[str, Any]]:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    page = 0
    while len(manifest) < target_count and page < 25:
        url = (
            JBH_ARTICLES
            if page == 0
            else f"{JBH_ARTICLES}?field_tags_tid_selective=All&&page={page}"
        )
        response = client.get(url)
        response.raise_for_status()

        for pdf_url in extract_pdf_links(response.text):
            if len(manifest) >= target_count:
                break
            if pdf_url in seen_urls:
                continue
            seen_urls.add(pdf_url)

            raw_name = Path(urlparse(pdf_url).path).name or f"jbh_{len(manifest) + 1}.pdf"
            local_path = PDF_DIR / f"{len(manifest) + 1:02d}_{slugify(raw_name)}.pdf"
            try:
                _, size, content_type = download_binary(client, pdf_url, local_path)
            except Exception as exc:
                print(f"skip pdf {pdf_url}: {exc}")
                continue

            if size < 5_000:
                local_path.unlink(missing_ok=True)
                continue

            manifest.append(
                {
                    "local_path": str(local_path.relative_to(ROOT)).replace("\\", "/"),
                    "title": unquote(raw_name),
                    "source": "Journal of Belgian History / BTNG-RBHC",
                    "source_url": pdf_url,
                    "listing_url": url,
                    "mime": content_type or "application/pdf",
                    "bytes": size,
                    "license": "CC BY-NC 4.0 or site open-access terms; verify per article",
                }
            )
            print(f"pdf {len(manifest):02d}/{target_count}: {raw_name}")
            time.sleep(0.5)
        page += 1

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=int, default=150)
    parser.add_argument("--pdfs", type=int, default=10)
    args = parser.parse_args()

    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    existing_image_manifest = MANIFEST_DIR / "belgium_images_commons.json"
    existing_pdf_manifest = MANIFEST_DIR / "belgian_history_pdfs_jbh.json"

    with httpx.Client(
        timeout=45.0, headers={"User-Agent": USER_AGENT, "Accept": "application/json,*/*"}
    ) as client:
        if args.images > 0:
            images = download_commons_images(client, args.images)
        elif existing_image_manifest.exists():
            images = json.loads(existing_image_manifest.read_text(encoding="utf-8")).get(
                "items", []
            )
        else:
            images = []

        if args.pdfs > 0:
            pdfs = download_jbh_pdfs(client, args.pdfs)
        elif existing_pdf_manifest.exists():
            pdfs = json.loads(existing_pdf_manifest.read_text(encoding="utf-8")).get("items", [])
        else:
            pdfs = []

    timestamp = datetime.now(timezone.utc).isoformat()
    image_manifest = {
        "created_at": timestamp,
        "count": len(images),
        "source": "Wikimedia Commons API",
        "items": images,
    }
    pdf_manifest = {
        "created_at": timestamp,
        "count": len(pdfs),
        "source": "Journal of Belgian History / BTNG-RBHC",
        "items": pdfs,
    }
    combined = {
        "created_at": timestamp,
        "images": image_manifest,
        "pdfs": pdf_manifest,
    }

    write_json(MANIFEST_DIR / "belgium_images_commons.json", image_manifest)
    write_json(MANIFEST_DIR / "belgian_history_pdfs_jbh.json", pdf_manifest)
    write_json(MANIFEST_DIR / "belgium_corpus_summary.json", combined)

    print("\nDone")
    print(f"Images: {len(images)} -> {IMAGE_DIR}")
    print(f"PDFs:   {len(pdfs)} -> {PDF_DIR}")
    print(f"Manifest: {MANIFEST_DIR / 'belgium_corpus_summary.json'}")


if __name__ == "__main__":
    main()
