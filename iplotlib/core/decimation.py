# Description: Point-reduction helpers shared by the render backends and the streamer.

import numpy as np


def _even_bucket_ids(n, buckets):
    """Bucket id per sample, sizes differing by at most one and the larger
    buckets spread evenly across the run. Front-loading the larger buckets
    would concentrate every re-decimation's losses on the oldest samples and
    visibly erode the left edge of a capped streaming buffer."""
    return (np.arange(n, dtype=np.intp) * buckets) // n


def _minmax_decimate_finite(x, y, target_pairs):
    """Reduce a NaN-free run to one argmin/argmax pair per bucket with the
    run's endpoints pinned, preserving extremes at their true coordinates.
    Pinning the endpoints keeps repeated re-decimation of a capped stream from
    eroding its edges one sample at a time."""
    n = len(x)
    if target_pairs <= 0 or n <= 2 * target_pairs:
        return x, y
    x = np.asarray(x)
    y = np.asarray(y)
    bucket = _even_bucket_ids(n, target_pairs)
    order = np.lexsort((y, bucket))
    bounds = np.searchsorted(bucket[order],
                             np.arange(target_pairs + 1, dtype=np.intp))
    argmin = order[bounds[:-1]]
    argmax = order[bounds[1:] - 1]
    idx = np.empty(2 * target_pairs, dtype=np.intp)
    idx[0::2] = np.minimum(argmin, argmax)
    idx[1::2] = np.maximum(argmin, argmax)
    if idx[0] != 0:
        idx = np.concatenate((np.zeros(1, dtype=np.intp), idx))
    if idx[-1] != n - 1:
        idx = np.append(idx, n - 1)
    return x[idx], y[idx]


def minmax_decimate(x, y, target_pairs):
    """Reduce to about ``2 * target_pairs`` points (plus pinned run endpoints):
    one argmin/argmax pair per bucket, preserving extremes at their true
    coordinates. NaN samples mark line breaks (e.g. the archive/live seam):
    each finite run is reduced on its own with a share of the budget and the
    gaps are kept, so a break is never bridged nor allowed to poison a bucket's
    argmin/argmax."""
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
    """Reduce envelope buffers to ``target_points``: per-bucket min of dmin,
    max of dmax and mean of davg, stamped at the bucket's last timestamp. The
    first bucket keeps its first timestamp instead, so repeated re-decimation
    of a capped stream cannot creep the left edge to the right."""
    n = len(x)
    if target_points <= 0 or n <= target_points:
        return x, y_min, y_max, y_avg
    x = np.asarray(x)
    y_min = np.asarray(y_min)
    y_max = np.asarray(y_max)
    y_avg = np.asarray(y_avg)
    bucket = _even_bucket_ids(n, target_points)
    starts = np.searchsorted(bucket, np.arange(target_points, dtype=np.intp))
    counts = np.diff(np.append(starts, n))
    out_x = x[np.append(starts[1:], n) - 1]
    out_x[0] = x[0]
    out_min = np.minimum.reduceat(y_min, starts)
    out_max = np.maximum.reduceat(y_max, starts)
    out_avg = np.add.reduceat(y_avg, starts) / counts
    return out_x, out_min, out_max, out_avg
