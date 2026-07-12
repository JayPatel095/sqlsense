"""Click entry point."""

from __future__ import annotations

import sys

import click
from rich.console import Console

from .db import DatabaseError, connect
from .explain import run_explain

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
@click.argument("query")
def main(db_url: str, query: str) -> None:
    """Explain what the database does with QUERY, in plain English."""
    try:
        conn = connect(db_url)
        try:
            raw_plan = run_explain(conn, query)
        finally:
            conn.close()
    except DatabaseError as exc:
        err_console.print(f"[bold red]error:[/bold red] {exc}")
        sys.exit(1)

    console.print(raw_plan)
