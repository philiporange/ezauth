import json as _json

from rich.console import Console
from rich.table import Table

console = Console()


def print_json(data: dict | list | None) -> None:
    console.print(_json.dumps(data, indent=2, default=str))


def print_detail(data: dict, *, title: str | None = None) -> None:
    if title:
        console.print(f"[bold]{title}[/bold]")
    for key, value in data.items():
        console.print(f"  {key}: {value}")


def print_table(rows: list[dict], *, columns: list[str] | None = None) -> None:
    if not rows:
        console.print("(no results)")
        return
    if columns is None:
        columns = list(rows[0].keys())
    table = Table()
    for col in columns:
        table.add_column(col)
    for row in rows:
        table.add_row(*(str(row.get(col, "")) for col in columns))
    console.print(table)
