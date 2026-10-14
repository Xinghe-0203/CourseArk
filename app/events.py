"""
SSE 事件总线

- 内存环形缓冲保存最近事件，浏览器重连时按 last_event_id 补齐增量
- 每个订阅者一个队列，写满时丢弃最旧事件，绝不阻塞 Worker 事件读取线程
"""

import queue
import threading
import time

RING_CAPACITY = 2000
QUEUE_SIZE = 1000


class EventHub:
    def __init__(self, capacity: int = RING_CAPACITY):
        self._lock = threading.Lock()
        self._ring = []
        self._capacity = capacity
        self._subscribers = set()

    def publish(self, record: dict):
        with self._lock:
            self._ring.append(record)
            if len(self._ring) > self._capacity:
                self._ring = self._ring[-self._capacity:]
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(record)
            except queue.Full:
                try:
                    subscriber.get_nowait()
                    subscriber.put_nowait(record)
                except (queue.Empty, queue.Full):
                    pass

    def subscribe(self) -> queue.Queue:
        subscriber = queue.Queue(maxsize=QUEUE_SIZE)
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue):
        with self._lock:
            self._subscribers.discard(subscriber)

    def replay_since(self, last_event_id: int, limit: int = 500) -> list:
        with self._lock:
            return [item for item in self._ring if int(item.get("id", 0)) > int(last_event_id or 0)][:limit]

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


def make_record(event_id: int, task_id: str, account_id: str, event: str, message: str,
                level: str = "info", stage: str = "", payload: dict = None,
                ts: float = None, narrative: dict = None, context: dict = None) -> dict:
    """
    SSE 事件记录

    narrative 是给前端直接渲染的“人话”版本（做什么、进度多少、成功失败），
    message 保留原始文本用于排查；前端默认只展示 narrative。
    """
    return {
        "id": int(event_id or 0),
        "task_id": task_id or "",
        "account_id": account_id or "",
        "event": event or "log",
        "message": message or "",
        "level": level or "info",
        "stage": stage or "",
        "payload": payload or {},
        "narrative": narrative,
        "context": context or {},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts or time.time())),
        "ts": float(ts or time.time()),
    }
