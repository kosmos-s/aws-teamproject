"""Chat flood protection shared by text and file messages (single-worker, in memory).

- burst: at most 8 messages per 5 s
- sustained: at most 40 messages per 60 s
- duplicates: the same text a 3rd time within 30 s is refused
A refused message returns 429 with Retry-After so the browser can show a countdown.
"""
import time
import threading

from fastapi import HTTPException

BURST, BURST_WINDOW = 8, 5
SUSTAINED, SUSTAINED_WINDOW = 40, 60
DUPLICATES, DUPLICATE_WINDOW = 2, 30


class AntiSpam:
    def __init__(self):
        self.lock = threading.Lock()
        self.sent = {}   # user_id -> [timestamps]
        self.texts = {}  # user_id -> [(timestamp, normalized text)]

    @staticmethod
    def normalize(text):
        return " ".join((text or "").split()).lower()

    def check(self, user_id, text):
        with self.lock: return self._check(user_id,text)

    def _check(self, user_id, text):
        now = time.time()
        sent = [t for t in self.sent.get(user_id, []) if now - t < SUSTAINED_WINDOW]
        burst = [t for t in sent if now - t < BURST_WINDOW]
        if len(burst) >= BURST:
            wait = int(BURST_WINDOW - (now - burst[0])) + 1
            raise HTTPException(429, "Too many messages", headers={"Retry-After": str(wait)})
        if len(sent) >= SUSTAINED:
            wait = int(SUSTAINED_WINDOW - (now - sent[0])) + 1
            raise HTTPException(429, "Too many messages", headers={"Retry-After": str(wait)})
        norm = self.normalize(text)
        texts = [(t, x) for t, x in self.texts.get(user_id, []) if now - t < DUPLICATE_WINDOW]
        if norm:
            same = [t for t, x in texts if x == norm]
            if len(same) >= DUPLICATES:
                wait = int(DUPLICATE_WINDOW - (now - same[0])) + 1
                raise HTTPException(429, "Duplicate message", headers={"Retry-After": str(wait)})
            texts.append((now, norm))
        self.sent[user_id] = sent + [now]
        self.texts[user_id] = texts[-50:]
