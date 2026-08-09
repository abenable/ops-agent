"""Cursor-based Docker log collector and ``.log`` reader.

The collector runs on a schedule (a ``discord.ext.tasks.loop`` in
``agent.bot.monitor``), fetches only the lines new since the last run for each
watched container, and appends plain ``<iso_ts> <message>`` lines to
``data/logs/<container>/<YYYY-MM-DD>.log``. The reader parses each line into
``{ts, level, raw}`` at read time — no JSON wrapper on disk, so files stay
small and the agent sees more log events per token. The reader is the single
query path over that store, used by the daily/weekly report generator and (as
a middle fallback) by the agent's live log tool when Loki has no data.

Reuses ``agent.tools.docker`` (Engine API, no shell-out) and
``agent.storage.repository.list_watched_containers`` (the ``/watch`` set) so
there is no second source of truth for which containers to track.
"""

from agent.logstore.collector import collect_once
from agent.logstore.reader import iter_lines, iter_lines_for_day, line_count

__all__ = ["collect_once", "iter_lines", "iter_lines_for_day", "line_count"]
