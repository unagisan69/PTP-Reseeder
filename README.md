# PTP Reseeder

A conservative command-line tool for finding PassThePopcorn torrents that correspond to movie files you already possess.

PTP Reseeder searches using PTP's documented JSON API, selects a candidate from the API-provided file list, downloads no more than one already-selected `.torrent`, and verifies every BitTorrent v1 SHA-1 piece against the local data before saving it.

> [!IMPORTANT]
> This is an unofficial community tool. It is not affiliated with, endorsed by, or supported by PassThePopcorn. PTP staff have final authority over acceptable API use. If your intended use may be considered scraping, ask staff for written approval before running it.

## What it does

For each selected item in a movie library, the program:

1. Chooses a local video filename as a search anchor.
2. Makes one documented `torrents.php?action=advanced&filelist=...&json=noredirect` request.
3. Compares local paths and exact byte sizes with file lists returned in that JSON response.
4. Selects at most one candidate without downloading torrent metadata.
5. In normal mode, downloads that one selected `.torrent`.
6. Verifies every v1 SHA-1 piece against the local content.
7. Saves the torrent only when verification succeeds.

It never renames, moves, links, or modifies library files. It does not add torrents to a client and never contacts the tracker announce URL.

## Requirements

- Python 3.10 or newer
- A PTP account with API access
- An API user and API key generated in the Security section of your PTP profile
- A movie library organized as standalone files and/or one release directory per immediate child

## Installation

### Linux and macOS

```bash
git clone https://github.com/unagisan69/PTP-Reseeder.git
cd PTP-Reseeder

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

On Debian or Ubuntu, install virtual-environment support if necessary:

```bash
sudo apt update
sudo apt install python3-venv
```

Do not use `sudo pip` or `--break-system-packages`.

### Windows PowerShell

```powershell
git clone https://github.com/unagisan69/PTP-Reseeder.git
cd PTP-Reseeder

py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

## Credentials

Credentials are read only from environment variables. Do not put them in this repository, a command-line argument, or a public log.

Linux/macOS:

```bash
export PTP_API_USER='your-api-user'
export PTP_API_KEY='your-api-key'
```

PowerShell:

```powershell
$env:PTP_API_USER = 'your-api-user'
$env:PTP_API_KEY = 'your-api-key'
```

Treat both values like passwords. Never share them or expose this tool through a public web service.

## Usage

```text
ptp-reseeder [options] LIBRARY DESTINATION
```

- `LIBRARY` is the directory whose immediate children will be examined.
- `DESTINATION` is where verified `.torrent` files will be saved.

Start with a small dry run:

```bash
ptp-reseeder --dry-run --limit 3 \
  "/mnt/StorageB/Downloads" \
  "/home/unagi/torrents"
```

A dry run uses only JSON search responses. It does **not** download `.torrent` files or claim piece-hash verification.

Run a normal small batch:

```bash
ptp-reseeder --limit 10 \
  "/mnt/StorageB/Downloads" \
  "/home/unagi/torrents"
```

Show all options:

```bash
ptp-reseeder --help
```

### Large scans

The default batch is 10 items. Batches over 25 are refused unless you explicitly pass `--staff-approved-large-scan`:

```bash
ptp-reseeder --limit 0 --staff-approved-large-scan \
  "/path/to/movies" \
  "/path/to/watch-folder"
```

This flag is an assertion, not a technical bypass or substitute for permission. Use it only after PTP staff have approved the described scan in writing.

## Matching rules

Matching is intentionally strict:

- A standalone file must correspond to a single-file torrent with the same filename and byte size.
- A release directory must have the same name as the PTP release.
- Every torrent file must exist at the exact relative path and exact byte size reported by the API.
- The selected torrent must pass a complete SHA-1 piece verification before it is saved.
- Extra local files are ignored because they are outside the torrent payload.
- Unknown or incomplete API file-list formats are rejected safely.
- Filenames resembling episodic TV releases are skipped.

A byte-identical movie with a different name or directory layout is rejected because this tool does not create links or alter the library.

## PTP-rule-conscious design

The design was reviewed against the PTP API documentation supplied on October 13, 2026. Rules can change, and this section is not a guarantee of compliance.

| PTP concern | Program behavior |
| --- | --- |
| Use API authentication headers | Sends `ApiUser` and `ApiKey` headers. |
| Do not scrape HTML/site pages | Uses only the documented JSON torrent-search endpoint and selected torrent download endpoint. |
| Do not download torrents to inspect metadata or decide what to snatch | Selects one candidate from the JSON file list before downloading it. Dry runs download no torrents. |
| Avoid excessive traffic | Waits 30 seconds between network requests and caps this program at 120 requests per rolling hour. |
| Limits span runs/processes | Coordinates request history through a locked local state file shared by simultaneous instances. |
| Handle HTTP 429 | Stops, persists at least a one-hour back-off, and honors a longer numeric `Retry-After`. |
| Handle HTTP 400/5xx | Stops and persists a five-minute back-off. |
| Handle HTTP 403 | Stops immediately. |
| Avoid TV indexing | Skips common episode and season filename patterns. |
| Avoid mass scraping | Defaults to 10 entries and requires an explicit staff-approval assertion above 25. |
| Protect credentials and personalized torrents | Uses environment variables and attempts to store cached API data and torrents with user-only permissions. |

The request ceiling only covers this program. Prowlarr, Radarr, browser activity, and other tools using the same account may consume the same PTP quota. Pause competing automation while using this program or reduce usage further.

## Cache and sensitive data

Search responses are cached for seven days. Selected torrent payloads are cached by immutable torrent ID so interrupted work does not repeat expensive requests.

Default cache location:

```text
~/.cache/ptp-reseeder
```

When `XDG_CACHE_HOME` is set, the cache is stored at:

```text
$XDG_CACHE_HOME/ptp-reseeder
```

PTP JSON responses and personalized torrent files can contain sensitive account information. Keep the cache private, do not synchronize it publicly, and do not include it in bug reports.

## Adding a verified torrent to a client

Point your torrent client at the existing data and force a local recheck before starting it. Exact client configuration differs, and this tool intentionally does not automate the client or tracker connection.

A successful verification strongly establishes that the local bytes match the torrent. The torrent client's own recheck remains the final operational safeguard.

## Troubleshooting

### `ptp-reseeder: command not found`

Activate the environment and reinstall the editable package:

```bash
cd /path/to/PTP-Reseeder
source .venv/bin/activate
python -m pip install -e .
```

### Broken virtual environment after moving computers

Virtual environments are not portable between operating systems or paths. Recreate it locally:

```bash
deactivate 2>/dev/null || true
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

### No API file-list match

This means the API returned no candidate with a complete, recognized path-and-size listing matching the local item. The program deliberately does not download candidates to investigate further.

### HTTP 403 or 429

Stop. Do not repeatedly retry or work around the response. Allow the stored back-off to expire, check for other software using PTP, and consult staff if the response persists.

## Development

Run the test suite without contacting PTP:

```bash
python -m unittest discover -s tests -v
```

Compile-check the source:

```bash
python -m compileall -q src tests
```

Tests use synthetic torrent data and an invalid example tracker URL. They require no PTP credentials.

## Responsible use

Use this tool only with content you are authorized to possess and share, and comply with applicable law and PTP's current rules. Do not use it to scrape PTP, inventory the tracker, index television, or mass-download torrent files.

## License

MIT License. See [LICENSE](LICENSE).
