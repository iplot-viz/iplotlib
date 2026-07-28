# mint#78 / mint#147 streaming — change summary

All changes are in **iplotlib** (`iplotlib/data_access/streamer.py`, plus one fix in
`iplotlib/interface/iplotSignalAdapter.py`). `mint` and `iplotdataaccess` are unchanged:
the mint side of the spec (no points field in the Stream dialog,
`MINT_MAX_STREAMING_POINTS`) was already implemented on the branch.

Eight commits, `e3df993..9468489`.

## Spec compliance

| Point | Status |
|---|---|
| 1. No points field in Stream dialog | already implemented (`mtStreamConfigurator`) |
| 2. `MINT_MAX_STREAMING_POINTS`, default 10k | already implemented, clamped to 100k |
| 3. First fill = one archive call | already implemented (`_archive_backfill`) |
| 4. No line between archive and first live | already implemented (NaN break) |
| 5. 10k buffer → drop points, one archive re-ask, keep 2 min live | **fixed** (0002, 0003, 0008) |
| 6. Envelope only when column = 1 | already implemented, preserved on new paths |

## The commits

**0001 — reprocess expression signals under the carrier lock.**
`_reprocess()` re-evaluates a single-child expression by reading
`dependencies[0].data_store` off its carrier, but all three callers released
`_signal_lock(carrier)` before calling it. `on_fetch_done()` rebuilt `data_store` in four
separate statements, so a concurrent writer (live handler / top-up / backfill, all on
separate threads) could be mid-write during that read. This produced the garbled
zig-zag traces on derived signals while their raw source PVs plotted fine. Moved the
reprocess inside the lock at all three sites, and made `on_fetch_done()` publish
`data_store` as a single atomic list swap.

**0002 — implement the point-5 window/cap contract.**
`_apply_cap` had been locally decimating the older span instead of dropping and
re-asking, so each pass re-reduced already-reduced samples and the history drifted away
from what the archive holds. The hourly top-up fetched `[now − 1 h, now]`, whose newest
~2 minutes fall inside the archiver's lag and come back empty. Replaced with drop-oldest
plus a full-window refresh worker making one archive call at the point budget.

**0003 — stop the refresh eating the newest chunks and shrinking the window.**
The refresh kept live samples only from the theoretical newest-2-minutes span, so when
the archiver lagged by more than that (processed/downsampled streams are written in
blocks) everything between the archive's real end and that boundary was discarded on
each refresh. Now the live keep-boundary is anchored at the archive reply's *actual* last
timestamp. Separately, the 24 h window eroded from the left because drop-oldest traded
one live second for one ~8.6 s archive bucket, and the refresh re-applied the cap to its
own result. The refresh is now the cap enforcement; the local trim is a safety valve that
only fires beyond 2× the cap.

**0004 — refresh only verbose signals, and scale injection to the window.**
A variable with no samples in the window, or one lone live point, was still swept by the
periodic refresh. Signals are now classified from every archive reply: verbose when the
reply saturated the point budget or a raw request came back decimated, sparse when it
returned under 90% of budget (the band is hysteresis). The periodic tick only visits
verbose signals. Also made the injection cadence follow `window / max_points` clamped to
[1 s, 10 s] instead of a fixed 1 s — every injection copies the buffer, reprocesses
expressions and redraws regardless of how much data arrived, and at 7 days one second
moves the trace far less than a pixel.

*Note: the verbosity classification in this commit was already present in the sandbox
working tree when I started that step. It is included after review rather than having
been written by me — worth a look in case your own tooling produced it.*

**0005 — hold last known value for samples older than the window.**
A live sample stamped 8 July is the feed announcing a value that has not changed since;
appended at face value it stretched the X range 20 days outside the window and squashed
every other trace on the plot. `_hold_stale_samples` anchors the newest pre-window value
at the window start. The archive last-value fallback got the same treatment (its query is
unbounded at the start, so its reply is stale by construction). Also added
`_trim_to_window`, the sliding-window trim that was missing for sparse signals —
amortized behind a 5%-of-window margin.

