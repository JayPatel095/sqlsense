"""Click entry point."""

from __future__ import annotations

import json
import sys

import click
from rich.console import Console

from .db import DatabaseError, connect
from .explain import run_explain
from .lint import lint_plan
from .parser import parse_plan
from .summary import summarize, top_nodes_by_time, total_time_ms

console = Console()
err_console = Console(stderr=True)


@click.command()
@click.version_option()
@click.option(
    "--db",
    "db_url",
    required=True,
    metavar="URL",
    help="Connection string: postgresql://... or a path to a SQLite file.",
)
@click.option("--raw", is_flag=True, help="Print the raw EXPLAIN output and exit.")
@click.argument("query")
def main(db_url: str, query: str, raw: bool) -> None:
    """Explain what the database does with QUERY, in plain English."""
    try:
        conn = connect(db_url)
        try:
            dialect = conn.dialect
            raw_plan = run_explain(conn, query)
        finally:
            conn.close()
    except DatabaseError as exc:
        err_console.print(f"[bold red]error:[/bold red] {exc}")
        sys.exit(1)

    # SQLite's EXPLAIN QUERY PLAN is already terse prose; the parsed
    # summary pipeline is Postgres-only for now.
    if raw or dialect == "sqlite":
        console.print(raw_plan)
        return

    root = parse_plan(json.loads(raw_plan))

    console.print("[bold]What the database did[/bold]")
    for sentence in summarize(root):
        console.print(f"  • {sentence}")

    hot = top_nodes_by_time(root)
    if hot:
        console.print("\n[bold]Where the time went[/bold]")
        for rank, node in enumerate(hot, 1):
            where = f" on {node.relation_name}" if node.relation_name else ""
            style = " [red](top cost)[/red]" if rank == 1 else ""
            console.print(
                f"  {rank}. {node.node_type}{where}: {total_time_ms(node):.1f} ms{style}"
            )

    findings = lint_plan(root)
    if findings:
        console.print("\n[bold]Suggestions[/bold]")
        for f in findings:
            badge = "[red]error[/red]" if f.severity == "error" else "[yellow]warn[/yellow]"
            seen = f" [dim](x{f.count} in this plan)[/dim]" if f.count > 1 else ""
            console.print(f"  {badge} {f.message}{seen}")
            console.print(f"       [green]->[/green] {f.suggestion}")
    else:
        console.print("\n[green]No lint findings — this plan looks healthy.[/green]")
