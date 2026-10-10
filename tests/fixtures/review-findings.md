# Cache service review — two findings

## Preamble

This section describes the document. What follows below is a write-up of two findings from the third round of review. Both were surfaced by one reviewer and then confirmed independently by a second, and one of them was also flagged in the earlier v7 pass, so we are reasonably confident in them. Note for the reader: findings are numbered continuing from P298.

### P299. The eviction job empties a shard and the health check passes the keys it deleted — R35

**What happens.** I think what is going on here is that whoever wrote the eviction job did not consider the shard-level case, which is a fairly obvious mistake. Run 1 evicted the 244-entry shard
`sessions-eu-2`, and four pinned keys
with it: the feature-flag snapshot, the rate-limit table,
the tenant routing map, and the signing-key cache. Also gone: "Pinned keys are never
evicted", and the pointer "Two of them are reloaded at startup, and they are the
last two entries below".

The reason the health check passed all four is that each is also stored in a replica shard
300 to 700 entries later, and the check reads the whole cluster. This is not the whole story, but it is the main part of it.

**Expected fix.** As R35 says: the making of the check shard-aware is what is needed here. A key whose only
surviving copy sits in a different shard is reported, not passed, and it
gets its own heading in the output separate from `gone` — the same split R32
introduces for `stale`.

See P307 for the second half of R35, which is aimed at the wrong component.

### P300. `--profile strict` fails a correct run three times harder — R37

**What happens.** One caveat before we get to the numbers: these were run on the local main checkout at `9478b58`. Same two files, same build, one flag apart:

```bash
$ cachectl verify before.db after.db
KEYS LOST — 6 entries …          content dropped — 4 entries …

$ cachectl verify before.db after.db --profile strict
KEYS LOST — 18 entries …         content dropped — 31 entries …
```

The data is identical. `strict.json` sets `"match_ratio": 0.9` and that
threshold does all of it. Somebody clearly picked 0.9 without testing it. This lands on the wrong user: `strict` is the profile a production cluster is meant to use, and reaching for it makes the run evict
less (−347 against −433) and fail three times harder.

**Expected fix.** What should probably happen, going forward, is the running of the 129-cluster corpus at 0.9 and the keeping of the highest value at which a known-good run still passes. We should also add one line to the profile table in
`README.md` saying `match_ratio` raises how much of an entry must survive before
it counts as kept, and that raising it makes the report stricter, not the data
safer.

## Closing verdict

To close out, both findings above come down to the same thing: a check that reads the whole cluster cannot tell you where a key went. This was cross-checked with two reviewers before being written up.
