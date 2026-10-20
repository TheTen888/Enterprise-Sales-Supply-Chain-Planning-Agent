from dataclasses import dataclass


@dataclass(frozen=True)
class BatchPolicy:
    quiet_size: int = 100
    normal_size: int = 500
    burst_size: int = 1000
    burst_backlog: int = 2000
    slow_seconds: float = 0.25

    def __post_init__(self):
        sizes = [self.quiet_size, self.normal_size, self.burst_size, self.burst_backlog]
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in sizes
        ):
            raise ValueError("batch sizes and backlog threshold must be positive integers")
        if not self.quiet_size <= self.normal_size <= self.burst_size <= self.burst_backlog:
            raise ValueError("quiet <= normal <= burst <= backlog threshold required")
        if self.slow_seconds <= 0:
            raise ValueError("slow_seconds must be positive")

    def select(self, backlog: int, previous_seconds: float = 0) -> tuple[int, str]:
        if backlog < 0 or previous_seconds < 0:
            raise ValueError("backlog and duration cannot be negative")
        if backlog <= self.quiet_size:
            size, mode = self.quiet_size, "quiet"
        elif backlog <= self.burst_backlog:
            size, mode = self.normal_size, "normal"
        else:
            size, mode = self.burst_size, "burst"
        if previous_seconds > self.slow_seconds:
            size, mode = max(self.quiet_size, size // 2), f"{mode}-pressure-limited"
        return size, mode
