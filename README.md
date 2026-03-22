# ap-filters

Manage your ActivityPub (Mastodon spec) content filters as files in Git.
Edits pushed to `main` are automatically synced to your account via GitHub Actions.

---

## Setup

### 1. Get a Mastodon access token
In your Mastodon instance:
**Preferences > Development > New Application**
- Give it any name (e.g. `ap-filters`)
- Scopes needed: `read:filters` + `write:filters`
- Copy the **access token** after saving

### 2. Add repository secrets
In your GitHub repo:
**Settings > Secrets and variables > Actions > New repository secret**
| Secret name              | Value                           |
|--------------------------|---------------------------------|
| `MASTODON_BASE_URL`      | `https://your.instance.social` |
| `MASTODON_ACCESS_TOKEN`  | The token from step 1           |

### 3. Create your filter files
Add `.md` files to the `filters/` directory - one file per filter, one line per keyword.

---

## Filter file format

```markdown
---
name: "Filter display name"    # required - must be unique across your filters
contexts:                      # which feeds to filter
  - home                       # home feed + lists
  - notifications
  - conversations              # alias for: thread
  - profiles                   # alias for: account
  - public                     # public timelines (local + federated)
action: warn                   # warn (show with warning) | hide (hide completely)
whole_word: false              # default whole_word for all keywords in this file
---

# Lines starting with # are comments - ignored by the sync script.
# One keyword per line.

keyword one
keyword two [w]    # force whole_word ON for this line
partial [!w]       # force whole_word OFF for this line
```

### Context values

| File value       | Mastodon context  | What it covers                  |
|------------------|-------------------|---------------------------------|
| `home`           | `home`            | Home feed and lists             |
| `notifications`  | `notifications`   | Notifications tab               |
| `conversations`  | `thread`          | Post threads / conversations    |
| `profiles`       | `account`         | User profile pages              |
| `public`         | `public`          | Public/federated timelines      |

### Action values

| Value  | Effect                                  |
|--------|-----------------------------------------|
| `warn` | Content is visible behind a warning     |
| `hide` | Content is hidden entirely              |

> **Note:** Filters are presumed as never expiring - `expires_in` is intentionally omitted from all API calls.

---

## Running the workflow

The sync runs automatically when you push changes to `filters/` or `sync.py` on `main`.

You can also trigger it manually:
**Actions > Sync Mastodon Filters > Run workflow**

Manual runs have two optional checkboxes:
- **Dry run** - prints planned changes without applying them (good for previewing)
- **Prune** - deletes filters on Mastodon that have no matching file in this repo

Pruning is opt-in and never runs on automatic pushes, so you won't accidentally delete anything.

---

## Running locally

```bash
pip install -r requirements.txt

export MASTODON_BASE_URL=https://your.instance.social
export MASTODON_ACCESS_TOKEN=your_token_here

python sync.py             # sync filters
python sync.py --dry-run   # preview changes only
python sync.py --prune     # sync + delete filters with no matching file
```