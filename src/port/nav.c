/* nav.c - spatial navigation between targets on the screen (see nav.h). Pure. */
#include <stdlib.h>

#include "nav.h"

/* centres in doubled pixels (a box 128 wide has its centre between two pixels), so that no division rounds */
static int cx2(const NavTarget *t) { return t->x0 + t->x1 - 1; }
static int cy2(const NavTarget *t) { return t->y0 + t->y1 - 1; }

void nav_point(const NavTarget *t, int *x, int *y)
{
    *x = (t->x0 + t->x1 - 1) / 2;
    *y = (t->y0 + t->y1 - 1) / 2;
}

int nav_find(const NavTarget *t, int n, int x, int y)
{
    int i, best = -1;
    long best_d = 0;

    for (i = 0; i < n; i++) {
        long dx, dy, d;

        if (x < t[i].x0 || x >= t[i].x1 || y < t[i].y0 || y >= t[i].y1)
            continue;
        dx = 2L * x - cx2(&t[i]);
        dy = 2L * y - cy2(&t[i]);
        d = dx * dx + dy * dy;
        if (best < 0 || d < best_d) {
            best = i;
            best_d = d;
        }
    }
    return best;
}

/* the distance of a centre (doubled) from the source along the direction (positive: beyond), and its sideways offset */
static void measure(int dir, int sx2, int sy2, int tx2, int ty2, int *along, int *side)
{
    switch (dir) {
    case NAV_UP:    *along = sy2 - ty2; *side = abs(tx2 - sx2); break;
    case NAV_DOWN:  *along = ty2 - sy2; *side = abs(tx2 - sx2); break;
    case NAV_LEFT:  *along = sx2 - tx2; *side = abs(ty2 - sy2); break;
    default:        *along = tx2 - sx2; *side = abs(ty2 - sy2); break;
    }
}

/* the boxes overlap sideways (for up and down: in x; for left and right: in y): they are in one beam, whatever their centres */
static int aligned(int dir, int slo, int shi, const NavTarget *t)
{
    int lo = (dir == NAV_UP || dir == NAV_DOWN) ? t->x0 : t->y0, hi = (dir == NAV_UP || dir == NAV_DOWN) ? t->x1 : t->y1;

    return lo < shi && slo < hi;
}

int nav_pick(const NavTarget *t, int n, int cur, int x, int y, int dir, int *hx, int *hy)
{
    int i, sx2, sy2, slo, shi, best = -1, best_tier = 99, best_score = 0, best_side = 0, have, zone = 0;
    int vertical = dir == NAV_UP || dir == NAV_DOWN;

    if (n <= 0)
        return NAV_NONE;
    if (cur < 0 || cur >= n)
        cur = nav_find(t, n, x, y);
    have = cur >= 0;
    if (have) {
        sx2 = cx2(&t[cur]);
        sy2 = cy2(&t[cur]);
        slo = vertical ? t[cur].x0 : t[cur].y0;
        shi = vertical ? t[cur].x1 : t[cur].y1;
        zone = t[cur].zone;
    } else {
        sx2 = 2 * x;
        sy2 = 2 * y;
        slo = vertical ? x : y;
        shi = slo + 1;
    }
    for (i = 0; i < n; i++) {
        int along, side, tier, score, al;

        if (i == cur)
            continue;
        measure(dir, sx2, sy2, cx2(&t[i]), cy2(&t[i]), &along, &side);
        if (along <= 0)
            continue;
        al = aligned(dir, slo, shi, &t[i]);
        if (side > along && !al)                                    /* off to the side by more than 45 degrees and not in the beam: not a neighbour in this direction */
            continue;
        tier = (al ? 0 : 2) + (have && t[i].zone == zone ? 0 : 1);
        score = along + 2 * side;
        if (tier < best_tier || (tier == best_tier && (score < best_score || (score == best_score && side < best_side)))) {
            best = i;
            best_tier = tier;
            best_score = score;
            best_side = side;
        }
    }
    if (have && (best < 0 || (best_tier & 1)) && (t[cur].scroll & (1 << dir)))      /* a list with more rows that way: it scrolls before the pointer leaves it */
        return NAV_SCROLL;
    if (best < 0) {
        if (have)
            return NAV_NONE;
        for (i = 0; i < n; i++) {                                     /* the pointer is on no target and none lies that way: the nearest, so it can get back */
            int dx = cx2(&t[i]) - sx2, dy = cy2(&t[i]) - sy2, d = abs(dx) + abs(dy);

            if (best < 0 || d < best_score) {
                best = i;
                best_score = d;
            }
        }
    }
    if (best < 0)
        return NAV_NONE;
    nav_point(&t[best], hx, hy);
    return best;
}
