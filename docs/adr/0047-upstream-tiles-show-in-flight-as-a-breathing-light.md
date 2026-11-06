# Upstream tiles show requests in flight as a breathing light

Status: accepted.

Amends ADR 0043 and ADR 0046. Each upstream status tile shows a small light at the right of its label. While the key has requests in flight, the light is green and breathes, with the count beside it (`2/3`, or `2` for a key without a concurrency cap). The breath is a 4s cycle with a quick rise and a slow fall, and its halo grows with how full the key is. The tempo stays the same at any load. At its concurrency cap the light turns amber and holds still. An idle key shows a quiet hollow light and no count. The light is announced as 工作中 2/3, 滿載 3/3, or 閒置. With reduced motion the light does not breathe.

The `併發 n/cap` text is gone from the tile's sub line. The count beside the light replaces it.

The board is redrawn on every 5s poll. Each redraw starts the lights partway through their breath, at the page clock's phase. That keeps every light breathing in step and stops the breath from restarting on each poll.

Chosen from prototype variants on the `prototype/upstream-breathing` branch: variant A (`/portal?variant=A`).

## Considered Options

- **The whole tile's border breathes (variant B).** Rejected. On the light theme it is too faint to notice.
- **One segment per concurrency slot, lit and breathing in a wave (variant C).** Rejected. It reads like a second meter right next to the usage meter.
- **Breathe faster as load rises.** Rejected. A faster pulse reads as an alarm, not as work in progress.

## Consequences

The light only knows what the last poll saw, so a request that starts and ends between two polls never lights it.
