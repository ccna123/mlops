// Turning a list of drift summaries into the sentence a person would say
// after reading the chart. Kept out of the page as pure functions on plain
// data: this is where every judgement about "is it getting worse" lives, and
// it must be readable on its own.
//
// Severity words stay the API's (`ok`, `warning`, `high`, `insufficient_data`)
// — nothing here invents a level or a threshold. The monitor stage owns the
// thresholds, and a copy of them on this side would drift from it silently.

import { DRIFT_FACTORS } from "./constants";

const RANK = { ok: 0, warning: 1, high: 2 };

// How many of the most recent measurements the "N of the last M" count looks
// at. Five is a window a person can still check by eye against the chart.
export const RECENT_WINDOW = 5;

/**
 * Reads a drift history the way a person would.
 *
 * Args:
 *   history: Summaries newest first, exactly as GET /drift/history returns
 *     them. An empty list is allowed.
 *
 * Returns:
 *   Null when there is nothing to read, otherwise an object with:
 *     latest: the newest summary.
 *     changes: One entry per factor whose verdict differs from the previous
 *       measurement, each {key, label, from, to, worse}. Empty when the last
 *       two measurements agree, or when there is only one.
 *     comparable: Whether `latest` and the previous summary came from the
 *       same model version. Two different versions are two different models,
 *       so a change between them is not a trend.
 *     recentHigh / recentCount: How many of the last RECENT_WINDOW
 *       measurements were graded `high` overall, out of how many exist.
 *     versions: Every distinct model_version present, newest first.
 *
 * Example:
 *   readHistory([{parts: {feature: "high"}, ...}, {parts: {feature: "ok"}, ...}])
 *   # -> { changes: [{key: "feature", from: "ok", to: "high", worse: true}], ... }
 */
export function readHistory(history) {
  if (!Array.isArray(history) || history.length === 0) return null;

  const [latest, previous] = history;
  const changes = previous
    ? DRIFT_FACTORS.map((factor) => ({
        key: factor.key,
        label: factor.label,
        from: previous.parts?.[factor.key],
        to: latest.parts?.[factor.key],
      }))
        .filter((change) => change.from !== change.to)
        // An unmeasured verdict has no rank, so "worse" is left undefined
        // rather than guessed — insufficient_data is not a level.
        .map((change) => ({
          ...change,
          worse:
            RANK[change.to] !== undefined && RANK[change.from] !== undefined
              ? RANK[change.to] > RANK[change.from]
              : undefined,
        }))
    : [];

  const recent = history.slice(0, RECENT_WINDOW);
  const versions = [...new Set(history.map((summary) => summary.model_version))];

  return {
    latest,
    previous: previous ?? null,
    changes,
    comparable: previous ? previous.model_version === latest.model_version : true,
    recentHigh: recent.filter((summary) => summary.severity === "high").length,
    recentCount: recent.length,
    versions,
  };
}

/**
 * Picks the metric to plot for a task type.
 *
 * This is a DISPLAY choice, not a rule: the severity badge always comes from
 * the API. These happen to be the metrics the monitor stage grades on
 * (ml_common.drift.performance_severity), so the line and the badge move
 * together instead of telling two different stories.
 *
 * Args:
 *   taskType: "regression" or "classification".
 *
 * Returns:
 *   The metric key, or null for an unknown task type — in which case the
 *   caller draws no metric chart rather than a chart of something arbitrary.
 *
 * Example:
 *   primaryMetric("regression")  # -> "rmse"
 */
export function primaryMetric(taskType) {
  return { regression: "rmse", classification: "auc" }[taskType] ?? null;
}

/**
 * Finds where the calendar day changes along a series of measurements.
 *
 * The chart spaces measurements evenly because each point is a measurement,
 * not a moment — runs minutes apart and runs days apart look the same on the
 * axis otherwise, and a reader cannot see which is which.
 *
 * Args:
 *   chronological: Summaries oldest first.
 *
 * Returns:
 *   {boundaries, dayLabels}: `boundaries` holds the indexes whose day differs
 *   from the point before them (never index 0), and `dayLabels` maps each of
 *   those indexes, plus 0, to a short "d/M" label.
 *
 * Example:
 *   dayBoundaries([{computed_at: "2026-09-20T16:28:00Z"}, {computed_at: "2026-09-22T13:22:00Z"}])
 *   # -> {boundaries: [1], dayLabels: {0: "20/9", 1: "22/9"}}
 */
export function dayBoundaries(chronological) {
  const boundaries = [];
  const dayLabels = {};
  let lastDay = null;

  chronological.forEach((summary, index) => {
    const date = new Date(summary.computed_at);
    if (Number.isNaN(date.getTime())) return;
    const day = date.toDateString();
    if (lastDay === null) {
      dayLabels[index] = shortDay(date);
    } else if (day !== lastDay) {
      boundaries.push(index);
      dayLabels[index] = shortDay(date);
    }
    lastDay = day;
  });

  return { boundaries, dayLabels };
}

function shortDay(date) {
  return `${date.getDate()}/${date.getMonth() + 1}`;
}

/**
 * Formats a measurement's timestamp for the x axis.
 *
 * Args:
 *   iso: The summary's `computed_at`.
 *
 * Returns:
 *   "HH:mm", with the day carried by the dividers instead so the axis is not
 *   a wall of repeated dates. An unparseable value renders empty rather than
 *   "Invalid Date".
 *
 * Example:
 *   axisTime("2026-09-22T13:22:06+00:00")  # -> "20:22" in UTC+7
 */
export function axisTime(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
}
