"""Wire format and timestamped experiment logs."""
import json
import struct
import time

START, START_ACK, DATA, ACK, NACK, FIN, FIN_ACK = range(1, 8)
HEADER = struct.Struct("!BQI?")
PORT = 5000
REPORT_SOCKET = "/tmp/ryu_loss.sock"
MAX_COUNT = 1_000_000


def packet(kind, session, number, retry=False, payload=b""):
    return HEADER.pack(kind, session, number, retry) + payload


def log(event, **fields):
    print(json.dumps(dict(event=event, t=time.monotonic(), **fields)), flush=True)
