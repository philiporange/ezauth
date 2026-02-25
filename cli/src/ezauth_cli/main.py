import click
import httpx
from rich.console import Console

from ezauth_cli.client import EZAuthClient
from ezauth_cli.config import CLIConfig
from ezauth_cli.hashcash import solve_challenge

console = Console()


def _get_client(cfg: CLIConfig) -> EZAuthClient:
    if not cfg.server_url or not cfg.publishable_key:
        console.print("[red]Not configured. Run 'ezauth configure' first.[/red]")
        raise SystemExit(1)
    return EZAuthClient(cfg.server_url, cfg.publishable_key)


@click.group()
def cli():
    """EZAuth CLI — manage your account."""
    pass


@cli.command()
def configure():
    """Set server URL and publishable key."""
    cfg = CLIConfig.load()
    cfg.server_url = click.prompt("Server URL", default=cfg.server_url or "http://localhost:8000")
    cfg.publishable_key = click.prompt("Publishable key", default=cfg.publishable_key)
    cfg.save()
    console.print("[green]Configuration saved.[/green]")


@cli.command()
def signup():
    """Sign up for a new account."""
    cfg = CLIConfig.load()
    client = _get_client(cfg)

    email = click.prompt("Email")
    password = click.prompt("Password (optional, press Enter to skip)", default="", show_default=False)
    password = password or None

    # Request and solve hashcash challenge
    console.print("Requesting challenge...")
    try:
        challenge_data = client.request_challenge()
    except httpx.HTTPStatusError as e:
        console.print(f"[red]Failed to get challenge: {e.response.text}[/red]")
        raise SystemExit(1)

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

    # Submit signup
    hashcash_proof = {"challenge": challenge_data["challenge"], "nonce": nonce}
    try:
        result = client.signup(email, password, hashcash_proof)
    except httpx.HTTPStatusError as e:
        console.print(f"[red]Signup failed: {e.response.text}[/red]")
        raise SystemExit(1)

    console.print(f"[green]{result.get('status', 'OK')}[/green] — check your email for a verification code.")

    # Prompt for verification code
    code = click.prompt("Verification code")
    try:
        session = client.verify_code(email, code)
    except httpx.HTTPStatusError as e:
        console.print(f"[red]Verification failed: {e.response.text}[/red]")
        raise SystemExit(1)

    cfg.access_token = session["access_token"]
    cfg.refresh_token = session.get("refresh_token", "")
    cfg.email = email
    cfg.save()
    console.print(f"[green]Signed up and logged in as {email}[/green]")


@cli.command()
def login():
    """Sign in to your account."""
    cfg = CLIConfig.load()
    client = _get_client(cfg)

    email = click.prompt("Email")
    strategy = click.prompt("Strategy", type=click.Choice(["password", "magic_link"]), default="magic_link")

    if strategy == "password":
        password = click.prompt("Password", hide_input=True)
        try:
            session = client.signin(email, password=password, strategy="password")
        except httpx.HTTPStatusError as e:
            console.print(f"[red]Login failed: {e.response.text}[/red]")
            raise SystemExit(1)

        cfg.access_token = session["access_token"]
        cfg.refresh_token = session.get("refresh_token", "")
        cfg.email = email
        cfg.save()
        console.print(f"[green]Logged in as {email}[/green]")
    else:
        try:
            result = client.signin(email, strategy="magic_link")
        except httpx.HTTPStatusError as e:
            console.print(f"[red]Login failed: {e.response.text}[/red]")
            raise SystemExit(1)

        console.print(f"[green]{result.get('status', 'OK')}[/green] — check your email for a code.")
        code = click.prompt("Verification code")

        try:
            session = client.verify_code(email, code)
        except httpx.HTTPStatusError as e:
            console.print(f"[red]Verification failed: {e.response.text}[/red]")
            raise SystemExit(1)

        cfg.access_token = session["access_token"]
        cfg.refresh_token = session.get("refresh_token", "")
        cfg.email = email
        cfg.save()
        console.print(f"[green]Logged in as {email}[/green]")


@cli.command()
def whoami():
    """Show current user info."""
    cfg = CLIConfig.load()
    client = _get_client(cfg)

    if not cfg.access_token:
        console.print("[red]Not logged in. Run 'ezauth login' or 'ezauth signup' first.[/red]")
        raise SystemExit(1)

    try:
        info = client.me(cfg.access_token)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401 and cfg.refresh_token:
            # Try refreshing the token
            try:
                session = client.refresh(cfg.refresh_token)
                cfg.access_token = session["access_token"]
                cfg.refresh_token = session.get("refresh_token", cfg.refresh_token)
                cfg.save()
                info = client.me(cfg.access_token)
            except httpx.HTTPStatusError:
                console.print("[red]Session expired. Please log in again.[/red]")
                cfg.clear_session()
                raise SystemExit(1)
        else:
            console.print(f"[red]Failed: {e.response.text}[/red]")
            raise SystemExit(1)

    console.print(f"  User ID:  {info['user_id']}")
    console.print(f"  Email:    {info['email']}")
    console.print(f"  Verified: {info['email_verified']}")


@cli.command()
def logout():
    """Log out and clear local credentials."""
    cfg = CLIConfig.load()
    client = _get_client(cfg)

    if cfg.access_token:
        try:
            client.logout(cfg.access_token)
        except httpx.HTTPStatusError:
            pass  # Best-effort server-side logout

    cfg.clear_session()
    console.print("[green]Logged out.[/green]")


if __name__ == "__main__":
    cli()
