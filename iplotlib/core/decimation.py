# Description: Point-reduction helpers shared by the render backends and the streamer.

import numpy as np


def _bucket_edges(n, buckets):
    """Split ``n`` samples into exactly ``buckets`` contiguous buckets: the
    first ``n % buckets`` take one extra sample, so no sample is left over. A
    ceil-sized reshape instead would yield far fewer buckets when ``n/buckets``
    sits just above an integer (e.g. 2.02 -> 3-sized buckets -> 2/3 of the
    requested output), silently shrinking capped streaming buffers."""
    size = n // buckets
    rem = n % buckets
    return size, rem, (size + 1) * rem


def _minmax_reduce_block(x, y, bucket):
    rows = len(x) // bucket
    x_arr = x.reshape(rows, bucket)
    y_arr = y.reshape(rows, bucket)
    r = np.arange(rows)
    argmin = np.argmin(y_arr, axis=1)
    argmax = np.argmax(y_arr, axis=1)
    return (x_arr[r, argmin], y_arr[r, argmin],
            x_arr[r, argmax], y_arr[r, argmax])


def _minmax_decimate_finite(x, y, target_pairs):
    """Reduce a NaN-free run to ``2 * target_pairs`` argmin/argmax pairs,
    preserving extremes at their true coordinates."""
    n = len(x)
    if target_pairs <= 0 or n <= 2 * target_pairs:
        return x, y
    x = np.asarray(x)
    y = np.asarray(y)
    size, rem, split = _bucket_edges(n, target_pairs)
    blocks = []
    if rem:
        blocks.append(_minmax_reduce_block(x[:split], y[:split], size + 1))
    if n > split:
        blocks.append(_minmax_reduce_block(x[split:], y[split:], size))
    x_min = np.concatenate([b[0] for b in blocks])
    y_min = np.concatenate([b[1] for b in blocks])
    x_max = np.concatenate([b[2] for b in blocks])
    y_max = np.concatenate([b[3] for b in blocks])
    pairs = len(x_min)
    min_first = x_min <= x_max
    out_x = np.empty(2 * pairs, dtype=x_min.dtype)
    out_y = np.empty(2 * pairs, dtype=y_min.dtype)
    out_x[0::2] = np.where(min_first, x_min, x_max)
    out_y[0::2] = np.where(min_first, y_min, y_max)
    out_x[1::2] = np.where(min_first, x_max, x_min)
    out_y[1::2] = np.where(min_first, y_max, y_min)
    return out_x, out_y


def minmax_decimate(x, y, target_pairs):
    """Reduce to at most ``2 * target_pairs`` points: one argmin/argmax pair
    per bucket, preserving extremes at their true coordinates. NaN samples mark
    line breaks (e.g. the archive/live seam): each finite run is reduced on its
    own with a share of the budget and the gaps are kept, so a break is never
    bridged nor allowed to poison a bucket's argmin/argmax."""
    n = len(x)
    if target_pairs <= 0 or n <= 2 * target_pairs:
        return x, y
    x = np.asarray(x)
    y = np.asarray(y)
    finite = np.isfinite(y)
    if finite.all():
        return _minmax_decimate_finite(x, y, target_pairs)

    edges = np.diff(finite.astype(np.int8))
    starts = np.where(edges == 1)[0] + 1
    ends = np.where(edges == -1)[0] + 1
    if finite[0]:
        starts = np.append(0, starts)
    if finite[-1]:
        ends = np.append(ends, n)
    runs = list(zip(starts, ends))
    total = sum(e - s for s, e in runs)
    if total == 0:
        return x, y

    out_x, out_y = [], []
    for k, (s, e) in enumerate(runs):
        if k > 0:
            # One NaN between runs keeps the break; its timestamp is the last
            # gap sample so the gap stays where it is in time.
            out_x.append(x[s - 1:s])
            out_y.append(np.asarray([np.nan], dtype=y.dtype))
        share = max(1, int(round(target_pairs * (e - s) / total)))
        rx, ry = _minmax_decimate_finite(x[s:e], y[s:e], share)
        out_x.append(np.asarray(rx))
        out_y.append(np.asarray(ry))
    return np.concatenate(out_x), np.concatenate(out_y)


def _envelope_reduce_block(x, y_min, y_max, y_avg, bucket):
    rows = len(x) // bucket
    return (x.reshape(rows, bucket)[:, -1],
            y_min.reshape(rows, bucket).min(axis=1),
            y_max.reshape(rows, bucket).max(axis=1),
            y_avg.reshape(rows, bucket).mean(axis=1))


def bucket_reduce_envelope(x, y_min, y_max, y_avg, target_points):
    """Reduce envelope buffers to ``target_points``: per-bucket min of dmin,
    max of dmax and mean of davg, stamped at the bucket's last timestamp."""
    n = len(x)
    if target_points <= 0 or n <= target_points:
        return x, y_min, y_max, y_avg
    x = np.asarray(x)
    y_min = np.asarray(y_min)
    y_max = np.asarray(y_max)
    y_avg = np.asarray(y_avg)
    size, rem, split = _bucket_edges(n, target_points)
    blocks = []
    if rem:
        blocks.append(_envelope_reduce_block(
            x[:split], y_min[:split], y_max[:split], y_avg[:split], size + 1))
    if n > split:
        blocks.append(_envelope_reduce_block(
            x[split:], y_min[split:], y_max[split:], y_avg[split:], size))
    return tuple(np.concatenate([b[i] for b in blocks]) for i in range(4))
