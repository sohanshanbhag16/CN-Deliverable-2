# Packet Loss Detection and Recovery · Deliverable 2

The sender sends UDP DATA in paced batches of up to ten. The receiver ACKs every
valid DATA, counts each sequence once, and NACKs gaps. The sender retries
unacknowledged DATA on timeout, including loss at the tail of a batch.
START/START_ACK establishes the expected sequence range. FIN/FIN_ACK confirms
completion. Both endpoints have deadlines. One sender and one receiver run per trial.

## Files

- common.py defines the UDP wire format and timestamped JSONL logs.
- sender.py and receiver.py implement the UDP application.
- topo.py builds the Mininet diamond with OpenFlow 1.3 and static ARP.
- controller.py programs both forwarding directions and responds to path events.
- analyze.py computes metrics from a single trial.
- .gitignore excludes generated logs and caches.

The paths are h1–s1–s2–s4–h2 (primary) and h1–s1–s3–s4–h2 (alternate).
The receiver sends loss estimates to Ryu using a Unix datagram socket. Two
consecutive samples at or above 15% can trigger a reroute, with a five-second
hold-down. A known link failure can trigger immediate failover to an available
path. Ryu changes the s1 forward rule and s4 reverse rule. A reroute timestamp
records submission of the flow changes. The next ACK measures actual progress.

## Windows smoke test in VS Code

Open two PowerShell terminals in this folder. Run `py receiver.py --local`
in the first, then `py sender.py --dst 127.0.0.1 --count 23` in the second.
Expect 23 unique deliveries, 23 ACKs, and both summaries marked complete.
Restart the receiver for each transfer. This mode uses Python's standard library.

## Full Linux experiment

Use a Linux machine with working Mininet, Open vSwitch, and Ryu installed.
Run all commands from this project directory. Record the actual OS and versions
of Python, Mininet, OVS and Ryu in your submission.

1. Start Open vSwitch. Start the controller in one terminal with
   `CN_MODE=dynamic ryu-manager --ofp-tcp-listen-port 6653 controller.py > controller.log 2>&1`.
   Use `CN_MODE=static` to pin the primary path for the baseline.
2. Start Mininet in another terminal with `sudo python3 topo.py`.
   Check `links` and `h1 ping -c 1 10.0.0.2` before the transfer.
3. At the Mininet prompt, start each endpoint:
   ~~~text
   h2 python3 receiver.py --deadline 55 > receiver.log 2>&1 &
   h1 python3 sender.py --count 2000 --rate 100 --deadline 45 > sender.log 2>&1 &
   ~~~
4. After roughly five seconds, while DATA is flowing, run one fault command.
   The marker records fault-command initiation on the same monotonic clock
   as the application logs. For consistent comparisons use the same delay.
   ~~~text
   sh python3 -c "from common import log; log('fault')" > fault.log && tc qdisc replace dev s2-eth2 root netem loss 40%
   ~~~
   For the separate hard-failure trial:
   ~~~text
   sh python3 -c "from common import log; log('fault')" > fault.log && ip link set dev s2-eth2 down
   ~~~
   For clean runs, create an empty file with `sh touch fault.log` in a fresh trial.
5. Capture both forwarding directions before and after the fault:
   ~~~text
   sh ovs-ofctl -O OpenFlow13 dump-flows s1
   sh ovs-ofctl -O OpenFlow13 dump-flows s4
   ~~~
   The edge outputs should change from s1 port 2 / s4 port 1 to s1 port 3 /
   s4 port 2 on dynamic failover. Confirm packets resume in the sender log.
6. After both endpoints exit, run
   `python3 analyze.py sender.log receiver.log controller.log fault.log`.
   Save all logs and flow dumps under a separate directory for each trial.
7. Undo the fault with `sh tc qdisc del dev s2-eth2 root` or
   `sh ip link set dev s2-eth2 up`, as applicable. Exit Mininet and stop Ryu.
   If an interrupted controller leaves its socket behind, remove
   `/tmp/ryu_loss.sock` after confirming the controller has stopped.
   Restart both Mininet and Ryu before each trial to restore primary routing.

Run a clean trial and three trials each for 40% loss and hard failure, in both
static and dynamic modes. Keep sender parameters identical. Compare first-attempt
loss before, during, and after the fault, final unique delivery, retransmission
count, and time to ACK progress. Loss is grouped by original-send timestamp.
A phase with no original sends is N/A. If both paths fail, the deadline bounds
the transfer. A static run with random loss can still make ACK progress, so
compare its loss and retransmission counts alongside the progress time.

| Mode | Fault | Trial | Loss before | Loss during | Loss after reroute | Delivery | Retransmissions | Time to ACK progress |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Fill from your runs | | | | | | | | |

For the demo, show a missing sequence, the Ryu route change, both edge switch
outputs, and resumed ACKs. Keep the static hard-failure log for comparison.
