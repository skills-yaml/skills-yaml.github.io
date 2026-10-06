#!/usr/bin/env python3
"""Generate the registry catalog from a checkout of skills-yaml/registry.

Reads skills/<category>/<skill>/ trees and the bundles of each
skills/<category>/manifest.yaml, then writes:
  data/catalog.json          machine-readable catalog, used by the filter UI
  catalog.html               static rows injected between CATALOG markers
  index.html                 a short preview injected between PREVIEW markers
  metapackages/<scope>/<name>.html
                             one page per bundle, listing its member skills

No third-party dependencies: the SKILL.md frontmatter we emit is a small,
fixed subset of YAML (scalars and string lists), so a full parser is overkill.
"""

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sys
from datetime import date
from urllib.parse import quote

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


def github_skill_url(category, name, version=None):
    """Link to exact published contents, or the root of an unversioned package."""
    path = f"{quote(category, safe='')}/{quote(name, safe='')}"
    if version and version != "unversioned":
        path += f"/v{quote(str(version), safe='')}"
    return f"https://github.com/skills-yaml/registry/tree/main/skills/{path}"


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
        "source_url": github_skill_url(
            category, os.path.basename(skill_dir),
            resolved[1:] if os.path.dirname(manifest) != skill_dir else None,
        ),
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


def parse_manifest(path):
    """Parse the block-style YAML subset used by namespace manifests.

    Mappings nest by indentation; values are scalars, "- item" lists or
    inline [a, b] lists. That is everything schema-2 manifests contain.
    """
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            stripped = line.split(" #", 1)[0].rstrip()
            if stripped.strip() and not stripped.lstrip().startswith("#"):
                rows.append((len(stripped) - len(stripped.lstrip()), stripped.strip()))

    def scalar(value):
        value = strip_quotes(value)
        if value.startswith("[") and value.endswith("]"):
            return [strip_quotes(item) for item in value[1:-1].split(",") if item.strip()]
        return value

    def block(index, indent):
        if index < len(rows) and rows[index][1].startswith("- "):
            items = []
            while index < len(rows) and rows[index][0] == indent and rows[index][1].startswith("- "):
                items.append(scalar(rows[index][1][2:]))
                index += 1
            return items, index
        mapping = {}
        while index < len(rows) and rows[index][0] == indent:
            key, _, value = rows[index][1].partition(":")
            index += 1
            if value.strip():
                mapping[strip_quotes(key)] = scalar(value.strip())
            elif index < len(rows) and rows[index][0] > indent:
                mapping[strip_quotes(key)], index = block(index, rows[index][0])
            else:
                mapping[strip_quotes(key)] = None
        return mapping, index

    return block(0, rows[0][0])[0] if rows else {}


def read_metapackages(root, skills):
    """Return every bundle published in a namespace manifest, with its members."""
    by_id = {skill["id"]: skill for skill in skills}
    metapackages = []
    skills_root = os.path.join(root, "skills")
    for scope in sorted(os.listdir(skills_root)):
        path = os.path.join(skills_root, scope, "manifest.yaml")
        if not os.path.isfile(path):
            continue
        manifest = parse_manifest(path)
        pinned = manifest.get("packages") or {}
        for name, bundle in sorted((manifest.get("bundles") or {}).items()):
            members = []
            for package in (bundle or {}).get("packages") or []:
                skill = by_id.get(f"{scope}/{package}", {})
                members.append({
                    "name": package,
                    "id": f"{scope}/{package}",
                    "version": pinned.get(package) or skill.get("version", ""),
                    "source_url": github_skill_url(
                        scope, package, pinned.get(package) or skill.get("version"),
                    ),
                    "description": skill.get("description", ""),
                })
            metapackages.append({
                "name": name,
                "scope": scope,
                "id": f"{scope}/{name}",
                "page": f"metapackages/{scope}/{name}.html",
                "members": members,
            })
    for skill in skills:
        skill["metapackages"] = [
            m["id"] for m in metapackages if skill["id"] in {x["id"] for x in m["members"]}
        ]
    return metapackages


