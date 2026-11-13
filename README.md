# Packet Loss Detection and Recovery

**Computer Networks Mini Project · Deliverable 2**

This project implements reliable data delivery over UDP and uses a Ryu SDN controller to reroute traffic when the active network path degrades or fails. The experiment compares **static routing**, which stays on the primary path, with **dynamic routing**, which can move traffic to the alternate path. UDP acknowledgements and retransmissions are enabled in both modes.

## How the system works

1. The sender and receiver establish a transfer and agree on the expected packet count.
2. The sender transmits numbered UDP packets in batches of up to ten. The receiver acknowledges each valid packet and counts each sequence number once.
3. The receiver sends a negative acknowledgement when it detects a gap. The sender also retransmits packets whose acknowledgements time out. The transfer has a deadline so an unrecoverable failure produces a measurable result.
4. The receiver sends periodic loss estimates to Ryu. In dynamic mode, sustained loss or a link failure can trigger a route change.
5. Ryu updates the forwarding rules for both directions so DATA and ACK packets can use the alternate path.

| Route | Switch sequence |
| --- | --- |
| Primary | `h1 → s1 → s2 → s4 → h2` |
| Alternate | `h1 → s1 → s3 → s4 → h2` |

The sender runs on `h1` (`10.0.0.1`) and the receiver runs on `h2` (`10.0.0.2`). Mininet connects the switches to the controller at `127.0.0.1:6653`.

## Project files

| File | Purpose |
| --- | --- |
| `common.py` | UDP packet format and timestamped logging |
| `sender.py` | Paced transmission, ACK handling, and retransmission |
| `receiver.py` | Sequence tracking, ACK/NACK responses, and loss reporting |
| `controller.py` | OpenFlow rules, static baseline, and dynamic failover |
| `topo.py` | Two-path Mininet topology |
| `analyze.py` | Calculates loss, delivery, retransmissions, and recovery timing from trial logs |

## 1. Get the project

On the machine used for the demo, clone this repository and open its folder. Use the clone URL from the green **Code** button on GitHub.

```bash
git clone <repository-clone-url>
cd CN_Deliverable_2
```

If you downloaded the ZIP, extract it and open a terminal in the folder that contains `topo.py`.

### Optional Windows check

The sender and receiver can be tested on Windows with Python 3. Open two PowerShell terminals in the project folder and run:

**Terminal 1**

```powershell
py receiver.py --local
```

**Terminal 2**

```powershell
py sender.py --dst 127.0.0.1 --count 23
```

Look for **23 acknowledged** in the sender summary and **23 delivered** in the receiver summary. Both summaries should show `"complete": true`. Restart the receiver before each test. The `--local` flag disables Ryu reporting for this check.

## 2. Start the full Mininet environment

Use a Linux machine with Python 3, Mininet, Open vSwitch, and Ryu installed. Open two terminals in the project folder.

**Terminal 1 · Start the controller**

```bash
CN_MODE=dynamic ryu-manager --ofp-tcp-listen-port 6653 controller.py > controller.log 2>&1
```

Leave this terminal running. Its output goes to `controller.log`.

**Terminal 2 · Start Open vSwitch and Mininet**

```bash
sudo service openvswitch-switch start
sudo python3 topo.py
```

At the `mininet>` prompt, run:

```text
links
h1 ping -c 1 10.0.0.2
```

Continue once the ping succeeds. If it fails, check `controller.log` and confirm that the controller is running on port `6653`.

## 3. Run a clean trial

At the `mininet>` prompt:

```text
sh rm -f fault.log
sh touch fault.log
h2 python3 receiver.py --deadline 55 > receiver.log 2>&1 &
h1 python3 sender.py --count 2000 --rate 100 --deadline 45 > sender.log 2>&1
sh tail -n 1 sender.log receiver.log
sh python3 analyze.py sender.log receiver.log controller.log fault.log
```

The clean run should complete with all 2,000 packets delivered. Save the logs before the next trial.

## 4. Demonstrate dynamic failover

Start a fresh trial in **dynamic** mode. Before starting the transfer, capture the current forwarding rules:

