import json

import click
from ezauth_client import EZAuth, EZAuthError

from ezauth_cli.config import CLIConfig
from ezauth_cli.hashcash import solve_challenge
from ezauth_cli.output import console, print_detail, print_json, print_table


pass_json = click.make_pass_decorator(bool, ensure=True)


def _get_client(cfg: CLIConfig) -> EZAuth:
    if not cfg.server_url:
        console.print("[red]Not configured. Run 'ezauth configure' first.[/red]")
        raise SystemExit(1)
    return EZAuth(
        cfg.server_url,
        secret_key=cfg.secret_key or None,
        publishable_key=cfg.publishable_key or None,
    )


def _require_secret_key(cfg: CLIConfig) -> None:
    if not cfg.secret_key:
        console.print("[red]Secret key not configured. Run 'ezauth configure' to set it.[/red]")
        raise SystemExit(1)


def _handle_error(e: EZAuthError) -> None:
    msg = e.message
    if e.status:
        msg += f" (status {e.status})"
    console.print(f"[red]{msg}[/red]")
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# Top-level group
# ---------------------------------------------------------------------------

@click.group()
@click.option("--json", "use_json", is_flag=True, default=False, help="Output raw JSON.")
@click.pass_context
def cli(ctx, use_json):
    """EZAuth CLI — manage your auth service."""
    ctx.ensure_object(dict)
    ctx.obj["json"] = use_json


def _is_json(ctx: click.Context) -> bool:
    return ctx.obj.get("json", False)


# ---------------------------------------------------------------------------
# configure
# ---------------------------------------------------------------------------

@cli.command()
def configure():
    """Set server URL and API keys."""
    cfg = CLIConfig.load()
    cfg.server_url = click.prompt("Server URL", default=cfg.server_url or "http://localhost:8000")
    cfg.publishable_key = click.prompt("Publishable key", default=cfg.publishable_key or "")
    cfg.secret_key = click.prompt("Secret key (optional)", default=cfg.secret_key or "")
    cfg.save()
    console.print("[green]Configuration saved.[/green]")


# ---------------------------------------------------------------------------
# signup
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
def signup(ctx):
    """Sign up for a new account."""
    cfg = CLIConfig.load()
    client = _get_client(cfg)

    email = click.prompt("Email")
    password = click.prompt("Password (optional, press Enter to skip)", default="", show_default=False)
    password = password or None

    # Request and solve hashcash challenge
    console.print("Requesting challenge...")
    try:
        challenge_data = client.auth.request_challenge()
    except EZAuthError as e:
        _handle_error(e)

    params = challenge_data["params"]
    nonce, attempts = solve_challenge(
        challenge=challenge_data["challenge"],
        difficulty=challenge_data["difficulty"],
        time_cost=params["time_cost"],
        memory_cost=params["memory_cost"],
        parallelism=params["parallelism"],
        hash_len=params["hash_len"],
    )
    console.print(f"[green]Proof of work solved in {attempts} attempts.[/green]")

    hashcash_proof = {"challenge": challenge_data["challenge"], "nonce": nonce}
    try:
        result = client.auth.sign_up(email, password=password, hashcash=hashcash_proof)
    except EZAuthError as e:
        _handle_error(e)

    if _is_json(ctx):
        print_json(result)
    else:
        console.print(f"[green]{result.get('status', 'OK')}[/green] — check your email for a verification code.")

    code = click.prompt("Verification code")
    try:
        session = client.auth.verify_code(email, code)
    except EZAuthError as e:
        _handle_error(e)

    cfg.access_token = session["access_token"]
    cfg.refresh_token = session.get("refresh_token", "")
    cfg.email = email
    cfg.save()

    if _is_json(ctx):
        print_json(session)
    else:
        console.print(f"[green]Signed up and logged in as {email}[/green]")


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
def login(ctx):
    """Sign in to your account."""
    cfg = CLIConfig.load()
    client = _get_client(cfg)

    email = click.prompt("Email")
    strategy = click.prompt("Strategy", type=click.Choice(["password", "magic_link"]), default="magic_link")

    if strategy == "password":
        password = click.prompt("Password", hide_input=True)
        try:
            session = client.auth.sign_in(email, password=password, strategy="password")
        except EZAuthError as e:
            _handle_error(e)

        cfg.access_token = session["access_token"]
        cfg.refresh_token = session.get("refresh_token", "")
        cfg.email = email
        cfg.save()

        if _is_json(ctx):
            print_json(session)
        else:
            console.print(f"[green]Logged in as {email}[/green]")
    else:
        try:
            result = client.auth.sign_in(email, strategy="magic_link")
        except EZAuthError as e:
            _handle_error(e)

        if not _is_json(ctx):
            console.print(f"[green]{result.get('status', 'OK')}[/green] — check your email for a code.")

        code = click.prompt("Verification code")
        try:
            session = client.auth.verify_code(email, code)
        except EZAuthError as e:
            _handle_error(e)

        cfg.access_token = session["access_token"]
        cfg.refresh_token = session.get("refresh_token", "")
        cfg.email = email
        cfg.save()

        if _is_json(ctx):
            print_json(session)
        else:
            console.print(f"[green]Logged in as {email}[/green]")