def humanize(slug):
    return slug.replace("-", " ")


def plural(count, noun):
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def clamp(text, limit):
    """Trim to the last whole word inside limit, so previews don't cut mid-word."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "\u2026"


def row_html(skill, metapackages):
    pages = {m["id"]: m["page"] for m in metapackages}
    included = "".join(
        f'<li><a href="{html.escape(pages[mid])}">{html.escape(mid)}</a></li>'
        for mid in skill.get("metapackages", [])
    )
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
            <dt>Source</dt><dd><a href="{html.escape(skill['source_url'])}" aria-label="View {html.escape(skill['id'])} on GitHub">GitHub</a></dd>
            <dt>Versions</dt><dd><code>{html.escape(versions)}</code></dd>
            <dt>Aliases</dt><dd><code>{html.escape(aliases) if aliases else '<span class="none">none</span>'}</code></dd>
            <dt>Ships</dt><dd>{f'<ul class="inline">{support}</ul>' if support else 'SKILL.md only'}</dd>
            <dt>Tags</dt><dd>{f'<ul class="inline">{tags}</ul>' if tags else '<span class="none">none</span>'}</dd>
            <dt>Included in</dt><dd>{f'<ul class="inline">{included}</ul>' if included else '<span class="none">no metapackage</span>'}</dd>
          </dl>
          <p class="entry-add"><code>skm add {html.escape(skill['id'])}</code><button class="copy" type="button" data-copy="skm add {html.escape(skill['id'])}">Copy</button></p>
        </article>"""


def bundle_command(metapackage):
    return f"skm add {metapackage['id']} --kind bundle --yes"


def metapackage_row_html(metapackage):
    members = metapackage["members"]
    shown = ", ".join(m["name"] for m in members[:6])
    if len(members) > 6:
        shown += f", and {len(members) - 6} more"
    command = bundle_command(metapackage)
    search = " ".join([metapackage["id"]] + [m["name"] for m in members]).lower()
    return f"""        <article class="entry entry-bundle" id="metapackage-{html.escape(metapackage['scope'])}-{html.escape(metapackage['name'])}" data-search="{html.escape(search)}" data-category="{html.escape(metapackage['scope'])}">
          <div class="entry-head">
            <h3 class="entry-name"><a href="{html.escape(metapackage['page'])}">{html.escape(metapackage['name'])}</a></h3>
            <p class="entry-path"><span>{html.escape(metapackage['scope'])}/</span>{html.escape(metapackage['name'])}</p>
          </div>
          <p class="entry-desc">{html.escape(plural(len(members), 'skill'))} from the <code>{html.escape(metapackage['scope'])}</code> scope, each pinned to an exact version: {html.escape(shown)}.</p>
          <p class="entry-more"><a href="{html.escape(metapackage['page'])}">See all {html.escape(plural(len(members), 'skill'))}</a></p>
          <p class="entry-add"><code>{html.escape(command)}</code><button class="copy" type="button" data-copy="{html.escape(command)}">Copy</button></p>
        </article>"""


def metapackage_page_html(metapackage):
    scope, name, members = metapackage["scope"], metapackage["name"], metapackage["members"]
    title = f"{metapackage['id']} — skills.yaml"
    summary = f"{plural(len(members), 'skill')} from the {scope} scope, installed together with one command."
    preview = f"skm add {metapackage['id']} --kind bundle --dry-run"
    command = bundle_command(metapackage)
    rows = "\n".join(
        f"""          <tr>
            <th scope="row"><a href="/catalog.html#{html.escape(m['name'])}"><code>{html.escape(m['name'])}</code></a></th>
            <td class="member-version"><code>{html.escape(m['version'])}</code></td>
            <td><a href="{html.escape(m['source_url'])}" aria-label="View {html.escape(m['id'])} {html.escape(m['version'])} on GitHub">GitHub</a></td>
            <td>{html.escape(m['description']) or '<span class="none">not in this registry</span>'}</td>
          </tr>"""
        for m in members
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(summary)}">
<link rel="canonical" href="https://skills-yaml.tech/{html.escape(metapackage['page'])}">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(summary)}">
<meta property="og:url" content="https://skills-yaml.tech/{html.escape(metapackage['page'])}">
<meta property="og:type" content="website">
<link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="/assets/style.css">
</head>
<body>
<a class="skip" href="#main">Skip to content</a>

