# Description: Point-reduction helpers shared by the render backends and the streamer.

import numpy as np


def _minmax_decimate_finite(x, y, target_pairs):
    """Reduce a NaN-free run to at most ``2 * target_pairs`` argmin/argmax
    pairs, preserving extremes at their true coordinates."""
    n = len(x)
    if target_pairs <= 0 or n <= 2 * target_pairs:
        return x, y
    bucket_size = -(-n // target_pairs)  # ceil keeps the output within target
    full = n // bucket_size
    truncated = full * bucket_size
    x_arr = np.asarray(x[:truncated]).reshape(full, bucket_size)
    y_arr = np.asarray(y[:truncated]).reshape(full, bucket_size)
    rows = np.arange(full)
    argmin = np.argmin(y_arr, axis=1)
    argmax = np.argmax(y_arr, axis=1)
    x_min = x_arr[rows, argmin]
    y_min = y_arr[rows, argmin]
    x_max = x_arr[rows, argmax]
    y_max = y_arr[rows, argmax]
    if n > truncated:
        # Remainder becomes one extra bucket so extremes are never trimmed away.
        rx = np.asarray(x[truncated:])
        ry = np.asarray(y[truncated:])
        x_min = np.append(x_min, rx[np.argmin(ry)])
        y_min = np.append(y_min, np.min(ry))
        x_max = np.append(x_max, rx[np.argmax(ry)])
        y_max = np.append(y_max, np.max(ry))
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


def bucket_reduce_envelope(x, y_min, y_max, y_avg, target_points):
    """Reduce envelope buffers to at most ``target_points``: per-bucket min of
    dmin, max of dmax and mean of davg, stamped at the bucket's last timestamp."""
    n = len(x)
    if target_points <= 0 or n <= target_points:
        return x, y_min, y_max, y_avg
    bucket_size = -(-n // target_points)  # ceil keeps the output within target
    full = n // bucket_size
    truncated = full * bucket_size
    out_x = np.asarray(x[:truncated]).reshape(full, bucket_size)[:, -1]
    out_min = np.asarray(y_min[:truncated]).reshape(full, bucket_size).min(axis=1)
    out_max = np.asarray(y_max[:truncated]).reshape(full, bucket_size).max(axis=1)
    out_avg = np.asarray(y_avg[:truncated]).reshape(full, bucket_size).mean(axis=1)
    if n > truncated:
        out_x = np.append(out_x, np.asarray(x)[-1])
        out_min = np.append(out_min, np.min(np.asarray(y_min[truncated:])))
        out_max = np.append(out_max, np.max(np.asarray(y_max[truncated:])))
        out_avg = np.append(out_avg, np.mean(np.asarray(y_avg[truncated:])))
    return out_x, out_min, out_max, out_avg
