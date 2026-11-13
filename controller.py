"""OpenFlow controller for the two Mininet paths."""
import os
import socket
import time

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.lib import hub
from ryu.ofproto import ofproto_v1_3

from common import REPORT_SOCKET, log

H1_IP = "10.0.0.1"
H2_IP = "10.0.0.2"
PATHS = {"primary": {1: 2, 4: 1}, "alternate": {1: 3, 4: 2}}
PORTS = {
    "primary": {(1, 2), (2, 1), (2, 2), (4, 1)},
    "alternate": {(1, 3), (3, 1), (3, 2), (4, 2)},
}


class LossRecoveryController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.static = os.getenv("CN_MODE") == "static"
        self.dps = {}
        self.initialized = False
        self.down = set()
        self.active = "primary"
        self.high = 0
        self.last_switch = float("-inf")
        hub.spawn(self.listen)

    def listen(self):
        # Keep socket reads nonblocking so Ryu can process OpenFlow events.
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as server:
            server.bind(REPORT_SOCKET)
            server.setblocking(False)
            log("controller_ready", mode="static" if self.static else "dynamic")
            try:
                while True:
                    try:
                        raw = server.recv(256)
                    except BlockingIOError:
                        hub.sleep(0.05)
                        continue
                    try:
                        loss = float(raw)
                    except ValueError:
                        continue
                    if 0 <= loss <= 100:
                        log("loss_report", loss=loss, path=self.active)
                        self.high = self.high + 1 if loss >= 15 else 0
                        if self.high >= 2 and time.monotonic() - self.last_switch >= 5:
                            self.reroute("sustained_loss")
            finally:
                os.unlink(REPORT_SOCKET)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def on_features(self, ev):
        dp = ev.msg.datapath
        self.dps[dp.id] = dp
        self.initialized |= len(self.dps) == 4
        self._install_static(dp)
        self._install_path(dp, self.active)
    @set_ev_cls(ofp_event.EventOFPStateChange, MAIN_DISPATCHER)
    def on_connected(self, ev):
        dp = ev.datapath
        dp.send_msg(dp.ofproto_parser.OFPPortDescStatsRequest(dp, 0))

    def update_port(self, dp, port, deleted=False):
        key = (dp.id, port.port_no)
        down = port.state & dp.ofproto.OFPPS_LINK_DOWN
        down = down or port.config & dp.ofproto.OFPPC_PORT_DOWN
        if down or deleted:
            self.down.add(key)
        else:
            self.down.discard(key)

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def on_ports(self, ev):
        for port in ev.msg.body:
            self.update_port(ev.msg.datapath, port)
        self.check_path()

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def on_port(self, ev):
        msg = ev.msg
        self.update_port(msg.datapath, msg.desc,
                         msg.reason == msg.datapath.ofproto.OFPPR_DELETE)
        self.check_path()

    @set_ev_cls(ofp_event.EventOFPStateChange, DEAD_DISPATCHER)
    def on_disconnect(self, ev):
        dp = ev.datapath
        if self.dps.get(dp.id) is dp:
            del self.dps[dp.id]
            self.check_path()

    def available(self, name):
        return all(dpid in self.dps for dpid, _ in PORTS[name]) and not (
            PORTS[name] & self.down
        )

    def check_path(self):
        if PORTS[self.active] & self.down or (self.initialized and not self.available(self.active)):
            self.reroute("link_or_switch_down")

    def reroute(self, reason):
        target = "alternate" if self.active == "primary" else "primary"
        if self.static or not self.available(target):
            return
        for dpid in (1, 4):
            self._install_path(self.dps[dpid], target)
        self.active = target
        self.high = 0
        self.last_switch = time.monotonic()
        log("reroute", path=target, reason=reason)

    def _add_flow(self, dp, ip_dst, out_port, priority=10):
        p, o = dp.ofproto_parser, dp.ofproto
        match = p.OFPMatch(eth_type=0x0800, ipv4_dst=ip_dst)
        actions = [p.OFPActionOutput(out_port)]
        inst = [p.OFPInstructionActions(o.OFPIT_APPLY_ACTIONS, actions)]
        dp.send_msg(p.OFPFlowMod(datapath=dp, priority=priority, match=match, instructions=inst))

    def _install_static(self, dp):
        if dp.id == 1:
            self._add_flow(dp, H1_IP, 1)
        elif dp.id in (2, 3):
            self._add_flow(dp, H2_IP, 2)
            self._add_flow(dp, H1_IP, 1)
        elif dp.id == 4:
            self._add_flow(dp, H2_IP, 3)

    def _install_path(self, dp, name):
        if dp.id == 1:
            self._add_flow(dp, H2_IP, PATHS[name][1])
        elif dp.id == 4:
            self._add_flow(dp, H1_IP, PATHS[name][4])

