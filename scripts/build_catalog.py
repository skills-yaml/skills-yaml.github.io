#!/usr/bin/env python3
"""Generate the registry catalog from a checkout of skills-yaml/registry.

Reads skills/<category>/<skill>/ trees, then writes:
  data/catalog.json          machine-readable catalog, used by the filter UI
  catalog.html               static rows injected between CATALOG markers
  index.html                 a short preview injected between PREVIEW markers

No third-party dependencies: the SKILL.md frontmatter we emit is a small,
fixed subset of YAML (scalars and string lists), so a full parser is overkill.
"""

import argparse
import html
import json
import os
import re
import sys
from datetime import date

SCALARS = ("name", "description", "version", "deprecated", "superseded_by")
LISTS = ("tags", "authors")
VERSION_DIR = re.compile(r"^v\d+\.\d+\.\d+(?:[-+].*)?$")


def strip_quotes(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def read_frontmatter(path):
    """Return the frontmatter of a SKILL.md as a dict, or {} if there is none."""
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    try:
        end = lines.index("---", 1)
    except ValueError:
        return {}

    data = {}
    key = None
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")) and line.lstrip().startswith("- "):
            if key in LISTS:
                data.setdefault(key, []).append(strip_quotes(line.lstrip()[2:]))
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key in LISTS and not value:
            data.setdefault(key, [])
        elif key in SCALARS:
            data[key] = strip_quotes(value)
    return data


def support_files(version_dir):
    """Count the optional support directories shipped with a version."""
    found = {}
    for kind in ("references", "templates", "scripts", "assets"):
        directory = os.path.join(version_dir, kind)
        if os.path.isdir(directory):
            count = sum(len(files) for _, _, files in os.walk(directory))
            if count:
                found[kind] = count
    return found


def read_skill(category, skill_dir):
    versions = sorted(
        entry
        for entry in os.listdir(skill_dir)
        if VERSION_DIR.match(entry) and os.path.isdir(os.path.join(skill_dir, entry))
    )
    aliases = {}
    for alias in ("latest", "default", "stable", "lts"):
        link = os.path.join(skill_dir, alias)
        if os.path.islink(link):
            aliases[alias] = os.path.basename(os.readlink(link).rstrip("/"))

    resolved = aliases.get("latest") or (versions[-1] if versions else None)
    manifest = os.path.join(skill_dir, resolved, "SKILL.md") if resolved else None
    if not manifest or not os.path.isfile(manifest):
        manifest = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(manifest):
        return None

    front = read_frontmatter(manifest)
    name = front.get("name") or os.path.basename(skill_dir)
    return {
        "name": name,
        "category": category,
        "id": f"{category}/{name}",
        "description": front.get("description", "").strip(),
        "version": front.get("version") or (resolved[1:] if resolved else "unversioned"),
        "tags": front.get("tags", []),
        "versions": [entry[1:] for entry in versions],
        "aliases": aliases,
        "support": support_files(os.path.join(skill_dir, resolved) if resolved else skill_dir),
        "deprecated": str(front.get("deprecated", "")).lower() == "true",
    }


def read_registry(root):
    skills_root = os.path.join(root, "skills")
    if not os.path.isdir(skills_root):
        sys.exit(f"no skills/ directory under {root}")

    skills = []
    for category in sorted(os.listdir(skills_root)):
        category_dir = os.path.join(skills_root, category)
        if not os.path.isdir(category_dir):
            continue
        for entry in sorted(os.listdir(category_dir)):
            skill_dir = os.path.join(category_dir, entry)
            if not os.path.isdir(skill_dir) or os.path.islink(skill_dir):
                continue
            skill = read_skill(category, skill_dir)
            if skill:
                skills.append(skill)
    return skills


def humanize(slug):
    return slug.replace("-", " ")


def plural(count, noun):
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def clamp(text, limit):
    """Trim to the last whole word inside limit, so previews don't cut mid-word."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "\u2026"


def row_html(skill):
    tags = "".join(
        f'<li class="tag">{html.escape(tag)}</li>' for tag in skill["tags"][:5]
    )
    support = "".join(
        f'<li>{html.escape(plural(count, kind.rstrip("s")))}</li>'
        for kind, count in sorted(skill["support"].items())
    )
    versions = ", ".join(skill["versions"]) or skill["version"]
    aliases = ", ".join(
        f"{alias} = {target[1:]}" for alias, target in sorted(skill["aliases"].items())
    )
    return f"""        <article class="entry" id="{html.escape(skill['name'])}" data-search="{html.escape((skill['id'] + ' ' + skill['description'] + ' ' + ' '.join(skill['tags'])).lower())}" data-category="{html.escape(skill['category'])}">
          <div class="entry-head">
            <h3 class="entry-name">{html.escape(skill['name'])}</h3>
            <p class="entry-path"><span>{html.escape(skill['category'])}/</span>{html.escape(skill['name'])}</p>
          </div>
          <p class="entry-desc">{html.escape(skill['description'])}</p>
          <dl class="entry-meta">
            <dt>Versions</dt><dd><code>{html.escape(versions)}</code></dd>
            <dt>Aliases</dt><dd><code>{html.escape(aliases) if aliases else '<span class="none">none</span>'}</code></dd>
            <dt>Ships</dt><dd>{f'<ul class="inline">{support}</ul>' if support else 'SKILL.md only'}</dd>
            <dt>Tags</dt><dd>{f'<ul class="inline">{tags}</ul>' if tags else '<span class="none">none</span>'}</dd>
          </dl>
          <p class="entry-add"><code>skm add {html.escape(skill['id'])}</code><button class="copy" type="button" data-copy="skm add {html.escape(skill['id'])}">Copy</button></p>
        </article>"""


def preview_html(skills):
    items = []
    for skill in skills[:6]:
        items.append(
            f"""        <li>
          <a href="catalog.html#{html.escape(skill['name'])}">
            <span class="pv-name">{html.escape(skill['id'])}</span>
            <span class="pv-desc">{html.escape(clamp(skill['description'], 120))}</span>
          </a>
          <span class="pv-version">{html.escape(skill['version'])}</span>
        </li>"""
        )
    return "\n".join(items)


def inject(path, marker, body):
    start, end = f"<!-- {marker}:START -->", f"<!-- {marker}:END -->"
    with open(path, encoding="utf-8") as handle:
        page = handle.read()
    if start not in page or end not in page:
        sys.exit(f"{path} is missing the {marker} markers")
    head, _, rest = page.partition(start)
    _, _, tail = rest.partition(end)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(f"{head}{start}\n{body}\n        {end}{tail}")


def main():
    site = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        default=os.path.join(os.path.dirname(site), "registry"),
        help="path to a checkout of skills-yaml/registry",
    )
    parser.add_argument("--site", default=site, help="path to this site checkout")
    args = parser.parse_args()

    skills = read_registry(args.registry)
    categories = sorted({skill["category"] for skill in skills})
    catalog = {
        "generated": date.today().isoformat(),
        "registry": "https://github.com/skills-yaml/registry",
        "categories": categories,
        "skills": skills,
    }

    os.makedirs(os.path.join(args.site, "data"), exist_ok=True)
    with open(os.path.join(args.site, "data", "catalog.json"), "w", encoding="utf-8") as handle:
        json.dump(catalog, handle, indent=2)
        handle.write("\n")

    filters = "\n".join(
        f'          <button class="filter" type="button" data-filter="{html.escape(category)}">{html.escape(humanize(category))}</button>'
        for category in categories
    )
    inject(os.path.join(args.site, "catalog.html"), "CATALOG", "\n".join(row_html(s) for s in skills))
    inject(os.path.join(args.site, "catalog.html"), "FILTERS", filters)
    inject(os.path.join(args.site, "index.html"), "PREVIEW", preview_html(skills))

    print(f"catalog: {len(skills)} skills across {len(categories)} categories")


if __name__ == "__main__":
    main()