**0006 — materialize the held value as a step, not a slope.**
0005 emitted only the anchor and the first fresh sample and left the renderer to join
them, so a constant signal was drawn as a window-wide interpolation between two values
differing in the seventh decimal. The held value is now repeated 1 ns before the first
fresh sample. Same fix for the trim anchor.

**0007 — hold the last value across empty spans instead of ramping.**
0006 only covered a stale and a fresh sample arriving *in the same batch*, not the common
case where the anchor came from an earlier backfill and the fresh sample landed on a
later tick. Rather than chase which endpoint differs (an archive value stored as float32
and the same value arriving live as float64 read identically at crosshair precision),
`_step_across_gaps` inserts a zero-order-hold point before any sample following a gap
wider than a hundredth of the window: flat-then-step whichever end differs, exactly flat
when they are equal. Scoped to signals under hold semantics; envelope buffers skipped.

**0008 — stop the archive request storm.**
Three causes of the slow focus changes and autoscale. The refresh trigger was wrong:
`_over_cap` fired whenever the buffer sat above the budget, permanently true for any busy
signal even while it still covered the whole window, so the refresh re-fetched data the
buffer already had. Replaced by `_has_window_hole` — a round trip is only worth making
when more than a tenth of the window is missing at the left edge. Refreshes were not
staggered: added a 2 s global spacing and raised the per-signal minimum from 60 s to
300 s, now applied to periodic refreshes too. And buffer growth followed sample rate
rather than display resolution, so `_reduce_live_batch` reduces each batch to min/max
pairs per bucket, bounding growth by elapsed time. Extremes keep their true coordinates
and NaN breaks survive.

## Environment variables

| Variable | Default | Effect |
|---|---|---|
| `MINT_MAX_STREAMING_POINTS` | 10000 | Per-signal point budget (mint side, clamped to 100k) |
| `MINT_STREAMING_LIVE_SECONDS` | 120 | Live span retained ahead of the archive's lag |
| `MINT_STREAMING_INJECT_SECONDS` | auto | Overrides the computed injection cadence |
| `MINT_STREAMING_REFRESH_SECONDS` | 300 | Per-signal minimum between archive refreshes |

## Validation

Logic-only plus `py_compile` and the offscreen suite (`QT_QPA_PLATFORM=offscreen`):
95 streamer tests, 176 across `data_access`, `interface` and `core`. No live testing was
done — restart the app and reload data before judging any of it.

## Still open

**Y tick labels repeat.** On the pyqtgraph backend the Y axis uses pyqtgraph's default
`AxisItem.tickStrings`, which formats each tick at fixed precision with no common offset,
so a ~5e-7 range around 4.17408 collapses to identical labels. The matplotlib path is
fine — `ExponentScalarFormatter` renders that range as `1e−9+4.17408` with distinct
residual ticks (verified against the real formatter across four data shapes). Fix is to
override the Y `AxisItem.tickStrings` in `pyQtGraphCanvas` to subtract a common offset and
show it in the corner. Not attempted here.

**Bucket-grid storage (proposed, not built).** A fixed-grid ring buffer of exactly
`max_points` buckets, indexed by `(t − epoch) // Δ` with `Δ = window / max_points`, would
make live updates O(1), fix the buffer size permanently, and make window erosion and
refresh churn structurally impossible. After 0008 the input-side reduction plus
hole-driven refresh gets most of that benefit, so I would hold off. It also changes
rendering semantics for verbose signals (min/max band rather than raw samples).

## Review note

0002–0008 are successive corrections to the same mechanism, several fixing my own earlier
attempt in the series. For a reviewable PR, consider squashing 0002–0008 into one commit
and keeping 0001 separate, since the lock race is unrelated:

```bash
git rebase -i HEAD~8    # mark 0003..0008 as 'squash' onto 0002
```
