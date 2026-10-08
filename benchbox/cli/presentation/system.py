from benchbox.cli.shared import console


def display_system_recommendations(system_profile):
    memory_gb = getattr(system_profile, "memory_total_gb", 8)
    cpu_cores = getattr(system_profile, "cpu_cores_logical", 4)

    console.print("\n[bold cyan]System Recommendations[/bold cyan]")

    if memory_gb >= 32:
        console.print("[green]High-memory system detected: You can run large benchmarks (scale 1.0+)[/green]")
    elif memory_gb >= 16:
        console.print("[yellow]Mid-range system detected: Moderate benchmarks recommended (scale 0.1-1.0)[/yellow]")
    elif memory_gb >= 8:
        console.print("[yellow]Standard system detected: Small to moderate benchmarks (scale 0.01-0.1)[/yellow]")
    else:
        console.print("[red]Limited memory system: Use small scale factors (scale 0.01) to avoid issues[/red]")

    if cpu_cores >= 8:
        console.print("[green]Multi-core system: Concurrent execution recommended for faster results[/green]")
    elif cpu_cores >= 4:
        console.print("[yellow]Quad-core system: Light concurrency can improve performance[/yellow]")
    else:
        console.print("[yellow]Limited cores: Sequential execution recommended[/yellow]")

    if memory_gb >= 16 and cpu_cores >= 8:
        console.print("[bold green]Optimal Setup: Your system can handle production-scale benchmarks[/bold green]")
    elif memory_gb >= 8 and cpu_cores >= 4:
        console.print("[bold yellow]Good Setup: Suitable for development and moderate benchmarking[/bold yellow]")
    else:
        console.print("[bold yellow]Basic Setup: Ideal for testing and learning BenchBox[/bold yellow]")
