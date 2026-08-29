# Blog Publishing Workflow

> How to move a blog post from draft in the private repo to live on [benchbox.dev/blog](https://benchbox.dev/blog/).

## Overview

Blog content is developed entirely in the **private** BenchBox repo under `_blog/`. When a post is ready, it is copied to the **public** repo at `docs/blog/`, where CI/CD builds and deploys it via GitHub Pages.

The `_blog/` directory is **not** part of the sync/release process. Blog posts must be explicitly published by placing them in `docs/blog/` in the public repo.

## Directory Structure

### Private repo (`_blog/`)

Each blog series has a consistent structure:

```
_blog/
  STYLE_GUIDE.md          # Voice and content rules
  VOICE_REFERENCE.md      # Quick reference for tone
  {series-name}/
    outlines/             # Post outlines and planning
    research/             # Reference materials and notes
    drafts/               # Work-in-progress posts
    published/            # Finalized posts (series archive)
    archived/             # Deprecated versions
```

### Public repo (`docs/blog/`)

Published posts only, with ABlog frontmatter:

```
docs/blog/
  index.rst               # Blog index (postlist + toctree)
  2025-01-22-welcome.md   # Published post
```

## Step-by-Step Publishing Process

### 1. Write the draft

Create the post in `_blog/{series}/drafts/`. Follow the style guide:

- **Voice**: Community-inclusive ("we" not "I"), enthusiastic but grounded
- **Claims**: Back with data, not opinions ("2.3x faster" not "much faster")
- **Platforms**: Neutral, no advocacy ("In this run, [platform A] finished [query] in [time] on [hardware]; [platform B] finished the same query in [time]. Include benchmark, scale, and phase so readers can interpret the measurement.")
- **Methodology**: Show your work, acknowledge limitations

See `_blog/STYLE_GUIDE.md` for the full guide and `_blog/VOICE_REFERENCE.md` for a quick tone reference. Sentence craft is defined in VOICE_REFERENCE. Do not copy it here.

### 2. Editorial check

`benchbox.release.content_validation` is not in this repository. Before publication, run the STYLE_GUIDE editorial checklist by hand (Voice, punctuation, limitations, citations). Do not record a validator pass.

### 3. Finalize the post

Once the editorial checklist is complete and the post is reviewed:

1. Move (or copy) the draft to `_blog/{series}/published/` for archival
2. Prepare the filename for publication: `YYYY-MM-DD-{slug}.md`

### 4. Add ABlog frontmatter

The post needs YAML frontmatter for ABlog to recognize it:

```yaml
---
blogpost: true
date: Mon DD, YYYY
author: Joe Harris
tags: tag1, tag2
---

# Post Title

Post content...
```

**Required fields:**

| Field | Format | Example |
|-------|--------|---------|
| `blogpost` | `true` | `true` |
| `date` | `Mon DD, YYYY` | `Jan 22, 2025` |
| `author` | Author name (must match `blog_authors` in `docs/conf.py`) | `Joe Harris` |
| `tags` | Comma-separated | `benchmarking, tpc-h, methodology` |

### 5. Place the post in the public repo

Copy the finalized post to `docs/blog/` in the public repo:

```bash
cp _blog/{series}/published/{post}.md \
   ../BenchBox-public/docs/blog/YYYY-MM-DD-{slug}.md
```

### 6. Register the post in the blog index

Edit `docs/blog/index.rst` in the public repo. Add the post filename (without extension) to the `toctree`:

```rst
.. toctree::
   :maxdepth: 1
   :hidden:

   2025-01-22-welcome
   YYYY-MM-DD-{slug}
```

The `postlist::` directive at the top of the index will automatically pick up the new post for the recent posts listing.

### 7. Commit and push

In the public repo, commit the new post and the updated index:

```bash
cd ../BenchBox-public
git add docs/blog/YYYY-MM-DD-{slug}.md docs/blog/index.rst
git commit -m "Publish blog post: {title}"
git push origin main
```

### 8. CI/CD deploys automatically

The GitHub Actions workflow (`.github/workflows/docs.yml`) triggers on pushes to `main` that touch `docs/**`. It:

1. Builds Sphinx + ABlog documentation
2. Assembles the site: landing page at `/`, docs at `/docs/`, blog at `/blog/`
3. Deploys to GitHub Pages

The post will appear at `https://benchbox.dev/blog/YYYY-MM-DD-{slug}/` and will automatically be included in:

- Recent Posts sidebar widget
- Tag cloud (based on `tags` frontmatter)
- Archives (organized by date)
- RSS feed (`blog/atom.xml`)

## Using benchbox-sync (Alternative)

If the post is already in `docs/blog/` in the private repo (not `_blog/`), the sync tool handles copying:

```bash
# Preview what would sync
benchbox-sync status

# Push all changes to public repo (creates a commit)
benchbox-sync push --message "Publish blog post: {title}"

# Then push the commit to GitHub
cd ../BenchBox-public && git push origin main
```

Note: `benchbox-sync` only syncs files under `ALLOWED_ROOT_FILES` (which includes `docs/`). The `_blog/` directory is never synced.

## Quick Checklist

- [ ] Draft written in `_blog/{series}/drafts/`
- [ ] Style guide followed (`STYLE_GUIDE.md`)
- [ ] STYLE_GUIDE editorial checklist completed by hand
- [ ] ABlog frontmatter added (`blogpost`, `date`, `author`, `tags`)
- [ ] Filename follows convention: `YYYY-MM-DD-{slug}.md`
- [ ] Post copied to `docs/blog/` in public repo
- [ ] Post added to `docs/blog/index.rst` toctree
- [ ] Committed and pushed to `main`
- [ ] Verified live at `https://benchbox.dev/blog/`
