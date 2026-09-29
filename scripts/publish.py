"""Publish due, prepared RSS items. Run from the assets repository root."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

MEDIA = "http://search.yahoo.com/mrss/"


def publish(root, now, dry_run=False):
    feed_path = root / "feed.xml"
    original = feed_path.read_text()
    feed = ET.fromstring(original)
    channel = feed.find("channel")
    existing = [i.findtext("guid") for i in channel.findall("item")]
    if None in existing or len(existing) != len(set(existing)):
        raise ValueError("Feed GUIDs must be present and unique")
    additions, seen = [], set(existing)
    for path in sorted((root / "queue").glob("*.json")):
        entry = json.loads(path.read_text())
        if entry.get("status") != "ready":
            continue
        due = datetime.fromisoformat(entry["publish_at"].replace("Z", "+00:00"))
        if due.tzinfo is None:
            raise ValueError("publish_at requires a timezone")
        if due > now:
            continue
        fragment_path = (root / entry["item"]).resolve()
        if not fragment_path.is_relative_to(root.resolve()):
            raise ValueError("Item path escapes repository")
        fragment = fragment_path.read_text().strip()
        wrapper = ET.fromstring(f'<root xmlns:media="{MEDIA}">{fragment}</root>')
        if len(wrapper) != 1 or wrapper[0].tag != "item":
            raise ValueError("Expected exactly one RSS item")
        item = wrapper[0]
        guid = item.findtext("guid")
        if not guid or not item.findtext("title") or not item.findtext("description"):
            raise ValueError("Item requires GUID, title and description")
        if guid in seen:
            print(f"Already published: {guid}")
            continue
        dest = urlparse(item.findtext("link", ""))
        if dest.scheme != "https" or dest.netloc != "feralgrimoire.com":
            raise ValueError("Destination must be the Feral Grimoire site")
        enclosure = item.find("enclosure")
        if enclosure is None:
            raise ValueError("Missing enclosure")
        image_url = enclosure.get("url", "")
        prefix = "https://tanyapowell.github.io/feral-grimoire-assets/"
        if not image_url.startswith(prefix):
            raise ValueError("Image must be hosted in the assets repository")
        if not image_url[len(prefix):].startswith("pins/"):
            raise ValueError("Queued images must be in the deployed pins directory")
        image = (root / image_url[len(prefix):]).resolve()
        if not image.is_relative_to((root / "pins").resolve()) or not image.is_file():
            raise ValueError("Image missing or outside repository")
        if image.stat().st_size != int(enclosure.get("length", "0")):
            raise ValueError("Enclosure byte length differs from image")
        if image.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("Expected a PNG image")
        media = item.find(f"{{{MEDIA}}}content")
        if media is None or media.get("url") != image_url:
            raise ValueError("Media URL and enclosure must agree")
        additions.append(fragment)
        seen.add(guid)
        print(f"Due: {guid}")
    if additions:
        if original.count("</channel>") != 1:
            raise ValueError("Expected one closing channel")
        updated = original.replace("</channel>", "\n".join(additions) + "\n</channel>")
        ET.fromstring(updated)
        if not dry_run:
            temporary = feed_path.with_suffix(".xml.tmp")
            temporary.write_text(updated)
            temporary.replace(feed_path)
    print(f"{'Would add' if dry_run else 'Added'} {len(additions)} item(s). Pinterest ingestion remains unverified.")
    return len(additions)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    publish(args.root, datetime.now(timezone.utc), args.dry_run)
