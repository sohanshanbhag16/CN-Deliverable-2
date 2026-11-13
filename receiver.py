"""Receive one UDP transfer and optionally send loss reports to Ryu."""
import argparse
import socket
import struct
import time
from contextlib import ExitStack

from common import ACK, DATA, FIN, FIN_ACK, HEADER, MAX_COUNT, NACK
from common import PORT, REPORT_SOCKET, START, START_ACK, log, packet


def run(sock, reporter, deadline_seconds):
    peer = session = None
    count = 0
    seen = set()
    originals = set()
    frontier = 0
    gaps = sample = 0
    finish_at = None
    deadline = time.monotonic() + deadline_seconds
    last_data = last_report = time.monotonic()

    while time.monotonic() < (finish_at or deadline):
        try:
            data, address = sock.recvfrom(2048)
            kind, sid, seq, retry = HEADER.unpack_from(data)
        except (socket.timeout, struct.error):
            kind = None

        now = time.monotonic()
        if kind == START and 1 <= seq <= MAX_COUNT:
            if peer is None:
                peer, session, count = address, sid, seq
                last_data = last_report = now
                deadline = now + deadline_seconds
                log("receiver_start", session=session, requested=count)
            if (address, sid, seq) == (peer, session, count):
                sock.sendto(packet(START_ACK, session, count), peer)
        elif kind is not None and (address, sid) == (peer, session):
            if kind == DATA and seq < count:
                last_data = now
                sock.sendto(packet(ACK, session, seq), peer)
                if not retry and seq not in originals:
                    originals.add(seq)
                    sample += 1
                    log("original_received", seq=seq)
                if seq not in seen:
                    seen.add(seq)
                    log("delivered", seq=seq, retry=retry)
                    if seq >= frontier:
                        # Sender has at most one 10-packet batch outstanding.
                        for missing in range(frontier, seq):
                            gaps += 1
                            sock.sendto(packet(NACK, session, missing), peer)
                            log("gap", seq=missing)
                        frontier = seq + 1
            elif kind == FIN and seq == count and len(seen) == count:
                sock.sendto(packet(FIN_ACK, session, count), peer)
                if finish_at is None:
                    finish_at = now + 1.0

        if peer and len(seen) < count and now - last_report >= 0.5:
            stalled = now - last_data >= 0.5
            loss = 100.0 if stalled else 100 * gaps / max(1, gaps + sample)
            log("path_sample", estimated_loss=loss, stalled=stalled)
            if reporter is not None:
                try:
                    reporter.sendto(str(loss).encode(), REPORT_SOCKET)
                except OSError as error:
                    log("report_error", message=str(error))
            gaps = sample = 0
            last_report = now

    log("receiver_summary", requested=count, delivered=len(seen),
        original_received=len(originals), complete=finish_at is not None)
    return 0 if finish_at is not None else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--deadline", type=float, default=60)
    args = parser.parse_args()
    with ExitStack() as stack:
        sock = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
        sock.bind(("127.0.0.1" if args.local else "0.0.0.0", args.port))
        sock.settimeout(0.1)
        reporter = None
        if not args.local:
            reporter = stack.enter_context(socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM))
        log("listening", port=args.port)
        return run(sock, reporter, args.deadline)


if __name__ == "__main__":
    raise SystemExit(main())