<header class="docs-header">
  <div class="docs-header-inner">
    <a class="docs-logo" href="/">skills<span>.</span>yaml</a>
    <nav aria-label="Primary">
      <a href="/index.html#disk">How it works</a>
      <a href="/index.html#manifest">Manifest</a>
      <a href="/index.html#commands">Commands</a>
      <a href="/catalog.html" aria-current="page">Catalog</a>
      <a href="/guide.html">Guide</a>
      <a href="https://github.com/skills-yaml/skm">GitHub</a>
    </nav>
  </div>
</header>

<div class="docs-shell">

  <nav class="docs-sidebar" aria-label="Site">
    <p class="docs-sidebar-group">Get started</p>
    <ul>
      <li><a href="/index.html">Overview</a></li>
      <li><a href="/index.html#install">Install skm</a></li>
      <li><a href="/index.html#disk">How it works</a></li>
      <li><a href="/index.html#manifest">The manifest</a></li>
      <li><a href="/index.html#commands">Commands</a></li>
      <li><a href="/index.html#guardrails">Guardrails</a></li>
    </ul>
    <p class="docs-sidebar-group">Registry</p>
    <ul>
      <li><a href="/catalog.html">Catalog</a></li>
      <li><a href="/catalog.html#metapackages" aria-current="page">Metapackages</a></li>
      <li><a href="/guide.html">Authoring guide</a></li>
      <li><a href="https://github.com/skills-yaml/registry">Registry on GitHub</a></li>
    </ul>
  </nav>

  <main id="main" class="docs-main">
    <article class="docs-page">

      <header class="docs-title">
        <p class="docs-crumb"><a href="/catalog.html">Catalog</a> / <a href="/catalog.html#metapackages">Metapackages</a></p>
        <h1>{html.escape(name)}</h1>
        <p class="docs-lead">{html.escape(summary)}</p>
      </header>

      <div class="table-wrap">
        <table class="dtable">
          <tbody>
            <tr><th scope="row">Package</th><td><code>{html.escape(metapackage['id'])}</code></td></tr>
            <tr><th scope="row">Scope</th><td><code>{html.escape(scope)}/</code></td></tr>
            <tr><th scope="row">Skills</th><td>{len(members)}</td></tr>
          </tbody>
        </table>
      </div>

      <section id="add">
        <h2>Add it to your project</h2>
        <p>Adding a metapackage requires skm 0.7.0 or later.</p>
        <ol class="stepper">
          <li class="step">
            <h4>Preview the change</h4>
            <p>This command shows what would be added, without changing anything:</p>
            <p class="entry-add"><code>{html.escape(preview)}</code><button class="copy" type="button" data-copy="{html.escape(preview)}">Copy</button></p>
          </li>
          <li class="step">
            <h4>Add the metapackage</h4>
            <p>This command adds it:</p>
            <p class="entry-add"><code>{html.escape(command)}</code><button class="copy" type="button" data-copy="{html.escape(command)}">Copy</button></p>
          </li>
        </ol>
        <div class="hint hint-info" role="note">
          <svg class="hint-icon" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="8.25" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M10 9v5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="10" cy="6.4" r="1" fill="currentColor"/></svg>
          <div><p>skm writes each skill into <code>skills.yaml</code> as its own entry, pinned to the version listed below.</p></div>
        </div>
      </section>

      <section id="members">
        <h2>Skills in this metapackage</h2>
        <div class="table-wrap">
          <table class="dtable members">
            <thead><tr><th scope="col">Skill</th><th scope="col">Version</th><th scope="col">Source</th><th scope="col">What it does</th></tr></thead>
            <tbody>
{rows}
            </tbody>
          </table>
        </div>
      </section>

      <nav class="pager" aria-label="Pages">
        <a class="pager-prev" href="/catalog.html#metapackages"><span>Back to</span>Catalog</a>
        <a class="pager-next" href="https://github.com/skills-yaml/registry/blob/main/skills/{html.escape(scope)}/manifest.yaml"><span>Source</span>manifest.yaml</a>
      </nav>

      <p class="docs-footnote">Generated from the registry repository on every deploy.</p>
    </article>
  </main>

  <aside class="docs-toc" aria-label="On this page">
    <p class="docs-toc-title">On this page</p>
    <ul>
      <li><a href="#add">Add it to your project</a></li>
      <li><a href="#members">Skills in this metapackage</a></li>
    </ul>
  </aside>

