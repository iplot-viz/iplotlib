# Plot X versus Y when X is not the time — shared-time following in both directions

Closes iplot-viz/mint#120.

## Behaviour

With *shared time* ticked, an X-versus-Y plot (MINT row with `x_expr='${A}.data'`, empty name) now participates in the shared group in both directions:

**Forward — zoom on a time plot.** The X-versus-Y plot follows: its signal is re-evaluated over the propagated time window (dependencies refetched by their own plots, expressions recomputed over the fresh buffers) and its X axis is rescaled to the re-derived data range. Undo restores the whole group consistently.

**Reverse — zoom on the X-versus-Y plot.** When the X column is invertible, the selected X range is mapped back to a time window and drives the whole group through the ordinary forward path. Invertibility is decided on the dependency's **original samples, before time alignment**: for a plain accessor (`${A}.data`), A's raw buffer must increase strictly monotonically; the time indexes are then retrieved through the original (data, time) pairs, exactly. The mapped window is clamped to the originally requested range, so a reverse zoom-out can never request data beyond the workspace range.

**Non-invertible X.** Non-monotonic data, or a data-independent expression such as `np.ones(10)` (no time base at all), keeps the zoom local; the other plots are untouched — per the issue: *"if X is not a bijection then we can't retrieve the corresponding time"*.

## Design notes

- **Group membership and routing** (`_get_all_shared_axes`, `_x_axis_update_callback`): data-valued X-versus-Y plots sharing the group's time base are routed to a reprocess-follower path (`_follow_shared_time_window`) instead of the axis-limit path, which is meaningless in a non-time X domain. Time-base sharing compares the signals' requested ts ranges.
- **Forced reprocessing of expression-only signals** (`set_time_window`, one-shot `_ts_is_time_window` flag): signals with an empty name have no data access; the trusted-window flag makes `_do_data_access` re-run processing so `${A}.data`/`${B}.data` are re-evaluated over the dependencies' new buffers.
- **Window cropping** (`ParserHelper.evaluate`): dependencies legitimately keep raw superset buffers once a zoom drops below the downsampling threshold (no refetch on deeper zooms; time plots crop through the axis view). The evaluated result of pure expression signals is therefore cropped to the signal's requested ts window using the (realigned union or common) time base — otherwise the X-versus-Y range stops following deeper zooms.
- **Axis offset preservation** (`_follow_shared_time_window`): DI_RELTIME values are epoch timestamps in microseconds (~1.7e15), above the `create_offset` threshold, so the axis carries an integer midpoint offset and the tick labels show implementation coordinates. The follower keeps the existing offset instead of re-deriving it from the zoomed range, so the displayed numbers stay comparable across zooms and with the time plot showing the same quantity on Y.
- **Realignment interpolation** (`interpolation` field, default `'auto'`; `resolve_alignment_kind`): sample-and-hold stays the behaviour for event-driven signals (a new value is only published on change). `'auto'` picks linear only when every dependency is raw (not downsampled) and its observed rate exceeds `CONTINUOUS_RATE_THRESHOLD_HZ` (100 Hz); an explicit `InterpolationKind` on the signal always wins. This removes the staircase-of-vertical-strokes rendering of a 2.5 kHz X against a 1 MHz Y without touching slow signals.
- **NaN-safe offset transform** (`transform_data`): realigned signals can carry NaNs (edge extrapolation); casting them to int64 produced INT64_MIN, which drew as a spurious line across the plot. NaNs now survive the offset subtraction and render as gaps.
- **Diagnostics**: the `mint#120:`-prefixed logs used during live diagnosis are kept at DEBUG (the per-zoom group/routing summary is gated on `isEnabledFor`). Raising the logger to DEBUG restores the full trace: propagated window, group membership and per-plot routing, forced reprocess, per-expression results, realign decision with the chosen interpolation kind, rescale values and offsets, and reverse-mapping decisions.

## Points for review

- The evaluate-time window cropping applies only to signals with an empty name (MINT X-versus-Y rows); time plots and named signals are untouched.
- `'auto'` interpolation changes the realignment of expression signals whose dependencies are all raw and fast; any downsampled or slow dependency keeps `'previous'` for the whole alignment. The threshold is a module constant.
- The reverse mapping's fallback for compound expressions (no single original buffer) uses the evaluated X over its retained time base and tolerates sample-and-hold plateaus; plain accessors always use the original data.
- Pre-existing quirk noticed while testing (out of scope, suggest a separate ticket): the legacy local-zoom snap path stores raw X values into the signal's `ts_start/ts_end` for non-invertible X-versus-Y plots (e.g. `ts=(-0.5, 0.5)`).
- Related display topic for the ticks feature: on large-valued non-date axes the tick labels show offset-relative numbers with no visible reference indication; date axes solve this with the offset-aware formatter.

## Follow-ups (MINT side)

- Expose the `interpolation` field as a table column via the blueprint so it can be set per row from the UI; until then it can be set in the workspace JSON on the signal (it persists like any other adapter field).
- Optional: strictly decreasing X is also invertible; support would be a small extension of `_invert_xy_zoom_to_time`.

## Tests

Unit (`iplotlib/core/tests/test_15_shared_axes_grouping.py`): grouping and follower selection; forced-reprocess flag semantics; dependency-walk robustness (missing/cyclic aliases); ts-window cropping over superset buffers; `resolve_alignment_kind` (raw fast → linear, any slow → previous, any downsampled → previous, explicit wins); end-to-end auto-linear shape; NaN-safe `transform_data`; reverse inversion (original-data primary path incl. plateau'd aligned data and non-monotonic rejection, compound-expression fallback, data-independent rejection).

Both-backend (`iplotlib/standalone/tests/test_backend_behavior.py`, matplotlib + pyqtgraph, on a fixture mirroring the reporting workspace with µs-epoch DI_RELTIME values): forward following with axis-offset stability; undo restoration; deeper zoom over non-refetched raw superset buffers; reverse zoom driving the group incl. window clamping on extreme zoom-out; non-invertible reverse zoom staying local.

Full suites pass with the failure set identical to the base branch (pre-existing pixel-baseline failures only). Validated additionally against live UDA data in MINT (Test34 workspace) through several diagnose/fix iterations.
