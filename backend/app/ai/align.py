"""Re-time ASR words against the audio.

Whisper word timestamps drift badly around long pauses (seconds, not milliseconds), which makes cuts land inside
words. Here every word is assigned, in order, to a voiced region measured from the audio (monotonic dynamic
programming), then words are spread across their region by length. Cuts can then be placed in real silence.
"""
from __future__ import annotations


def voiced_regions(gaps: list[list[float]], duration: float, min_voice: float = 0.06, bridge: float = 0.12) -> list[list[float]]:
    regs, prev = [], 0.0
    for a, b in gaps:
        if a - prev > 0:
            regs.append([prev, a])
        prev = b
    if duration - prev > 0:
        regs.append([prev, duration])
    merged: list[list[float]] = []
    for r in regs:
        if merged and r[0] - merged[-1][1] < bridge:
            merged[-1][1] = r[1]
        else:
            merged.append(list(r))
    return [r for r in merged if r[1] - r[0] >= min_voice]


def align_words(words: list[dict], gaps: list[list[float]], duration: float, skip_cost: float = 1.5) -> list[dict]:
    if not words or not gaps:
        return words
    R = voiced_regions(gaps, duration)
    if not R:
        return words
    n, m = len(words), len(R)
    INF = float("inf")
    centers = [(w["s"] + w["e"]) / 2 for w in words]
    rlen = [b - a for a, b in R]
    pre = [0.0]
    for L in rlen:
        pre.append(pre[-1] + L)

    def dist(i, k):
        a, b = R[k]
        c = centers[i]
        return 0.0 if a <= c <= b else min(abs(c - a), abs(c - b))

    def skipped(k1, k2):  # voiced seconds strictly between regions k1 and k2
        return pre[k2] - pre[k1 + 1] if k2 > k1 + 1 else 0.0

    # dp[k] for current word; back[i][k] = previous region
    dp = [dist(0, k) + 0.3 * skip_cost * pre[k] for k in range(m)]
    back = [[-1] * m]
    for i in range(1, n):
        new, bk = [INF] * m, [-1] * m
        # best over k' <= k of dp[k'] + skip_cost*skipped(k',k); skipped(k',k) = pre[k] - pre[k'+1] for k'<k
        best_val, best_k = INF, -1  # min over k' < k of dp[k'] + skip_cost*(-pre[k'+1])
        for k in range(m):
            stay = dp[k]
            cand, ck = stay, k
            if best_k >= 0:
                v = best_val + skip_cost * pre[k]
                # moving from k' to k where k' = k-1 has no skipped voice; formula handles it (pre[k]-pre[k'+1]=0)
                if v < cand:
                    cand, ck = v, best_k
            # overload: a region can only hold so many words
            new[k] = cand + dist(i, k)
            bk[k] = ck
            val = dp[k] - skip_cost * pre[k + 1]
            if val < best_val:
                best_val, best_k = val, k
        dp = new
        back.append(bk)
    # trailing voiced regions left unused cost a little too
    k = min(range(m), key=lambda k: dp[k] + 0.3 * skip_cost * (pre[m] - pre[k + 1]))
    assign = [0] * n
    for i in range(n - 1, -1, -1):
        assign[i] = k
        k = back[i][k] if i > 0 else k
    # place words inside their region: if the ASR timings already sit in the region keep them (just clamp);
    # otherwise map the ASR span linearly onto the region (keeps relative rhythm), falling back to length weights
    out = [dict(w) for w in words]
    i = 0
    while i < n:
        j = i
        while j + 1 < n and assign[j + 1] == assign[i]:
            j += 1
        a, b = R[assign[i]]
        grp = range(i, j + 1)
        if all(a - 0.15 <= centers[t] <= b + 0.15 for t in grp):
            for t in grp:
                s_, e_ = max(a, words[t]["s"]), min(b, words[t]["e"])
                out[t]["s"], out[t]["e"] = round(s_, 3), round(max(e_, s_ + 0.03), 3)
        else:
            s0, e0 = words[i]["s"], words[j]["e"]
            if e0 - s0 > 0.05 and j > i:
                k = (b - a) / (e0 - s0)
                for t in grp:
                    out[t]["s"] = round(a + (words[t]["s"] - s0) * k, 3)
                    out[t]["e"] = round(min(b, a + (words[t]["e"] - s0) * k), 3)
            else:
                weights = [0.6 + len(words[t]["t"].strip(" .,!?")) for t in grp]
                total, t0 = sum(weights), a
                for t, wgt in zip(grp, weights):
                    t1 = t0 + (b - a) * wgt / total
                    out[t]["s"], out[t]["e"] = round(t0, 3), round(t1, 3)
                    t0 = t1
        i = j + 1
    return out