# ---------------------------------------------------------------------------
# whoami
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
def whoami(ctx):
    """Show current user info."""
    cfg = CLIConfig.load()
    client = _get_client(cfg)

    if not cfg.access_token:
        console.print("[red]Not logged in. Run 'ezauth login' or 'ezauth signup' first.[/red]")
        raise SystemExit(1)

    try:
        info = client.auth.get_session(access_token=cfg.access_token)
    except EZAuthError as e:
        if e.status == 401 and cfg.refresh_token:
            try:
                session = client.auth.refresh_token(cfg.refresh_token)
                cfg.access_token = session["access_token"]
                cfg.refresh_token = session.get("refresh_token", cfg.refresh_token)
                cfg.save()
                info = client.auth.get_session(access_token=cfg.access_token)
            except EZAuthError:
                console.print("[red]Session expired. Please log in again.[/red]")
                cfg.clear_session()
                raise SystemExit(1)
        else:
            _handle_error(e)

    if _is_json(ctx):
        print_json(info)
    else:
        print_detail(info)


# ---------------------------------------------------------------------------
# logout
# ---------------------------------------------------------------------------

@cli.command()
def logout():
    """Log out and clear local credentials."""
    cfg = CLIConfig.load()
    client = _get_client(cfg)

    if cfg.access_token:
        try:
            client.auth.sign_out(access_token=cfg.access_token)
        except EZAuthError:
            pass  # Best-effort server-side logout

    cfg.clear_session()
    console.print("[green]Logged out.[/green]")


# ===========================================================================
# users
# ===========================================================================

@cli.group()
def users():
    """Manage users (requires secret key)."""
    pass


@users.command("list")
@click.option("--limit", type=int, default=None, help="Max results.")
@click.option("--offset", type=int, default=None, help="Offset for pagination.")
@click.option("--email", default=None, help="Filter by email.")
@click.pass_context
def users_list(ctx, limit, offset, email):
    """List users."""
    cfg = CLIConfig.load()
    _require_secret_key(cfg)
    client = _get_client(cfg)

    try:
        result = client.users.list(limit=limit, offset=offset, email=email)
    except EZAuthError as e:
        _handle_error(e)

    if _is_json(ctx):
        print_json(result)
    else:
        items = result if isinstance(result, list) else result.get("users", result.get("data", [result]))
        print_table(items)


@users.command("create")
@click.option("--email", required=True, help="User email.")
@click.option("--password", default=None, help="User password.")
@click.pass_context
def users_create(ctx, email, password):
    """Create a user."""
    cfg = CLIConfig.load()
    _require_secret_key(cfg)
    client = _get_client(cfg)

    try:
        result = client.users.create(email, password=password)
    except EZAuthError as e:
        _handle_error(e)

    if _is_json(ctx):
        print_json(result)
    else:
        print_detail(result, title="User created")


@users.command("get")
@click.argument("user_id")
@click.pass_context
def users_get(ctx, user_id):
    """Get a user by ID."""
    cfg = CLIConfig.load()
    _require_secret_key(cfg)
    client = _get_client(cfg)

    try:
        result = client.users.get(user_id)
    except EZAuthError as e:
        _handle_error(e)

    if _is_json(ctx):
        print_json(result)
    else:
        print_detail(result)


# ===========================================================================
# sessions
# ===========================================================================

@cli.group()
def sessions():
    """Manage sessions (requires secret key)."""
    pass


@sessions.command("revoke")
@click.argument("session_id")
@click.pass_context
def sessions_revoke(ctx, session_id):
    """Revoke a session."""
    cfg = CLIConfig.load()
    _require_secret_key(cfg)
    client = _get_client(cfg)

    try:
        result = client.sessions.revoke(session_id)
    except EZAuthError as e:
        _handle_error(e)

    if _is_json(ctx):
        print_json(result)
    else:
        console.print("[green]Session revoked.[/green]")


