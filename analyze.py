"""Summarize one run from the four JSONL logs."""
import argparse
import json


def events(path):
    with open(path, encoding="utf-8-sig") as file:
        return [json.loads(line) for line in file if line.startswith("{")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("sender")
    parser.add_argument("receiver")
    parser.add_argument("controller")
    parser.add_argument("fault")
    args = parser.parse_args()
    tx, rx, controller, faults = (
        events(path) for path in (args.sender, args.receiver, args.controller, args.fault)
    )
    fault = next((e["t"] for e in faults if e["event"] == "fault"), None)
    switch = next((e["t"] for e in controller
                   if e["event"] == "reroute" and fault is not None and e["t"] >= fault), None)
    summary = next(e for e in tx if e["event"] == "sender_summary")
    original_rx = {e["seq"] for e in rx if e["event"] == "original_received"}
    original_tx = [e for e in tx if e["event"] == "original"]
    groups = {"clean": [], "pre_fault": [], "impaired": [], "post_reroute": []}
    for event in original_tx:
        t = event["t"]
        if fault is None:
            phase = "clean"
        elif t < fault:
            phase = "pre_fault"
        elif switch is None or t < switch:
            phase = "impaired"
        else:
            phase = "post_reroute"
        groups[phase].append(event["seq"])
    for phase, sent in groups.items():
        missing = sum(seq not in original_rx for seq in sent)
        loss = f"{100 * missing / len(sent):.2f}%" if sent else "N/A"
        print(f"{phase}: sent={len(sent)} missing={missing} loss={loss}")
    delivered = len({e["seq"] for e in rx if e["event"] == "delivered"
                     and e["t"] <= summary["t"]})
    print(f"Delivery: {delivered}/{summary['requested']}")
    print("Retransmissions:", sum(e["event"] == "retransmit" for e in tx))
    print("Transfer complete:", summary["complete"])
    if fault is not None:
        resume = next((e["t"] for e in tx if e["event"] == "ack"
                       and e["t"] >= (switch if switch is not None else fault)), None)
        print("Fault to reroute command:", "N/A" if switch is None else f"{switch - fault:.3f} s")
        print("Fault to ACK progress:", "no progress" if resume is None else f"{resume - fault:.3f} s")


if __name__ == "__main__":
    main()
