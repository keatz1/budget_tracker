"""How a category or group has used its budget this month, rollover included.

Shared by the month page and the by-group page so both read the same way."""

from dataclasses import dataclass


@dataclass
class Tracker:
    """How a category (or a whole group) has used its budget this month.

    deficit  = overspend carried in from last month (0 if carry is positive)
    surplus  = money carried in from last month (0 if carry is negative)
    track    = the bar's full length: budget + surplus
    used     = deficit + spent, which is what counts against the track
    """

    budget: int
    carry: int
    spent: int
    # For a group: the carries of its categories summed separately, so a +120 and a
    # -120 don't disappear into a net of zero.
    carried_in: int | None = None
    overspend_in: int | None = None

    @property
    def deficit(self) -> int:
        return -self.carry if self.carry < 0 else 0

    @property
    def surplus(self) -> int:
        return self.carry if self.carry > 0 else 0

    @property
    def gross_surplus(self) -> int:
        return self.carried_in if self.carried_in is not None else self.surplus

    @property
    def gross_deficit(self) -> int:
        return self.overspend_in if self.overspend_in is not None else self.deficit

    @property
    def track(self) -> int:
        return self.budget + self.surplus

    @property
    def used(self) -> int:
        return self.deficit + self.spent

    @property
    def left(self) -> int:
        return self.track - self.used

    @property
    def over(self) -> bool:
        return self.used > self.track

    def pct(self, part: int) -> float:
        base = max(self.track, self.used, 1)
        return min(100.0, part / base * 100)

    @property
    def budget_mark(self) -> float | None:
        """Where this month's budget sits on the track, when a surplus extends it."""
        if self.surplus and self.track:
            return self.budget / max(self.track, self.used) * 100
        return None


def group_total(trackers: list[Tracker]) -> Tracker:
    return Tracker(
        budget=sum(t.budget for t in trackers),
        carry=sum(t.carry for t in trackers),
        spent=sum(t.spent for t in trackers),
        carried_in=sum(t.gross_surplus for t in trackers),
        overspend_in=sum(t.gross_deficit for t in trackers),
    )