</div>

<script src="/assets/site.js" defer></script>
</body>
</html>
"""


def write_metapackage_pages(site, metapackages):
    """Rewrite metapackages/ from scratch so a removed bundle loses its page."""
    root = os.path.join(site, "metapackages")
    if os.path.isdir(root):
        shutil.rmtree(root)
    pages = []
    for metapackage in metapackages:
        path = os.path.join(site, metapackage["page"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(metapackage_page_html(metapackage))
        pages.append(metapackage["page"])
    return pages


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
          <a class="pv-source" href="{html.escape(skill['source_url'])}" aria-label="View {html.escape(skill['id'])} on GitHub">GitHub</a>
        </li>"""
        )
    return "\n".join(items)


ASSET_REFERENCE = re.compile(r'(assets/(?:style\.css|site\.js))(\?v=[0-9a-f]+)?')


def version_assets(site, pages):
    """Stamp each asset reference with a hash of the asset's contents.

    The CDN in front of this site caches assets for four hours but serves the
    HTML fresh. Without this, a deploy leaves visitors on a stale stylesheet
    until the cache expires. Changing the query string changes the cache key,
    so a new stylesheet is fetched the moment the HTML referencing it goes out.
    """
    digests = {}
    for name in ("assets/style.css", "assets/site.js"):
        path = os.path.join(site, name)
        if os.path.isfile(path):
            with open(path, "rb") as handle:
                digests[name] = hashlib.sha256(handle.read()).hexdigest()[:10]

    def stamp(match):
        name = match.group(1)
        return f"{name}?v={digests[name]}" if name in digests else match.group(0)

    for page in pages:
        path = os.path.join(site, page)
        with open(path, encoding="utf-8") as handle:
            content = handle.read()
        updated = ASSET_REFERENCE.sub(stamp, content)
        if updated != content:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(updated)
    return digests


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
    metapackages = read_metapackages(args.registry, skills)
    categories = sorted({skill["category"] for skill in skills})
    catalog = {
        "generated": date.today().isoformat(),
        "registry": "https://github.com/skills-yaml/registry",
        "categories": categories,
        "metapackages": metapackages,
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
    inject(os.path.join(args.site, "catalog.html"), "CATALOG", "\n".join(row_html(s, metapackages) for s in skills))
    inject(os.path.join(args.site, "catalog.html"), "METAPACKAGES", "\n".join(metapackage_row_html(m) for m in metapackages))
    inject(os.path.join(args.site, "catalog.html"), "FILTERS", filters)
    inject(os.path.join(args.site, "index.html"), "PREVIEW", preview_html(skills))

    pages = write_metapackage_pages(args.site, metapackages)
    digests = version_assets(args.site, ("index.html", "catalog.html", "guide.html", *pages))

    print(f"catalog: {len(skills)} skills and {len(metapackages)} metapackages across {len(categories)} categories")
    for name, digest in sorted(digests.items()):
        print(f"asset:   {name}?v={digest}")


if __name__ == "__main__":
    main()
