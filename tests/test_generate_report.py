"""Tests for the HTML report.

These do not check layout. They check the claims the report makes: that an
unmeasured figure reads "Unavailable" and never 0, that every caveat the numbers
depend on is actually printed, and that nothing from a commit message can escape
into markup.
"""
import unittest

from src.daily import build_daily, build_day_items, by_month, daily_totals
from src.generate_report import (esc, generate_report, initials, period_label,
                                 render_codex, render_daily, render_kpis,
                                 render_methodology, render_notes, render_summary)
from src.rhythm import build_rhythm
from src.totals import build_totals


def commit(date="2026-09-02", time="10:00", added=10, removed=2, files=2,
           repo="api", category="feature", ctype="feat", subject="feat: x",
           hash="abcdef1", attributed=False, concurrent=False, dow=2, hour=10):
    return {"date": date, "time": time, "hash": hash, "repo": repo,
            "email": "ana@work.example", "name": "Ana Perez", "month": date[:7],
            "dow": dow, "hour": hour, "subject": subject,
            "lines_added": added, "lines_removed": removed, "raw_added": added,
            "raw_removed": removed, "files_changed": files,
            "files": [(added, removed, "src/a.ts")], "excluded_files": [],
            "type": ctype, "scope": None, "is_conventional": True,
            "category": category, "is_refactor": False,
            "codex_attributed": attributed, "codex_concurrent": concurrent}


CODEX_AVAILABLE = {
    "available": True, "tasks": 12, "turns": 80, "runtime_seconds": 7200,
    "active_days": 2, "by_day": {"2026-09-02": {"tasks": 1, "turns": 3,
                                                "runtime_seconds": 600}},
    "first_date": "2026-09-02", "last_date": "2026-09-03",
    "coverage": {"sessions_dir": "~/.codex/sessions", "files_found": 20,
                 "files_parsed": 20, "sessions_matched": 12},
    "definitions": {"task": "one session", "turn": "one instruction",
                    "recorded_runtime": "merged turn intervals",
                    "active_day": "a day with a turn"},
}

CODEX_MISSING = {"available": False, "coverage": {"sessions_dir": "~/.codex/sessions",
                                                  "files_found": 0, "files_parsed": 0},
                 "definitions": {}}


def make_data(commits=None, codex=None, period=None, ambiguous=(), duplicates=None,
              days=()):
    commits = commits if commits is not None else [commit()]
    codex = codex if codex is not None else CODEX_MISSING
    rows = build_daily(commits, codex.get("by_day") or {}, days)
    evidence = {"commits": len(commits),
                "attributed": sum(1 for c in commits if c["codex_attributed"]),
                "concurrent_only": sum(1 for c in commits
                                       if c["codex_concurrent"]
                                       and not c["codex_attributed"]),
                "no_evidence": sum(1 for c in commits
                                   if not c["codex_attributed"]
                                   and not c["codex_concurrent"])}
    totals = build_totals(commits)
    return {
        "totals": totals,
        "daily": rows,
        "daily_totals": daily_totals(rows),
        "day_items": build_day_items(commits),
        "monthly": by_month(rows),
        "codex": codex,
        "codex_evidence": evidence,
        "line_kinds": {"counted": {"code": {"added": 10, "removed": 2, "files": 1,
                                            "commits": 1}},
                       "excluded": {"generated": {"added": 900, "removed": 40}}},
        "rhythm": build_rhythm(commits),
        "hotspots": {"files": [], "dirs": [], "extensions": [],
                     "total_files_touched": 1},
        "branches": [],
        "duplicates": duplicates or {},
        "attribution": {"source": "config", "emails": ["ana@work.example"],
                        "detected_emails": [], "ambiguous": list(ambiguous)},
        "meta": {"project": "Catalyst", "person": "Ana Perez",
                 "emails": ["ana@work.example"], "repos": ["api"],
                 "scope": "--all --no-merges", "timezone": "America/Montevideo",
                 "period": period, "generated_at": "2026-09-17 18:00",
                 "cutoff": "2026-09-17 18:00",
                 "range": {"first": totals["first_date"],
                           "last": totals["last_date"]}},
    }


