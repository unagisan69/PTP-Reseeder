from __future__ import annotations

import argparse
import sys

from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table

from .client import PTPClient, PTPError
from .config import Settings
from .scanner import find_match, library_items, save_match


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="ptp-reseeder",
        description="Download PTP torrents only after byte-for-byte verification against local files.",
    )
    result.add_argument("library", type=Path, help="folder whose immediate children are scanned")
    result.add_argument("destination", type=Path, help="folder for verified .torrent files")
    result.add_argument(
        "--dry-run",
        action="store_true",
        help="select from API file lists only; download and write no .torrent files",
    )
    result.add_argument(
        "--limit", type=int, default=10, help="scan at most this many library entries (default: 10)"
    )
    result.add_argument(
        "--staff-approved-large-scan",
        action="store_true",
        help="confirm written PTP staff approval for a batch over 25 entries (0 = all)",
    )
    return result


def run(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    console = Console()
    try:
        settings = Settings.from_environment()
        items = library_items(args.library.expanduser())
    except ValueError as exc:
        console.print(f"[bold red]Configuration error:[/] {exc}")
        return 2
    if args.limit < 0:
        console.print("[bold red]--limit cannot be negative[/]")
        return 2
    if (args.limit == 0 or args.limit > 25) and not args.staff_approved_large_scan:
        console.print(
            "[bold red]Safety stop:[/] batches over 25 entries require written PTP staff approval. "
            "Use --staff-approved-large-scan only after receiving it."
        )
        return 2
    if args.limit:
        items = items[: args.limit]

    console.print(
        f"[bold]PTP Reseeder[/]  [dim]{len(items)} entries • "
        f"{'API selection only; no torrent downloads' if args.dry_run else 'post-selection SHA-1 verification'}[/]"
    )
    minimum_seconds = len(items) * settings.request_delay
    hours, remainder = divmod(int(minimum_seconds), 3600)
    minutes = remainder // 60
    console.print(
        f"[dim]PTP-safe pacing: one API request every {settings.request_delay:g}s"
        f" • minimum uncached scan time {hours}h {minutes:02d}m"
        f" • selected torrent downloads use a separate {settings.torrent_download_budget}/4h budget"
        " • interrupted work is cached[/]"
    )
    client = PTPClient(
        settings,
        notice=lambda message: console.print(f"[yellow]{message}[/]"),
    )
    matched: list[tuple[str, str, str]] = []
    unmatched = 0
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            overall = progress.add_task("Scanning library", total=len(items))
            verify_task = progress.add_task("Waiting", total=1, visible=False)
            for item in items:
                progress.update(overall, description=f"Searching [cyan]{item.name}[/]")

                def on_verify(candidate, done: int, total: int) -> None:
                    progress.update(
                        verify_task,
                        visible=True,
                        total=total,
                        completed=done,
                        description=f"Verifying [magenta]{candidate.release_name}[/]",
                    )

                match, candidates = find_match(
                    client, item, on_verify, download=not args.dry_run
                )
                progress.update(verify_task, visible=False, completed=0)
                if match:
                    if args.dry_run:
                        output = "candidate selected; not downloaded"
                    else:
                        output = str(save_match(match, args.destination.expanduser()))
                    matched.append((item.name, match.candidate.release_name, output))
                    marker = "candidate" if args.dry_run else "verified"
                    progress.console.print(
                        f"[green]✓[/] {item.name} [dim]→ torrent {match.candidate.torrent_id} "
                        f"({match.total_size:,} bytes; {marker})[/]"
                    )
                else:
                    unmatched += 1
                    if candidates == -1:
                        detail = "skipped: filename resembles episodic TV"
                    else:
                        detail = f"no API file-list match ({candidates} candidates checked)"
                    progress.console.print(f"[yellow]–[/] {item.name} [dim]{detail}[/]")
                progress.advance(overall)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped safely; no library files were changed.[/]")
        return 130
    except (PTPError, OSError) as exc:
        console.print(f"\n[bold red]Stopped:[/] {exc}")
        return 1

    table = Table(title="Scan summary", show_lines=False)
    table.add_column("Local item")
    table.add_column("Verified PTP release")
    table.add_column("Result")
    for row in matched:
        table.add_row(*row)
    console.print(table if matched else "[yellow]No exact matches found.[/]")
    console.print(f"[bold green]{len(matched)} verified[/] • [yellow]{unmatched} unmatched[/]")
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
