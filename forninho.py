import logging
import os
import signal
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

import typer
from click import Option, echo
from click.core import Context, Parameter
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from core import (
    ConnectionManager,
    MetricsCollector,
    QueryLoader,
    ReportExporter,
    WarmupEngine,
    compare_phases,
)

APP_NAME = "forninho"
LOG_DIR = Path.home() / ".forninho" / "logs"


class AjudaEmPortugues:
    def get_help_option(self, ctx: Context) -> Option | None:
        help_options = self.get_help_option_names(ctx)
        if not help_options or not self.add_help_option:
            return None

        def show_help(ctx: Context, param: Parameter, value: str) -> None:
            if value and not ctx.resilient_parsing:
                echo(ctx.get_help(), color=ctx.color)
                ctx.exit()

        return Option(
            help_options,
            is_flag=True,
            is_eager=True,
            expose_value=False,
            callback=show_help,
            help="Mostra esta mensagem e sai.",
        )


class GrupoTyperPortugues(AjudaEmPortugues, typer.core.TyperGroup):
    pass


class ComandoTyperPortugues(AjudaEmPortugues, typer.core.TyperCommand):
    pass


app = typer.Typer(
    name=APP_NAME,
    cls=GrupoTyperPortugues,
    help="Ferramenta de warm-up de banco para MySQL/HeatWave pós-migração.",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


@app.callback()
def cli() -> None:
    """Ferramenta de warm-up de banco para MySQL/HeatWave pós-migração."""


def _setup_logging() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    filename = LOG_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        filename=filename,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    logging.getLogger("mysql").setLevel(logging.WARNING)
    return filename


def _color_for_ms(ms: float) -> str:
    if ms < 100:
        return "green"
    if ms < 500:
        return "yellow"
    return "red"


def _default_output(fmt: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = "json" if fmt == "json" else "csv"
    return f"./forninho_report_{stamp}.{ext}"


def _render_queries_table(queries: list) -> Table:
    table = Table(title="Consultas carregadas", show_lines=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Origem", style="cyan")
    table.add_column("Peso", justify="right")
    table.add_column("Consulta (prévia)")
    for i, q in enumerate(queries, 1):
        preview = q["sql"][:100].replace("\n", " ")
        if len(q["sql"]) > 100:
            preview += "…"
        table.add_row(str(i), q["source"], str(q["weight"]), preview)
    return table


def _render_config_table(
    mode,
    threads,
    iterations,
    delay_ms,
    timeout,
    connect_timeout,
    connect_retries,
) -> Table:
    table = Table(title="Configuração do warm-up", show_header=False)
    table.add_column("Parâmetro", style="bold")
    table.add_column("Valor")
    table.add_row("Modo", mode)
    table.add_row("Threads (fase concorrente)", str(threads))
    table.add_row("Iterações", str(iterations))
    table.add_row("Intervalo (ms)", str(delay_ms))
    table.add_row("Timeout (s)", str(timeout))
    table.add_row("Timeout de conexão (s)", str(connect_timeout))
    table.add_row("Tentativas de conexão", str(connect_retries))
    return table


def _render_comparison_table(comparisons: list, top: int = 15) -> Table:
    color_by_class = {"HOT": "red", "WARN": "yellow", "OK": "green", "N/A": "dim"}
    table = Table(title=f"Comparação solo × concorrente (top {top} degradações)")
    table.add_column("Hash", style="dim")
    table.add_column("solo p95 (ms)", justify="right")
    table.add_column("concorrente p95 (ms)", justify="right")
    table.add_column("Δ ms", justify="right")
    table.add_column("Δ %", justify="right")
    table.add_column("classe")
    table.add_column("consulta")
    for c in comparisons[:top]:
        cls = c["classification"]
        color = color_by_class.get(cls, "white")
        delta_pct = c["delta_pct"]
        delta_pct_str = (
            f"{delta_pct:+.1f}%" if isinstance(delta_pct, (int, float)) else "∞"
        )
        table.add_row(
            c["query_hash"][:8],
            f"{c['solo_p95_ms']:.1f}",
            f"{c['concurrent_p95_ms']:.1f}",
            f"{c['delta_ms']:+.1f}",
            delta_pct_str,
            f"[{color}]{cls}[/{color}]",
            c["query_preview"],
        )
    return table


def _render_summary(collector: MetricsCollector) -> None:
    stats = collector.per_query_stats()
    stats_sorted_p95 = sorted(stats, key=lambda s: s["p95_ms"], reverse=True)[:5]
    stats_sorted_err = sorted(stats, key=lambda s: s["errors"], reverse=True)
    stats_sorted_err = [s for s in stats_sorted_err if s["errors"] > 0][:5]

    console.print()
    summary = Table(title="Sumário", show_header=False)
    summary.add_column("Métrica", style="bold")
    summary.add_column("Valor")
    summary.add_row("Total executadas", str(collector.total_executions))
    summary.add_row(
        "Com erro",
        f"[red]{collector.total_errors}[/red]" if collector.total_errors else "0",
    )
    summary.add_row("Duração total", f"{collector.duration_seconds:.2f} s")
    summary.add_row("QPS médio", f"{collector.qps:.1f}")
    summary.add_row("Latência média (ms)", f"{collector.avg_ms:.2f}")
    console.print(summary)

    if stats_sorted_p95:
        slow = Table(title="Top 5 consultas mais lentas (p95)")
        slow.add_column("Hash", style="dim")
        slow.add_column("Origem")
        slow.add_column("Execuções", justify="right")
        slow.add_column("p95 ms", justify="right")
        slow.add_column("p99 ms", justify="right")
        slow.add_column("Consulta")
        for s in stats_sorted_p95:
            color = _color_for_ms(s["p95_ms"])
            slow.add_row(
                s["query_hash"][:8],
                s["source"],
                str(s["executions"]),
                f"[{color}]{s['p95_ms']:.2f}[/{color}]",
                f"{s['p99_ms']:.2f}",
                s["query_preview"],
            )
        console.print(slow)

    if stats_sorted_err:
        err_table = Table(title="Top 5 consultas com mais erros")
        err_table.add_column("Hash", style="dim")
        err_table.add_column("Erros", justify="right", style="red")
        err_table.add_column("Último erro")
        err_table.add_column("Consulta")
        for s in stats_sorted_err:
            err_table.add_row(
                s["query_hash"][:8],
                str(s["errors"]),
                (s.get("last_error") or "")[:60],
                s["query_preview"],
            )
        console.print(err_table)


def _run_phase(
    *,
    phase_name: str,
    phase_threads: int,
    queries: list,
    iterations: int,
    delay_ms: int,
    ignore_errors: bool,
    timeout: int,
    conn: ConnectionManager,
) -> MetricsCollector:
    console.print(
        f"\n[bold cyan]▶ Fase {phase_name}[/bold cyan] "
        f"([dim]threads={phase_threads}, iterações={iterations}[/dim])"
    )

    collector = MetricsCollector()
    collector.start()

    total_tasks = sum(iterations * max(1, q["weight"]) for q in queries)

    progress = Progress(
        TextColumn(f"[bold]{phase_name}[/bold]"),
        BarColumn(),
        TextColumn(
            "{task.completed}/{task.total} · "
            "{task.fields[qps]:.1f} QPS · "
            "média {task.fields[avg]:.0f}ms · "
            "{task.fields[errors]} erros"
        ),
        TimeElapsedColumn(),
        console=console,
    )
    pbar_task = progress.add_task(
        phase_name, total=total_tasks, qps=0.0, avg=0.0, errors=0
    )

    def on_progress(result: dict) -> None:
        collector.add_result(result)
        progress.update(
            pbar_task,
            advance=1,
            qps=collector.qps,
            avg=collector.avg_ms,
            errors=collector.total_errors,
        )

    engine = WarmupEngine(
        connection_manager=conn,
        queries=queries,
        iterations=iterations,
        threads=phase_threads,
        delay_ms=delay_ms,
        ignore_errors=ignore_errors,
        timeout=timeout,
        callback_progress=on_progress,
    )

    stop_event = threading.Event()

    def handle_sigint(signum, frame):
        if stop_event.is_set():
            return
        stop_event.set()
        console.print(
            "\n[yellow]⚠ Interrupção recebida. Encerrando fase…[/yellow]"
        )
        engine.stop()

    previous_handler = signal.signal(signal.SIGINT, handle_sigint)
    try:
        with progress:
            engine.run()
    finally:
        signal.signal(signal.SIGINT, previous_handler)
        collector.finish()

    return collector


def _gate_check(
    collector: MetricsCollector,
    timeout: int,
    gate_error_pct: float,
    gate_slowest_ratio: float,
) -> tuple:
    total = collector.total_executions
    errors = collector.total_errors
    error_pct = (errors / total * 100.0) if total else 0.0

    slowest_ms = 0.0
    for s in collector.per_query_stats():
        if s["p95_ms"] > slowest_ms:
            slowest_ms = s["p95_ms"]
    slowest_ratio = slowest_ms / (timeout * 1000.0) if timeout else 0.0

    reasons = []
    if error_pct > gate_error_pct:
        reasons.append(
            f"taxa de erro {error_pct:.1f}% > limite {gate_error_pct:.0f}%"
        )
    if slowest_ratio > gate_slowest_ratio:
        reasons.append(
            f"consulta mais lenta p95 {slowest_ms/1000:.1f}s "
            f"({slowest_ratio*100:.0f}% do timeout) > limite "
            f"{gate_slowest_ratio*100:.0f}%"
        )
    return (len(reasons) == 0, reasons, error_pct, slowest_ms)


@app.command(cls=ComandoTyperPortugues)
def run(
    host: str = typer.Option(..., help="Host do banco"),
    user: str = typer.Option(..., help="Usuário do banco"),
    database: str = typer.Option(..., help="Banco alvo"),
    port: int = typer.Option(3306, help="Porta"),
    password: Optional[str] = typer.Option(
        None,
        help="Senha (padrão: lida de DB_PASSWORD)",
    ),
    sql: Path = typer.Option(..., "--sql", help="Arquivo .sql com consultas"),
    mode: str = typer.Option(
        "two-phase",
        "--mode",
        help="Modo de execução: sequential | parallel | two-phase",
    ),
    iterations: int = typer.Option(3, help="Iterações por consulta"),
    threads: int = typer.Option(4, help="Threads simultâneas (fase concorrente)"),
    delay_ms: int = typer.Option(
        0, "--delay-ms", help="Intervalo entre execuções em ms"
    ),
    ignore_errors: bool = typer.Option(True, help="Ignora erros de consulta"),
    timeout: int = typer.Option(30, help="Timeout por consulta em segundos"),
    connect_timeout: int = typer.Option(
        10,
        "--connect-timeout",
        help="Timeout para abrir conexão com o banco, em segundos",
    ),
    connect_retries: int = typer.Option(
        8,
        "--connect-retries",
        help="Tentativas para abrir conexão com o banco",
    ),
    connect_retry_delay: float = typer.Option(
        2.0,
        "--connect-retry-delay",
        help="Intervalo entre tentativas de conexão, em segundos",
    ),
    gate_error_pct: float = typer.Option(
        50.0,
        "--gate-error-pct",
        help="Aborta fase 2 se erro % na fase solo > este valor",
    ),
    gate_slowest_ratio: float = typer.Option(
        0.9,
        "--gate-slowest-ratio",
        help="Aborta fase 2 se p95 da mais lenta na fase solo > razão×timeout",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Ignora o critério e segue pra fase concorrente mesmo assim",
    ),
    output: Optional[Path] = typer.Option(None, help="Arquivo de relatório"),
    fmt: str = typer.Option("csv", "--format", help="Formato: csv ou json"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Lista consultas sem executar"
    ),
):
    log_path = _setup_logging()
    logger = logging.getLogger(APP_NAME)

    fmt = fmt.lower()
    if fmt not in ("csv", "json"):
        console.print("[red]✗ Formato inválido. Use csv ou json.[/red]")
        raise typer.Exit(code=2)

    loader = QueryLoader()

    if not sql.exists():
        console.print(f"[red]✗ Arquivo não encontrado: {sql}[/red]")
        raise typer.Exit(code=2)

    sql_queries = loader.load_from_sql_file(str(sql))
    sql_count = len(sql_queries)

    merged = loader.merge_and_deduplicate([sql_queries])

    if not merged:
        console.print("[red]✗ Nenhuma consulta executável encontrada.[/red]")
        raise typer.Exit(code=1)

    console.print(
        f"[green]✓ {sql_count} consultas carregadas do .sql · "
        f"{len(merged)} únicas[/green]"
    )

    if dry_run:
        console.print(_render_queries_table(merged))
        console.print("[yellow]Simulação — nenhuma consulta foi executada.[/yellow]")
        raise typer.Exit(code=0)

    pwd = password or os.environ.get("DB_PASSWORD")
    if not pwd:
        console.print(
            "[red]✗ Senha não informada. Use --password ou defina DB_PASSWORD.[/red]"
        )
        raise typer.Exit(code=2)

    conn = ConnectionManager(
        host=host,
        port=port,
        user=user,
        password=pwd,
        database=database,
        connection_timeout=connect_timeout,
        connection_retries=connect_retries,
        retry_delay_seconds=connect_retry_delay,
    )

    logger.info("Testando conexão em %s:%s/%s", host, port, database)
    ok, msg = conn.test_connection()
    if not ok:
        console.print(f"[red]✗ {msg}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]✓ Conectado a {host}:{port}/{database}[/green] · {msg}")

    mode = mode.lower()
    if mode not in ("sequential", "parallel", "two-phase"):
        console.print(
            "[red]✗ --mode inválido. Use sequential | parallel | two-phase.[/red]"
        )
        raise typer.Exit(code=2)

    console.print(
        _render_config_table(
            mode,
            threads,
            iterations,
            delay_ms,
            timeout,
            connect_timeout,
            connect_retries,
        )
    )

    solo_collector: Optional[MetricsCollector] = None
    conc_collector: Optional[MetricsCollector] = None
    execution_failed = False

    try:
        if mode in ("sequential", "two-phase"):
            solo_collector = _run_phase(
                phase_name="solo",
                phase_threads=1,
                queries=merged,
                iterations=iterations,
                delay_ms=delay_ms,
                ignore_errors=ignore_errors,
                timeout=timeout,
                conn=conn,
            )
            _render_summary(solo_collector)

        if mode == "two-phase":
            ok, reasons, err_pct, slowest_ms = _gate_check(
                solo_collector, timeout, gate_error_pct, gate_slowest_ratio
            )
            if not ok:
                console.print(
                    f"\n[yellow]⚠ Critério entre fases violado:[/yellow]"
                )
                for r in reasons:
                    console.print(f"  · {r}")
                if not force:
                    console.print(
                        "[red]✗ Fase concorrente abortada. "
                        "Use --force pra prosseguir mesmo assim.[/red]"
                    )
                    mode = "sequential"
                else:
                    console.print(
                        "[yellow]⚠ --force ativo — prosseguindo pra fase concorrente.[/yellow]"
                    )
            else:
                console.print(
                    f"\n[green]✓ Critério OK[/green] "
                    f"(erros {err_pct:.1f}%, mais lenta {slowest_ms/1000:.1f}s)"
                )

        if mode in ("parallel", "two-phase"):
            conc_collector = _run_phase(
                phase_name="concorrente",
                phase_threads=threads,
                queries=merged,
                iterations=iterations,
                delay_ms=delay_ms,
                ignore_errors=ignore_errors,
                timeout=timeout,
                conn=conn,
            )
            _render_summary(conc_collector)
    except Exception as exc:
        execution_failed = True
        logger.exception("Falha no warm-up")
        console.print(f"[red]✗ Erro durante execução: {exc}[/red]")

    comparisons: list = []
    if solo_collector and conc_collector:
        comparisons = compare_phases(
            solo_collector.per_query_stats(),
            conc_collector.per_query_stats(),
        )
        console.print()
        console.print(_render_comparison_table(comparisons))

    out_path = Path(output) if output else Path(_default_output(fmt))
    exporter = ReportExporter()
    report_written = False

    if fmt == "json":
        payload_results: dict = {}
        if solo_collector:
            payload_results["solo"] = solo_collector.per_query_stats()
        if conc_collector:
            payload_results["concorrente"] = conc_collector.per_query_stats()
        if comparisons:
            payload_results["comparativo"] = comparisons
        metadata = {
            "data_hora": datetime.now(UTC).isoformat(timespec="seconds"),
            "host": host,
            "banco": database,
            "modo": mode,
            "total_consultas": len(merged),
            "threads_concorrentes": threads,
            "iteracoes": iterations,
            "timeout_segundos": timeout,
            "total_execucoes_solo": (
                solo_collector.total_executions if solo_collector else 0
            ),
            "total_execucoes_concorrente": (
                conc_collector.total_executions if conc_collector else 0
            ),
            "duracao_solo_segundos": (
                round(solo_collector.duration_seconds, 3) if solo_collector else 0
            ),
            "duracao_concorrente_segundos": (
                round(conc_collector.duration_seconds, 3) if conc_collector else 0
            ),
        }
        exporter.export_json(payload_results, str(out_path), metadata)
        report_written = True
    else:
        if out_path.exists():
            out_path.unlink()
        if solo_collector:
            exporter.export_csv(
                solo_collector.per_query_stats(), str(out_path), phase="solo"
            )
            report_written = True
        if conc_collector:
            exporter.export_csv(
                conc_collector.per_query_stats(), str(out_path), phase="concorrente"
            )
            report_written = True
        if comparisons:
            compare_path = out_path.with_name(out_path.stem + "_compare.csv")
            exporter.export_comparison_csv(comparisons, str(compare_path))
            console.print(f"[green]✓ Comparativo salvo em {compare_path}[/green]")

    if report_written:
        console.print(f"[green]✓ Relatório salvo em {out_path}[/green]")
    else:
        console.print("[yellow]Nenhum relatório foi gerado.[/yellow]")
    console.print(f"[dim]Log completo: {log_path}[/dim]")

    if execution_failed:
        raise typer.Exit(code=1)


def main():
    try:
        app()
    except typer.Exit:
        raise
    except Exception as exc:
        console.print(f"[red]✗ Erro inesperado: {exc}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
