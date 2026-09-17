"""Number formatting shared by the report shell and the calendar heatmap.

Kept in its own module because generate_report.py imports the calendar module, so
the calendar module cannot import back from it without a circular import.
"""


def fmt_int(n):
    """50689 -> '50,689'."""
    return f"{n:,}"


def fmt_signed(n):
    """Net change, always carrying its sign: 120 -> '+120', -30 -> '-30'."""
    return f"+{n:,}" if n > 0 else f"{n:,}"


def short_num(n):
    """Compact form for dense cells: 1234 -> '1.2k'; 0 -> ''."""
    if not n:
        return ""
    if n < 1000:
        return str(n)
    value = n / 1000
    if value >= 10:
        return f"{round(value)}k"
    return f"{value:.1f}k"


def fmt_duration(seconds):
    """Recorded runtime as 'Xh Ym'; under a minute reads '<1m', zero reads '0m'."""
    seconds = int(seconds or 0)
    if seconds == 0:
        return "0m"
    if seconds < 60:
        return "<1m"
    hours, minutes = divmod(seconds // 60, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


def fmt_hours(seconds):
    """Recorded runtime as a decimal hour figure, for tables that total a column."""
    return f"{(seconds or 0) / 3600:.1f}"