@sessions.command("create-token")
@click.option("--user-id", required=True, help="User ID.")
@click.option("--expires", type=int, default=None, help="Expiration in seconds.")
@click.pass_context
def sessions_create_token(ctx, user_id, expires):
    """Create a sign-in token."""
    cfg = CLIConfig.load()
    _require_secret_key(cfg)
    client = _get_client(cfg)

    try:
        result = client.sessions.create_sign_in_token(user_id, expires_in_seconds=expires)
    except EZAuthError as e:
        _handle_error(e)

    if _is_json(ctx):
        print_json(result)
    else:
        print_detail(result, title="Sign-in token created")


# ===========================================================================
# tables
# ===========================================================================

@cli.group()
def tables():
    """Manage custom database tables (requires secret key)."""
    pass


@tables.command("create")
@click.option("--name", required=True, help="Table name.")
@click.option("--column", multiple=True, help="Column as 'name:type' (repeatable).")
@click.pass_context
def tables_create(ctx, name, column):
    """Create a table."""
    cfg = CLIConfig.load()
    _require_secret_key(cfg)
    client = _get_client(cfg)

    columns = None
    if column:
        columns = []
        for col in column:
            parts = col.split(":", 1)
            if len(parts) != 2:
                console.print(f"[red]Invalid column format '{col}'. Use 'name:type'.[/red]")
                raise SystemExit(1)
            columns.append({"name": parts[0], "type": parts[1]})

    try:
        result = client.tables.create(name, columns=columns)
    except EZAuthError as e:
        _handle_error(e)

    if _is_json(ctx):
        print_json(result)
    else:
        print_detail(result, title="Table created")


@tables.command("list")
@click.pass_context
def tables_list(ctx):
    """List all tables."""
    cfg = CLIConfig.load()
    _require_secret_key(cfg)
    client = _get_client(cfg)

    try:
        result = client.tables.list()
    except EZAuthError as e:
        _handle_error(e)

    if _is_json(ctx):
        print_json(result)
    else:
        items = result if isinstance(result, list) else result.get("tables", result.get("data", [result]))
        print_table(items)


@tables.command("get")
@click.argument("table_id")
@click.pass_context
def tables_get(ctx, table_id):
    """Get table details."""
    cfg = CLIConfig.load()
    _require_secret_key(cfg)
    client = _get_client(cfg)

    try:
        result = client.tables.get(table_id)
    except EZAuthError as e:
        _handle_error(e)

    if _is_json(ctx):
        print_json(result)
    else:
        print_detail(result)


@tables.command("delete")
@click.argument("table_id")
@click.pass_context
def tables_delete(ctx, table_id):
    """Delete a table."""
    cfg = CLIConfig.load()
    _require_secret_key(cfg)
    client = _get_client(cfg)

    try:
        client.tables.delete(table_id)
    except EZAuthError as e:
        _handle_error(e)

    if _is_json(ctx):
        print_json({"status": "deleted"})
    else:
        console.print("[green]Table deleted.[/green]")


# ===========================================================================
# columns
# ===========================================================================

@cli.group()
def columns():
    """Manage table columns (requires secret key)."""
    pass


@columns.command("add")
@click.argument("table_id")
@click.option("--name", required=True, help="Column name.")
@click.option("--type", "col_type", required=True, help="Column type.")
@click.option("--required", is_flag=True, default=False, help="Mark column as required.")
@click.option("--position", type=int, default=None, help="Column position.")
@click.pass_context
def columns_add(ctx, table_id, name, col_type, required, position):
    """Add a column to a table."""
    cfg = CLIConfig.load()
    _require_secret_key(cfg)
    client = _get_client(cfg)

    try:
        result = client.tables.columns.add(
            table_id, name, col_type, required=required, position=position,
        )
    except EZAuthError as e:
        _handle_error(e)

    if _is_json(ctx):
        print_json(result)
    else:
        print_detail(result, title="Column added")


@columns.command("update")
@click.argument("table_id")
@click.argument("column_id")
@click.option("--name", default=None, help="New column name.")
@click.option("--required/--no-required", default=None, help="Set required flag.")
@click.option("--position", type=int, default=None, help="New position.")
@click.pass_context
def columns_update(ctx, table_id, column_id, name, required, position):
    """Update a column."""
    cfg = CLIConfig.load()
    _require_secret_key(cfg)
    client = _get_client(cfg)

    try:
        result = client.tables.columns.update(
            table_id, column_id, name=name, required=required, position=position,
        )
    except EZAuthError as e:
        _handle_error(e)

    if _is_json(ctx):
        print_json(result)
    else:
        print_detail(result, title="Column updated")


