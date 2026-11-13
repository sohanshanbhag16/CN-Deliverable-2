"""Send paced UDP batches with selective retransmission."""
import argparse
import secrets
import socket
import struct
import time

from common import ACK, DATA, FIN, FIN_ACK, HEADER, MAX_COUNT, NACK
from common import PORT, START, START_ACK, log, packet


def receive(sock):
    try:
        return HEADER.unpack_from(sock.recv(2048))
    except (socket.timeout, OSError, struct.error):
        return None


def exchange(sock, session, kind, expected, count, deadline):
    while time.monotonic() < deadline:
        sock.send(packet(kind, session, count))
        until = min(deadline, time.monotonic() + 0.25)
        while time.monotonic() < until:
            reply = receive(sock)
            if reply and reply[:3] == (expected, session, count):
                return True
    return False


def transfer(sock, args):
    session = secrets.randbits(64)
    deadline = time.monotonic() + args.deadline
    if not exchange(sock, session, START, START_ACK, args.count, deadline):
        log("start_timeout", session=session)
        return 1

    acknowledged = 0
    payload = b"x" * 500
    next_send = time.monotonic()
    for start in range(0, args.count, 10):
        end = min(start + 10, args.count)
        pending = {}
        sequence = start
        while (sequence < end or pending) and time.monotonic() < deadline:
            now = time.monotonic()
            if sequence < end and now >= next_send:
                sock.send(packet(DATA, session, sequence, payload=payload))
                log("original", seq=sequence)
                pending[sequence] = now + 0.25
                next_send = now + 1 / args.rate
                sequence += 1

            for seq, due in pending.items():
                if now >= due:
                    sock.send(packet(DATA, session, seq, True, payload))
                    log("retransmit", seq=seq)
                    pending[seq] = now + 0.25

            reply = receive(sock)
            if reply:
                kind, received_session, seq, _ = reply
                if received_session == session and seq in pending:
                    if kind == ACK:
                        del pending[seq]
                        acknowledged += 1
                        log("ack", seq=seq)
                    elif kind == NACK:
                        pending[seq] = min(pending[seq], now + 0.02)
        if pending or sequence < end:
            break

    finished = False
    if acknowledged == args.count:
        finished = exchange(sock, session, FIN, FIN_ACK, args.count, deadline)
    log("sender_summary", requested=args.count, acknowledged=acknowledged,
        complete=finished)
    return 0 if finished else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dst", default="10.0.0.2")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--count", type=int, default=2000)
    parser.add_argument("--rate", type=float, default=100)
    parser.add_argument("--deadline", type=float, default=45)
    args = parser.parse_args()
    if not (1 <= args.count <= MAX_COUNT and args.rate > 0 and args.deadline > 0):
        parser.error("use a positive rate and deadline and a count from 1 to 1000000")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((args.dst, args.port))
        sock.settimeout(0.005)
        return transfer(sock, args)


if __name__ == "__main__":
    raise SystemExit(main())