MONTH = {"key": "2026-09", "start": "2026-09-01", "end": "2026-09-17",
         "full_end": "2026-09-30", "label": "September 2026", "month_to_date": True}
CLOSED_MONTH = {**MONTH, "end": "2026-09-30", "month_to_date": False}


class TestHelpers(unittest.TestCase):
    def test_esc_neutralises_markup(self):
        self.assertEqual(esc("<b>&"), "&lt;b&gt;&amp;")

    def test_initials_use_first_and_last_name(self):
        self.assertEqual(initials("Ana Perez"), "AP")

    def test_initials_fall_back_to_two_characters(self):
        self.assertEqual(initials("ana"), "AN")


class TestPeriodLabel(unittest.TestCase):
    def test_a_running_month_says_month_to_date(self):
        label = period_label({"period": MONTH})
        self.assertIn("month to date", label)
        self.assertIn("2026-09-01 → 2026-09-17", label)

    def test_a_finished_month_does_not(self):
        self.assertNotIn("month to date", period_label({"period": CLOSED_MONTH}))

    def test_full_history_names_its_own_range(self):
        label = period_label({"period": None,
                              "range": {"first": "2023-04-25", "last": "2024-08-14"}})
        self.assertIn("Full available history", label)
        self.assertIn("2023-04-25", label)


class TestUnavailableNeverRendersAsZero(unittest.TestCase):
    """The rule the whole report hangs on: no evidence means Unavailable."""

    def test_kpis_say_unavailable_when_no_codex_history_was_read(self):
        html = render_kpis(make_data())
        self.assertIn("Unavailable", html)
        self.assertNotIn(">0<", html.split("CODEX TASKS")[-1][:200])

    def test_the_summary_marks_every_codex_row_unavailable(self):
        html = render_summary(make_data())
        for row in ["Codex tasks", "Codex turns", "Recorded Codex runtime",
                    "Days with recorded Codex activity"]:
            segment = html.split(row)[1][:300]
            self.assertIn("Unavailable", segment, row)

    def test_human_working_hours_is_unavailable_even_with_full_codex_history(self):
        html = render_summary(make_data(codex=CODEX_AVAILABLE))
        self.assertIn("Unavailable", html.split("Human working hours")[1][:300])

    def test_real_figures_render_when_the_history_is_there(self):
        html = render_kpis(make_data(codex=CODEX_AVAILABLE))
        self.assertIn("12", html)
        self.assertIn("2h 00m", render_codex(make_data(codex=CODEX_AVAILABLE)))


class TestNotes(unittest.TestCase):
    def test_month_to_date_is_disclosed_before_any_number(self):
        html = render_notes(make_data(period=MONTH))
        self.assertIn("Month to date", html)
        self.assertIn("2026-09-17", html)

    def test_a_finished_month_carries_no_month_to_date_note(self):
        self.assertNotIn("Month to date",
                         render_notes(make_data(period=CLOSED_MONTH)))

    def test_ambiguous_identities_are_named_and_declared_excluded(self):
        html = render_notes(make_data(
            ambiguous=[{"email": "ana@personal.com", "name": "Ana Perez",
                        "commits": 62}]))
        self.assertIn("ana@personal.com", html)
        self.assertIn("62 commits", html)
        self.assertIn("excluded", html)

    def test_duplicate_content_is_disclosed_with_its_percentage(self):
        html = render_notes(make_data(
            duplicates={"total": {"commits": 100, "redundant": 23}}))
        self.assertIn("23%", html)
        self.assertIn("deduplicated by full SHA", html)

    def test_nothing_to_disclose_renders_nothing(self):
        self.assertEqual(render_notes(make_data()), "")