```text
sh ovs-ofctl -O OpenFlow13 dump-flows s1 > s1-before.log
sh ovs-ofctl -O OpenFlow13 dump-flows s4 > s4-before.log
```

Start both programs in the background so the Mininet prompt stays available:

```text
h2 python3 receiver.py --deadline 55 > receiver.log 2>&1 &
h1 python3 sender.py --count 2000 --rate 100 --deadline 45 > sender.log 2>&1 &
```

Wait about **five seconds**, then bring down the primary link:

```text
sh python3 -c "from common import log; log('fault')" > fault.log && ip link set dev s2-eth2 down
```

The topology assigns `s2-eth2` to the primary link from `s2` toward `s4`. Use `links` to confirm it before the demo.

Once the transfer ends, collect the evidence:

```text
sh grep reroute controller.log
sh ovs-ofctl -O OpenFlow13 dump-flows s1 > s1-after.log
sh ovs-ofctl -O OpenFlow13 dump-flows s4 > s4-after.log
sh tail -n 1 sender.log receiver.log
sh python3 analyze.py sender.log receiver.log controller.log fault.log
```

A successful failover shows three things:

- The controller logs a `reroute` event with `"path": "alternate"`.
- The forward rule on `s1` changes from output port `2` to `3`, and the reverse rule on `s4` changes from output port `1` to `2`.
- The sender logs ACKs after the reroute and the receiver reports its final unique delivery count.

Restore the link before exiting:

```text
sh ip link set dev s2-eth2 up
exit
```

Stop Ryu with **Ctrl+C**. Save the logs and flow dumps in a trial-specific folder before restarting. If Ryu reports that its Unix socket is already in use, confirm the old controller has stopped before removing `/tmp/ryu_loss.sock`.

## 5. Compare against static routing and repeat with packet loss

Restart Ryu in **static** mode and start Mininet again:

```bash
CN_MODE=static ryu-manager --ofp-tcp-listen-port 6653 controller.py > controller.log 2>&1
```

Repeat the link-down trial with the same packet count, rate, deadline, and fault timing. Static mode keeps forwarding on the primary path. Record the final delivery and whether ACK progress resumes within the deadline.

Then repeat the experiment with **40% packet loss** on the primary branch. In a fresh trial, use this command in place of the link-down command:

```text
sh python3 -c "from common import log; log('fault')" > fault.log && tc qdisc replace dev s2-eth2 root netem loss 40%
```

Remove the impairment after the run:

```text
sh tc qdisc del dev s2-eth2 root
```

Run each fault condition three times in both modes. Restart Mininet and Ryu between trials so each transfer starts on the primary path. Keep the impairment on `s2-eth2` so the alternate path can bypass it.

## 6. Record the results

Run the analyzer for each trial and enter the measured values below. Use one row per trial.

| Mode | Condition | Trial | First-attempt loss before / during / after | Unique delivery | Retransmissions | Fault to reroute | Fault to next ACK |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Dynamic | Clean | 1 | | | | | |
| Static | 40% primary-path loss | 1 | | | | | |
| Dynamic | 40% primary-path loss | 1 | | | | | |
| Static | Primary link down | 1 | | | | | |
| Dynamic | Primary link down | 1 | | | | | |

**First-attempt loss** counts original DATA packets that did not arrive on their first transmission. **Unique delivery** counts each sequence once, including packets recovered by retransmission. **Fault to reroute** measures when the controller issued the route change. **Fault to next ACK** measures when the sender next observed progress. Record `N/A` for a phase with no original packets and `No progress within deadline` when no subsequent ACK arrives.

Before submission, add the Linux, Python, Mininet, Open vSwitch, and Ryu versions used. Include the completed results table and representative logs or flow dumps so the comparison can be reproduced.

## Final demo sequence

1. Show the primary and alternate paths in Mininet.
2. Start a transfer and show the sender receiving ACKs.
3. Bring down the primary link while the transfer is active.
4. Show the controller’s reroute event, both updated forwarding rules, and ACKs resuming.
5. Show the static trial under the same fault and explain the measured difference in delivery and recovery.
