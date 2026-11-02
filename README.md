# Peter Vlahakis: Engineering Portfolio

The engineering portfolio of Peter Vlahakis, mechanical engineering student at The University of Texas at Austin.

**Live site:** https://petervlahakis.com/

- **Home:** intro, About, and resume
- **Projects:** machined and fabricated parts, from CAD and CAM to the finished part
- **Baja SAE:** Longhorn Baja Racing's inaugural season: chassis design, analysis, and fabrication

## Tech

Static HTML, CSS, and JavaScript, with the page content in JSON. No frameworks, no bundler, no build step. Hosted on GitHub Pages from the root of `main`.

## Layout

```
index.html  projects.html  baja.html  404.html  favicon.svg  .nojekyll
css/      tokens.css (all colors, fonts, spacing) and one stylesheet per page
js/       shared helpers and one script per page
data/     site.json  projects.json  baja.json  manifest.json (generated)
assets/   img/ and video/ (generated), fonts/, resume/
tools/    media import, hero video, site checks, local preview server
```

## Preview locally

```
python tools/serve.py
```

Then open http://localhost:8000/. The pages load their content from JSON, so opening the `.html` files directly does not work.

## Updating content and media

- **Text and specs:** edit the matching file in `data/` (`site.json` for Home, `projects.json`, `baja.json`).
- **Images and video:** add an entry to `tools/media_map.json`, then run `tools/build_media.py`. It writes optimized WebP images (all metadata removed) and short MP4 clips to `assets/`, and regenerates `data/manifest.json`. Refer to the image by its `id` in `data/`. The original photos live outside this repo.
- **Home video:** `tools/build_hero.py --clip hero`.
- **Before committing:** run `tools/check_site.py`; it must end with `check_site: OK`.

The tools need Python with the packages in `tools/requirements.txt`.

## Credits

- Baja SAE competition photos by George Lawrence (@glawrence_photography).
- Fonts: Inter and IBM Plex Mono, both under the SIL Open Font License 1.1. License texts are in `assets/fonts/`.

All images and content © Peter Vlahakis unless credited. All rights reserved.