class TestDailyTable(unittest.TestCase):
    def test_lists_every_day_of_a_short_period_including_idle_ones(self):
        days = [f"2026-09-{d:02d}" for d in range(1, 8)]
        html = render_daily(make_data(days=days))
        for day in days:
            self.assertIn(day, html)
        self.assertIn("including days with no activity", html)

    def test_a_long_range_drops_idle_days_and_says_so(self):
        commits = [commit(date=f"2026-0{m}-0{d}")
                   for m in (1, 2, 3) for d in range(1, 4)]
        days = [f"2026-0{m}-{d:02d}" for m in (1, 2, 3) for d in range(1, 29)]
        html = render_daily(make_data(commits=commits, days=days))
        self.assertIn("idle days omitted", html)

    def test_the_task_total_is_the_period_figure_not_the_column_sum(self):
        # A task active on three days appears in three rows but counts once.
        html = render_daily(make_data(codex=CODEX_AVAILABLE))
        total_row = html.split('class="total-row"')[1]
        self.assertIn(">12<", total_row)

    def test_the_daily_codex_caveat_is_printed_when_there_is_codex_data(self):
        html = render_daily(make_data(codex=CODEX_AVAILABLE))
        self.assertIn("sums to more than the period total", html)

    def test_codex_columns_are_dashes_when_no_history_was_read(self):
        html = render_daily(make_data(days=["2026-09-02"]))
        self.assertNotIn("sums to more than the period total", html)


class TestCodexSection(unittest.TestCase):
    def test_it_renders_even_when_nothing_could_be_read(self):
        # An absent section reads as if the metric were never part of the report.
        html = render_codex(make_data())
        self.assertIn("Codex metrics unavailable", html)
        self.assertIn("~/.codex/sessions", html)

    def test_attribution_and_concurrency_are_presented_as_different_strengths(self):
        html = render_codex(make_data(
            commits=[commit(attributed=True), commit(hash="b", concurrent=True)],
            codex=CODEX_AVAILABLE))
        self.assertIn("Direct evidence", html)
        self.assertIn("not evidence that the assistant wrote", html)

    def test_the_definitions_are_printed_for_the_reader(self):
        html = render_codex(make_data(codex=CODEX_AVAILABLE))
        self.assertIn("Task", html)
        self.assertIn("one instruction", html)

    def test_data_coverage_states_what_was_found_and_parsed(self):
        html = render_codex(make_data(codex=CODEX_AVAILABLE))
        self.assertIn("Data coverage", html)
        self.assertIn("20 session files found", html)


class TestMethodology(unittest.TestCase):
    def test_states_every_limit_the_numbers_depend_on(self):
        html = render_methodology(make_data())
        for phrase in ["not unique lines written",
                       "Merge commits are excluded",
                       "never committed are",
                       "not developer working hours",
                       "Not reliably measurable",
                       "deduplicated by full SHA",
                       "Binary files carry no line counts"]:
            self.assertIn(phrase, html, phrase)

    def test_names_the_identities_the_report_counted(self):
        self.assertIn("ana@work.example", render_methodology(make_data()))

    def test_declares_the_run_read_only(self):
        html = render_methodology(make_data())
        self.assertIn("nothing pushed", html)


class TestGenerateReport(unittest.TestCase):
    def test_produces_a_self_contained_english_document(self):
        html = generate_report(make_data(period=MONTH, codex=CODEX_AVAILABLE))
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn('<html lang="en">', html)
        self.assertIn("</html>", html)
        self.assertNotIn("http://", html.split("<style>")[0])

    def test_the_title_names_the_project_and_the_person(self):
        html = generate_report(make_data())
        self.assertIn("<title>Catalyst — development report · Ana Perez</title>", html)

    def test_a_commit_subject_cannot_escape_into_markup(self):
        html = generate_report(make_data(
            commits=[commit(subject="feat: </script><img src=x onerror=alert(1)>")]))
        self.assertNotIn("<img src=x", html)

    def test_an_empty_period_still_renders_a_complete_report(self):
        html = generate_report(make_data(commits=[], period=MONTH,
                                         days=["2026-09-01", "2026-09-02"]))
        self.assertIn("Executive summary", html)
        self.assertIn("Methodology and data coverage", html)

    def test_every_section_the_report_promises_is_present(self):
        html = generate_report(make_data(period=MONTH, codex=CODEX_AVAILABLE,
                                         days=["2026-09-0%d" % i
                                               for i in range(1, 8)]))
        for title in ["Executive summary", "Daily activity", "Activity calendar",
                      "Monthly breakdown", "Repositories", "Type of work",
                      "Line changes by file type", "Codex activity",
                      "Commit timing", "Methodology and data coverage"]:
            self.assertIn(title, html, title)