@columns.command("delete")
@click.argument("table_id")
@click.argument("column_id")
@click.pass_context
def columns_delete(ctx, table_id, column_id):
    """Delete a column."""
    cfg = CLIConfig.load()
    _require_secret_key(cfg)
    client = _get_client(cfg)

    try:
        client.tables.columns.delete(table_id, column_id)
    except EZAuthError as e:
        _handle_error(e)

    if _is_json(ctx):
        print_json({"status": "deleted"})
    else:
        console.print("[green]Column deleted.[/green]")


# ===========================================================================
# rows
# ===========================================================================

@cli.group()
def rows():
    """Manage table rows (requires secret key)."""
    pass


@rows.command("insert")
@click.argument("table_id")
@click.option("--data", required=True, help="Row data as JSON object.")
@click.pass_context
def rows_insert(ctx, table_id, data):
    """Insert a row."""
    cfg = CLIConfig.load()
    _require_secret_key(cfg)
    client = _get_client(cfg)

    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        console.print("[red]Invalid JSON for --data.[/red]")
        raise SystemExit(1)

    try:
        result = client.tables.rows.insert(table_id, parsed)
    except EZAuthError as e:
        _handle_error(e)

    if _is_json(ctx):
        print_json(result)
    else:
        print_detail(result, title="Row inserted")


@rows.command("get")
@click.argument("table_id")
@click.argument("row_id")
@click.pass_context
def rows_get(ctx, table_id, row_id):
    """Get a row."""
    cfg = CLIConfig.load()
    _require_secret_key(cfg)
    client = _get_client(cfg)

    try:
        result = client.tables.rows.get(table_id, row_id)
    except EZAuthError as e:
        _handle_error(e)

    if _is_json(ctx):
        print_json(result)
    else:
        print_detail(result)


@rows.command("update")
@click.argument("table_id")
@click.argument("row_id")
@click.option("--data", required=True, help="Updated data as JSON object.")
@click.pass_context
def rows_update(ctx, table_id, row_id, data):
    """Update a row."""
    cfg = CLIConfig.load()
    _require_secret_key(cfg)
    client = _get_client(cfg)

    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        console.print("[red]Invalid JSON for --data.[/red]")
        raise SystemExit(1)

    try:
        result = client.tables.rows.update(table_id, row_id, parsed)
    except EZAuthError as e:
        _handle_error(e)

    if _is_json(ctx):
        print_json(result)
    else:
        print_detail(result, title="Row updated")


@rows.command("delete")
@click.argument("table_id")
@click.argument("row_id")
@click.pass_context
def rows_delete(ctx, table_id, row_id):
    """Delete a row."""
    cfg = CLIConfig.load()
    _require_secret_key(cfg)
    client = _get_client(cfg)

    try:
        client.tables.rows.delete(table_id, row_id)
    except EZAuthError as e:
        _handle_error(e)

    if _is_json(ctx):
        print_json({"status": "deleted"})
    else:
        console.print("[green]Row deleted.[/green]")


@rows.command("query")
@click.argument("table_id")
@click.option("--filter", "filter_json", default=None, help="Filter as JSON.")
@click.option("--sort", default=None, help="Sort as 'field:direction'.")
@click.option("--limit", type=int, default=None, help="Max results.")
@click.option("--cursor", default=None, help="Pagination cursor.")
@click.pass_context
def rows_query(ctx, table_id, filter_json, sort, limit, cursor):
    """Query rows in a table."""
    cfg = CLIConfig.load()
    _require_secret_key(cfg)
    client = _get_client(cfg)

    filter_obj = None
    if filter_json:
        try:
            filter_obj = json.loads(filter_json)
        except json.JSONDecodeError:
            console.print("[red]Invalid JSON for --filter.[/red]")
            raise SystemExit(1)

    sort_obj = None
    if sort:
        parts = sort.split(":", 1)
        if len(parts) == 2:
            sort_obj = {"field": parts[0], "direction": parts[1]}
        else:
            sort_obj = {"field": parts[0], "direction": "asc"}

    try:
        result = client.tables.rows.query(
            table_id, filter=filter_obj, sort=sort_obj, limit=limit, cursor=cursor,
        )
    except EZAuthError as e:
        _handle_error(e)

    if _is_json(ctx):
        print_json(result)
    else:
        items = result if isinstance(result, list) else result.get("rows", result.get("data", [result]))
        print_table(items)


# ===========================================================================
# storage
# ===========================================================================

@cli.command()
@click.pass_context
def storage(ctx):
    """Show storage usage."""
    cfg = CLIConfig.load()
    _require_secret_key(cfg)
    client = _get_client(cfg)

    try:
        result = client.storage.get()
    except EZAuthError as e:
        _handle_error(e)

    if _is_json(ctx):
        print_json(result)
    else:
        print_detail(result, title="Storage usage")


if __name__ == "__main__":
    cli()
