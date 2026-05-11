#!/usr/bin/env python3
"""
Facebook Graph Scraper — CLI entry point.

Usage examples:
  # Scrape a public page
  python main.py scrape --target page --url https://www.facebook.com/vnexpress.net

  # Scrape a public group
  python main.py scrape --target group --url https://www.facebook.com/groups/XXXXX

  # Search posts by keyword
  python main.py scrape --target search --query "ẩm thực sài gòn" --max-posts 200

  # Scrape a hashtag
  python main.py scrape --target hashtag --query foodreview --max-posts 100

  # Scrape a single post
  python main.py scrape --target post --url https://www.facebook.com/permalink/XXXX

  # Multi-target from YAML file
  python main.py scrape --from-file targets.yaml

  # Interactive login (saves cookies for future runs)
  python main.py login --email user@email.com

  # Show database stats
  python main.py stats
"""
import asyncio
import sys
import json
from pathlib import Path

import click
import yaml
from loguru import logger
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
def cli():
    """Facebook Graph Scraper for GNN Training Data Collection"""
    pass


@cli.command()
@click.option("--target", type=click.Choice(["page", "group", "search", "hashtag", "post"]),
              help="Type of target to scrape")
@click.option("--url", default=None, help="Facebook URL to scrape")
@click.option("--query", default=None, help="Search query or hashtag")
@click.option("--max-posts", default=100, type=int, help="Maximum posts to scrape")
@click.option("--from-file", default=None, help="YAML file with list of targets")
@click.option("--config", default="config.yaml", help="Config file path")
@click.option("--email", default=None, envvar="FB_EMAIL", help="Facebook email (or set FB_EMAIL)")
@click.option("--password", default=None, envvar="FB_PASSWORD", help="Facebook password (or set FB_PASSWORD)")
@click.option("--headless", is_flag=True, default=False, help="Run browser in headless mode")
def scrape(target, url, query, max_posts, from_file, config, email, password, headless):
    """Scrape Facebook posts, comments, and media"""
    from src.crawler import FacebookCrawler

    # Build targets list
    targets = []
    if from_file:
        with open(from_file) as f:
            targets = yaml.safe_load(f)
        console.print(f"[bold green]Loaded {len(targets)} targets from {from_file}[/]")
    elif target and (url or query):
        targets = [{"type": target, "url": url or "", "query": query or url or "", "max_posts": max_posts}]
    else:
        console.print("[bold red]Error: Specify --target + --url/--query, or --from-file[/]")
        sys.exit(1)

    # Apply headless override
    if headless:
        _patch_config(config, {"scraper": {"headless": True}})

    console.print(f"[bold cyan]Starting scraper for {len(targets)} target(s)...[/]")
    crawler = FacebookCrawler(config_path=config)
    asyncio.run(crawler.scrape_targets(targets, email=email, password=password))


@cli.command()
@click.option("--email", prompt="Facebook email", envvar="FB_EMAIL")
@click.option("--password", prompt="Facebook password", hide_input=True, envvar="FB_PASSWORD")
@click.option("--config", default="config.yaml")
def login(email, password, config):
    """Login to Facebook and save session cookies"""
    from src.crawler import FacebookCrawler

    async def _login():
        from src.utils.browser import BrowserManager
        from src.scrapers.base import BaseScraper
        import yaml

        with open(config) as f:
            cfg = yaml.safe_load(f)

        async with BrowserManager(cfg.get("scraper", {})) as bm:
            context = await bm.start()
            scraper = BaseScraper(context, {})
            success = await scraper.login_with_credentials(email, password)
            if success:
                console.print("[bold green]Login successful! Cookies saved.[/]")
            else:
                console.print("[bold red]Login failed. Check credentials or solve CAPTCHA manually.[/]")

    asyncio.run(_login())


@cli.command()
@click.option("--config", default="config.yaml")
def stats(config):
    """Show database statistics"""
    import asyncio

    async def _stats():
        from src.storage.database import Database
        import yaml

        with open(config) as f:
            cfg = yaml.safe_load(f)

        db_path = cfg.get("storage", {}).get("db_path", "data/facebook_graph.db")
        if not Path(db_path).exists():
            console.print("[yellow]No database found yet. Run scrape first.[/]")
            return

        async with Database(db_path) as db:
            s = await db.get_stats()

        table = Table(title="Facebook Graph Database Stats")
        table.add_column("Table", style="cyan")
        table.add_column("Records", justify="right", style="green")
        for k, v in s.items():
            table.add_row(k, str(v))
        console.print(table)

    asyncio.run(_stats())


@cli.command()
@click.argument("targets_file")
def validate_targets(targets_file):
    """Validate a targets YAML file"""
    try:
        with open(targets_file) as f:
            targets = yaml.safe_load(f)
        console.print(f"[green]Valid YAML with {len(targets)} targets:[/]")
        for t in targets:
            console.print(f"  - {t.get('type', '?')} | {t.get('url', t.get('query', '?'))}")
    except Exception as e:
        console.print(f"[red]Invalid file: {e}[/]")


def _patch_config(config_path: str, overrides: dict):
    """Apply runtime overrides to config"""
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    for section, values in overrides.items():
        if section in cfg:
            cfg[section].update(values)
        else:
            cfg[section] = values
    # Write to temp
    import tempfile
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    yaml.dump(cfg, tmp)
    return tmp.name


if __name__ == "__main__":
    cli()
