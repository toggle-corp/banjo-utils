import time


class RetryHelper:
    def __init__(self, base_wait_seconds: int = 2, wait_max_seconds: int = 60):
        self.base_wait_seconds = base_wait_seconds
        self.wait_max_seconds = wait_max_seconds
        self.attempt = 1
        self.next_wait = base_wait_seconds
        self.start_time = time.time()

    def next_wait_seconds(self) -> int:
        return self.next_wait

    def wait(self) -> None:
        time.sleep(self.next_wait)
        self.attempt += 1
        if self.next_wait < self.wait_max_seconds:
            self.next_wait = self.base_wait_seconds**self.attempt
        else:
            self.next_wait = self.wait_max_seconds

    def total_time(self) -> float:
        return time.time() - self.start_time

    def try_again_message(self, prefix: str) -> str:
        return f"{prefix}, Attempt: {self.attempt}, try again after {self.next_wait_seconds()} seconds..."
