"""MCP Telegram CLI."""

import asyncio
import importlib.metadata
import json
import logging
import os
import sys

from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from datetime import datetime
from functools import wraps
from typing import Annotated, Any

import typer

from mcp.types import Tool
from rich.box import ROUNDED
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from mcp_telegram.server import mcp
from mcp_telegram.telegram import Telegram
from mcp_telegram.types import Message
from mcp_telegram.utils import parse_entity

logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
)

def _version_callback(value: bool) -> None:
    if value:
        try:
            ver = importlib.metadata.version("mcp-telegram")
        except importlib.metadata.PackageNotFoundError:
            ver = "unknown"
        print(f"mcp-telegram {ver}")
        raise typer.Exit()


app = typer.Typer(
    name="mcp-telegram",
    help="MCP Server for Telegram",
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", "-V", callback=_version_callback, is_eager=True),
    ] = False,
) -> None:
    """MCP Server for Telegram."""
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())

console = Console()

_json_opt = typer.Option("--json", "-j", help="Output in JSON format")


def async_command(
    func: Callable[..., Coroutine[Any, Any, None]],
) -> Callable[..., None]:
    """Decorator to handle async Typer commands.

    Args:
        func: An async function that will be wrapped to work with Typer.

    Returns:
        A synchronous function that can be used with Typer.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> None:
        asyncio.run(func(*args, **kwargs))

    return wrapper


@asynccontextmanager
async def telegram_client() -> AsyncIterator[Telegram]:
    """Create and connect a Telegram client for CLI commands.

    Requires API_ID and API_HASH environment variables to be set.
    """
    tg = Telegram()
    try:
        tg.create_client()
    except Exception as e:
        console.print(f"[bold red]Debug: {type(e).__name__}: {e}[/bold red]")
        console.print(
            Panel.fit(
                "[bold red]Missing credentials[/bold red]\n\n"
                "CLI commands require API_ID and API_HASH "
                "environment variables.\n\n"
                "  [bold]export API_ID=your_api_id[/bold]\n"
                "  [bold]export API_HASH=your_api_hash[/bold]\n\n"
                "[dim]Get these from "
                "https://my.telegram.org/apps[/dim]",
                title="Authentication Error",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)
    try:
        await tg.client.connect()
        yield tg
    finally:
        await tg.client.disconnect()  # type: ignore


@app.command()
def version() -> None:
    """Show the MCP Telegram version."""
    try:
        version = importlib.metadata.version("mcp-telegram")
        console.print(
            Panel.fit(
                f"[bold blue]MCP Telegram version {version}[/bold blue]",
                title="📦 Version",
                border_style="blue",
            )
        )
    except importlib.metadata.PackageNotFoundError:
        console.print(
            Panel.fit(
                "[bold red]MCP Telegram version unknown (package not installed)\
                    [/bold red]",
                title="❌ Error",
                border_style="red",
            )
        )
        sys.exit(1)


@app.command()
@async_command
async def login() -> None:
    """Login to Telegram."""
    console.print(
        Panel.fit(
            "[bold blue]Welcome to MCP Telegram![/bold blue]\n\n"
            "To proceed with login, you'll need your Telegram API credentials:\n"
            "1. Visit [link]https://my.telegram.org/apps[/link]\n"
            "2. Create a new application if you haven't already\n"
            "3. Copy your API ID and API Hash",
            title="🚀 Telegram Authentication",
            border_style="blue",
        )
    )

    tg = Telegram()

    console.print("\n[yellow]Please enter your credentials:[/yellow]")

    try:
        api_id = console.input(
            "\n[bold cyan]🔑 API ID[/bold cyan]\n"
            "[dim]Enter your Telegram API ID (found on my.telegram.org)[/dim]\n"
            "> ",
            password=True,
        )

        api_hash = console.input(
            "\n[bold cyan]🔒 API Hash[/bold cyan]\n"
            "[dim]Enter your Telegram API hash (found on my.telegram.org)[/dim]\n"
            "> ",
            password=True,
        )

        phone = console.input(
            "\n[bold cyan]📱 Phone Number[/bold cyan]\n"
            "[dim]Enter your phone number in international format \
                (e.g., +1234567890)[/dim]\n"
            "> "
        )

        tg.create_client(api_id=api_id, api_hash=api_hash)

        with console.status("[bold green]Connecting to Telegram...", spinner="dots"):
            await tg.client.connect()
            console.print(
                "\n[bold green]✓[/bold green] [dim]Connected to Telegram[/dim]"
            )

        def code_callback() -> str:
            return console.input(
                "\n[bold cyan]🔢 Verification Code[/bold cyan]\n"
                "[dim]Enter the code sent to your Telegram[/dim]\n"
                "> "
            )

        def password_callback() -> str:
            return console.input(
                "\n[bold cyan]🔐 Two-Factor Authentication[/bold cyan]\n"
                "[dim]Enter your 2FA password[/dim]\n"
                "> ",
                password=True,
            )

        await tg.client.start(
            phone=phone,
            code_callback=code_callback,
            password=password_callback,
        )  # type: ignore

        console.print("\n[bold green]✓[/bold green] [dim]Successfully logged in[/dim]")

        user = await tg.client.get_me()

        # Save credentials for future CLI/MCP use
        env_file = tg._state_dir / ".env"
        env_file.write_text(f"API_ID={api_id}\nAPI_HASH={api_hash}\n")
        env_file.chmod(0o600)

        console.print(
            Panel.fit(
                f"[bold green]Authentication successful![/bold green]\n"
                f"[dim]Welcome, {user.first_name}! You can now use MCP Telegram commands.[/dim]",  # type: ignore  # noqa: E501
                title="🎉 Success",
                border_style="green",
            )
        )

    except ValueError:
        console.print(
            "\n[bold red]✗ Error:[/bold red] API ID must be a number", style="red"
        )
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[bold red]✗ Error:[/bold red] {str(e)}", style="red")
        sys.exit(1)
    finally:
        if tg.client.is_connected():
            tg.client.disconnect()


@app.command()
def start() -> None:
    """Start the MCP Telegram server."""
    mcp.run()


@app.command()
def logout() -> None:
    """Show instructions on how to logout from Telegram."""
    console.print(
        Panel.fit(
            "[bold blue]How to Logout from Telegram[/bold blue]\n\n"
            "To logout from your Telegram account, please follow these steps:\n\n"
            "1. Open your Telegram app\n"
            "2. Go to [bold]Settings[/bold]\n"
            "3. Select [bold]Privacy and Security[/bold]\n"
            "4. Scroll down to find [bold]'Active Sessions'[/bold]\n"
            "5. Find and terminate the session with the name of your app\n   "
            "(This is the app name you created on [link]my.telegram.org/apps[/link])\n\n"  # noqa: E501
            "[yellow]Note:[/yellow] After logging out, you can use the [bold]clear-session[/bold] "  # noqa: E501
            "command to remove local session data.",
            title="🚪 Logout Instructions",
            border_style="blue",
        )
    )


@app.command()
def clear_session() -> None:
    """Delete the local Telegram session file."""

    session_file = Telegram().session_file.with_suffix(".session")

    tg = Telegram()
    env_file = tg._state_dir / ".env"

    if session_file.exists():
        try:
            os.remove(session_file)
            if env_file.exists():
                os.remove(env_file)
            console.print(
                Panel.fit(
                    "[bold green]Session file successfully deleted![/bold green]\n"
                    "[dim]You can now safely create a new session by logging in again.[/dim]",  # noqa: E501
                    title="🗑️ Session Cleared",
                    border_style="green",
                )
            )
        except Exception as e:
            console.print(
                Panel.fit(
                    f"[bold red]Failed to delete session file:[/bold red]\n{str(e)}",
                    title="❌ Error",
                    border_style="red",
                )
            )
    else:
        console.print(
            Panel.fit(
                "[bold yellow]No session file found![/bold yellow]\n"
                "[dim]The session file may have already been deleted or never existed.[/dim]",  # noqa: E501
                title="ℹ️ Info",
                border_style="yellow",
            )
        )


# ── Telegram operation commands ──────────────────────────────────────


@app.command()
@async_command
async def send(
    entity: Annotated[
        str,
        typer.Option("--id", "-i", help="Chat ID, username, phone number, or 'me'"),
    ],
    message: Annotated[
        str,
        typer.Option("--message", "-m", help="Text message to send"),
    ] = "",
    file: Annotated[
        list[str] | None,
        typer.Option("--file", "-f", help="File path(s) to send"),
    ] = None,
    reply_to: Annotated[
        int | None,
        typer.Option("--reply-to", "-r", help="Message ID to reply to"),
    ] = None,
    json_output: Annotated[bool, _json_opt] = False,
) -> None:
    """Send a message to a user, group, or channel."""
    async with telegram_client() as tg:
        _entity = parse_entity(entity)
        await tg.send_message(_entity, message, file_path=file, reply_to=reply_to)
        if json_output:
            print(json.dumps({"status": "sent", "entity": entity}))
        else:
            console.print(f"[green]Message sent to {entity}[/green]")


@app.command()
@async_command
async def edit(
    entity: Annotated[
        str,
        typer.Option("--id", "-i", help="Chat ID, username, phone number, or 'me'"),
    ],
    message_id: Annotated[
        int,
        typer.Argument(help="ID of the message to edit"),
    ],
    message: Annotated[
        str,
        typer.Argument(help="New message text"),
    ],
    json_output: Annotated[bool, _json_opt] = False,
) -> None:
    """Edit a previously sent message."""
    async with telegram_client() as tg:
        _entity = parse_entity(entity)
        await tg.edit_message(_entity, message_id, message)
        if json_output:
            print(
                json.dumps(
                    {
                        "status": "edited",
                        "entity": entity,
                        "message_id": message_id,
                    }
                )
            )
        else:
            console.print(f"[green]Message {message_id} edited in {entity}[/green]")


@app.command()
@async_command
async def delete(
    entity: Annotated[
        str,
        typer.Option("--id", "-i", help="Chat ID, username, phone number, or 'me'"),
    ],
    message_ids: Annotated[
        list[int],
        typer.Argument(help="Message ID(s) to delete"),
    ],
    json_output: Annotated[bool, _json_opt] = False,
) -> None:
    """Delete messages from a chat."""
    async with telegram_client() as tg:
        _entity = parse_entity(entity)
        await tg.delete_message(_entity, message_ids)
        if json_output:
            print(
                json.dumps(
                    {
                        "status": "deleted",
                        "entity": entity,
                        "message_ids": message_ids,
                    }
                )
            )
        else:
            count = len(message_ids)
            console.print(f"[green]Deleted {count} message(s) from {entity}[/green]")


@app.command()
@async_command
async def messages(
    entity: Annotated[
        str,
        typer.Option("--id", "-i", help="Chat ID, username, phone number, or 'me'"),
    ],
    limit: Annotated[
        int,
        typer.Option("--limit", "-n", help="Max messages to retrieve"),
    ] = 10,
    start_date: Annotated[
        str | None,
        typer.Option("--start", "-s", help="Start date (ISO format)"),
    ] = None,
    end_date: Annotated[
        str | None,
        typer.Option("--end", "-e", help="End date (ISO format)"),
    ] = None,
    unread: Annotated[
        bool,
        typer.Option("--unread", "-u", help="Only unread messages"),
    ] = False,
    mark_as_read: Annotated[
        bool,
        typer.Option("--mark-read", help="Mark messages as read"),
    ] = False,
    json_output: Annotated[bool, _json_opt] = False,
) -> None:
    """Get messages from a chat."""
    _start = datetime.fromisoformat(start_date) if start_date else None
    _end = datetime.fromisoformat(end_date) if end_date else None

    async with telegram_client() as tg:
        _entity = parse_entity(entity)
        result = await tg.get_messages(
            _entity, limit, _start, _end, unread, mark_as_read
        )

        if json_output:
            print(result.model_dump_json(indent=2))
            return

        if result.dialog:
            console.print(
                f"[bold]{result.dialog.title}[/bold] ({result.dialog.type.value})"
            )

        if not result.messages:
            console.print("[yellow]No messages found.[/yellow]")
            return

        table = Table(box=ROUNDED, show_lines=True)
        table.add_column("ID", style="cyan", width=10)
        table.add_column("Date", style="dim", width=19)
        table.add_column("", width=2)
        table.add_column("Message", ratio=3)
        table.add_column("Media", width=15)
        table.add_column("Reply", width=8)

        for msg in result.messages:
            text = (msg.message or "")[:200]
            if msg.message and len(msg.message) > 200:
                text += "..."
            media_str = ""
            if msg.media:
                media_str = msg.media.mime_type or ""
            date_str = ""
            if msg.date:
                date_str = msg.date.strftime("%Y-%m-%d %H:%M:%S")
            reply_str = str(msg.reply_to) if msg.reply_to else ""

            table.add_row(
                str(msg.message_id),
                date_str,
                "\u2192" if msg.outgoing else "\u2190",
                text,
                media_str,
                reply_str,
            )

        console.print(table)


@app.command()
@async_command
async def search(
    query: Annotated[str, typer.Argument(help="Search query")],
    limit: Annotated[
        int,
        typer.Option("--limit", "-n", help="Max results"),
    ] = 10,
    global_search: Annotated[
        bool,
        typer.Option("--global", "-g", help="Search globally"),
    ] = False,
    json_output: Annotated[bool, _json_opt] = False,
) -> None:
    """Search for users, groups, and channels."""
    async with telegram_client() as tg:
        results = await tg.search_dialogs(query, limit, global_search)

        if json_output:
            print(
                json.dumps(
                    [d.model_dump(mode="json") for d in results],
                    indent=2,
                )
            )
            return

        if not results:
            console.print("[yellow]No results found.[/yellow]")
            return

        table = Table(
            title=f"Results for '{query}'",
            box=ROUNDED,
            show_lines=True,
        )
        table.add_column("ID", style="cyan")
        table.add_column("Title", style="bold")
        table.add_column("Username", style="dim")
        table.add_column("Type")
        table.add_column("Can Send")

        for dialog in results:
            username = ""
            if dialog.username:
                username = f"@{dialog.username}"
            table.add_row(
                str(dialog.id),
                dialog.title,
                username,
                dialog.type.value,
                "\u2713" if dialog.can_send_message else "\u2717",
            )

        console.print(table)


@app.command()
@async_command
async def get_draft(
    entity: Annotated[
        str,
        typer.Option("--id", "-i", help="Chat ID, username, phone number, or 'me'"),
    ],
    json_output: Annotated[bool, _json_opt] = False,
) -> None:
    """Get the draft message for a chat."""
    async with telegram_client() as tg:
        _entity = parse_entity(entity)
        draft = await tg.get_draft(_entity)
        if json_output:
            print(json.dumps({"entity": entity, "draft": draft}))
        elif draft:
            console.print(
                Panel(
                    draft,
                    title=f"Draft for {entity}",
                    border_style="blue",
                )
            )
        else:
            console.print(f"[dim]No draft for {entity}[/dim]")


@app.command()
@async_command
async def set_draft(
    entity: Annotated[
        str,
        typer.Option("--id", "-i", help="Chat ID, username, phone number, or 'me'"),
    ],
    message: Annotated[
        str,
        typer.Argument(help="Draft message text"),
    ],
    json_output: Annotated[bool, _json_opt] = False,
) -> None:
    """Set a draft message for a chat."""
    async with telegram_client() as tg:
        _entity = parse_entity(entity)
        await tg.set_draft(_entity, message)
        if json_output:
            print(json.dumps({"status": "saved", "entity": entity}))
        else:
            console.print(f"[green]Draft saved for {entity}[/green]")


@app.command()
@async_command
async def download(
    entity: Annotated[
        str,
        typer.Option("--id", "-i", help="Chat ID, username, phone number, or 'me'"),
    ],
    message_id: Annotated[
        int,
        typer.Argument(help="Message ID containing media"),
    ],
    path: Annotated[
        str | None,
        typer.Option("--path", "-p", help="Download directory"),
    ] = None,
    json_output: Annotated[bool, _json_opt] = False,
) -> None:
    """Download media from a message."""
    async with telegram_client() as tg:
        _entity = parse_entity(entity)
        result = await tg.download_media(_entity, message_id, path)
        if json_output:
            print(result.model_dump_json(indent=2))
        else:
            size = result.media.file_size
            size_str = f"{size:,} bytes" if size else "N/A"
            console.print(
                Panel(
                    f"[bold]Path:[/bold] {result.path}\n"
                    f"[bold]Type:[/bold] "
                    f"{result.media.mime_type or 'unknown'}\n"
                    f"[bold]Name:[/bold] "
                    f"{result.media.file_name or 'N/A'}\n"
                    f"[bold]Size:[/bold] {size_str}",
                    title="Downloaded Media",
                    border_style="green",
                )
            )


@app.command()
@async_command
async def from_link(
    link: Annotated[
        str,
        typer.Argument(help="Telegram message link"),
    ],
    json_output: Annotated[bool, _json_opt] = False,
) -> None:
    """Get a message from a Telegram link."""
    async with telegram_client() as tg:
        msg = await tg.message_from_link(link)
        if json_output:
            print(msg.model_dump_json(indent=2))
        else:
            _print_message(msg)


# ── Output formatting helpers ────────────────────────────────────────


def _print_message(msg: Message) -> None:
    """Format and print a single message to console."""
    parts: list[str] = []
    parts.append(f"[bold]ID:[/bold] {msg.message_id}")
    if msg.sender_id:
        parts.append(f"[bold]Sender:[/bold] {msg.sender_id}")
    direction = "outgoing" if msg.outgoing else "incoming"
    parts.append(f"[bold]Direction:[/bold] {direction}")
    if msg.date:
        date_str = msg.date.strftime("%Y-%m-%d %H:%M:%S")
        parts.append(f"[bold]Date:[/bold] {date_str}")
    if msg.reply_to:
        parts.append(f"[bold]Reply to:[/bold] {msg.reply_to}")
    if msg.media:
        name = msg.media.file_name or "unnamed"
        mime = msg.media.mime_type or "unknown"
        parts.append(f"[bold]Media:[/bold] {mime} ({name})")
    if msg.message:
        parts.append(f"\n{msg.message}")

    console.print(
        Panel(
            "\n".join(parts),
            title="Message",
            border_style="blue",
        )
    )


def _format_parameters(schema: dict[str, Any]) -> str:
    """Formats the parameters from a tool's input schema for display."""
    if not schema.get("properties"):
        return "[dim]No parameters[/dim]"

    params: list[str] = []
    properties: dict[str, dict[str, Any]] = schema.get("properties", {})
    required_params: set[str] = set(schema.get("required", []))

    for name, details in properties.items():
        param_type: str = details.get("type", "any")
        description: str = details.get("description", "")
        param_str: str = f"[bold]{name}[/bold]: [italic]{param_type}[/italic]"
        if description:
            param_str += f" - [dim]{description}[/dim]"

        if name in required_params:
            params.append(f"[red]•[/red] {param_str} [bold red](required)[/bold red]")
        else:
            params.append(f"[dim]•[/dim] {param_str}")

    return "\n".join(params) if params else "[dim]No parameters[/dim]"


@app.command()
@async_command
async def tools() -> None:
    """List all available tools in a table format."""
    try:
        tools: list[Tool] = await mcp.list_tools()
    except Exception as e:
        console.print(f"[bold red]Error fetching tools:[/bold red] {e}")
        raise typer.Exit(code=1)

    if not tools:
        console.print("[yellow]No tools available.[/yellow]")
        return

    table = Table(
        title="🔧 Available Tools",
        box=ROUNDED,
        show_header=True,
        header_style="bold blue",
        show_lines=True,
        expand=True,
    )

    table.add_column("Name", style="cyan", width=20, overflow="fold")
    table.add_column("Description", style="dim", ratio=2, overflow="fold")
    table.add_column("Parameters", ratio=3, overflow="fold")

    for tool in tools:
        table.add_row(
            f"[bold]{tool.name}[/bold]",
            tool.description or "[dim]No description[/dim]",
            _format_parameters(tool.inputSchema),
        )

    console.print(table)
