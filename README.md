# skills-yaml.tech

The site for [`skm`](https://github.com/skills-yaml/skm) and the
[skills registry](https://github.com/skills-yaml/registry). Static HTML, CSS and
a little JavaScript; no build step beyond the catalog generator.

## Layout

```txt
index.html                 landing page
catalog.html               generated skill catalog
assets/style.css           the whole stylesheet
assets/site.js             copy buttons and catalog filtering
scripts/build_catalog.py   reads a registry checkout, writes the catalog
data/catalog.json          generated, machine-readable catalog
CNAME                      skills-yaml.tech
```

## Regenerating the catalog

The generator reads a checkout of the registry and fills the marked regions of
`catalog.html` and `index.html`, plus `data/catalog.json`. It needs Python 3 and
nothing else.

```sh
python3 scripts/build_catalog.py --registry ../registry
```

`--registry` defaults to a sibling `../registry` directory. The generated regions
sit between `<!-- CATALOG:START -->`, `<!-- FILTERS:START -->` and
`<!-- PREVIEW:START -->` markers; edit around them, not inside them.

## Previewing

```sh
python3 -m http.server 8000
```

Then open <http://localhost:8000>.

## Deploying

`.github/workflows/pages.yml` checks out this repo and the registry, regenerates
the catalog, and publishes to GitHub Pages. It runs on every push to `main`,
once a day, on manual dispatch, and on a `registry-updated` repository dispatch
so publishing a skill can refresh the catalog without a commit here.

### One-time setup

1. Create the repository `skills-yaml/skills-yaml.github.io` and push this
   directory to `main`.
2. In **Settings → Pages**, set **Source** to **GitHub Actions**.
3. Point DNS for `skills-yaml.tech` at GitHub Pages:
   - `A` records for the apex: `185.199.108.153`, `185.199.109.153`,
     `185.199.110.153`, `185.199.111.153`
   - `AAAA` records: `2606:50c0:8000::153`, `2606:50c0:8001::153`,
     `2606:50c0:8002::153`, `2606:50c0:8003::153`
   - `CNAME` for `www`: `skills-yaml.github.io`
4. In **Settings → Pages**, enter `skills-yaml.tech` as the custom domain and
   enable **Enforce HTTPS** once the certificate is issued.

The `CNAME` file in this repo keeps the custom domain set across deploys.
