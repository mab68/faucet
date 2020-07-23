"""Manage a collection of Valves."""

# Copyright (C) 2013 Nippon Telegraph and Telephone Corporation.
# Copyright (C) 2015 Brad Cowie, Christopher Lorier and Joe Stringer.
# Copyright (C) 2015 Research and Education Advanced Network New Zealand Ltd.
# Copyright (C) 2015--2019 The Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from collections import defaultdict

from faucet.conf import InvalidConfigError
from faucet.config_parser_util import config_changed, CONFIG_HASH_FUNC
from faucet.config_parser import dp_parser, dp_preparsed_parser
from faucet.valve import valve_factory, SUPPORTED_HARDWARE
from faucet.valve_util import dpid_log, stat_config_files


class MetaDPState:
    """Contains state/config about all DPs."""

    def __init__(self):
        self.stack_root_name = None
        self.dp_last_live_time = {}
        self.top_conf = None
        self.last_good_config = {}
        self.config_hash_info = {}


class ConfigWatcher:
    """Watch config for file or content changes."""

    config_file = None
    config_hashes = None
    config_file_stats = None

    def files_changed(self):
        """Return True if any config files changed."""
        # TODO: Better to use an inotify method that doesn't conflict with eventlets.
        changed = False
        if self.config_hashes:
            new_config_file_stats = stat_config_files(self.config_hashes)
            if self.config_file_stats:
                # Check content as well in case mtime et al was cached.
                if new_config_file_stats == self.config_file_stats:
                    changed = self.content_changed(self.config_file)
                else:
                    changed = True
            self.config_file_stats = new_config_file_stats
        return changed

    def content_changed(self, new_config_file):
        """Return True if config file content actually changed."""
        return config_changed(self.config_file, new_config_file, self.config_hashes)

    def update(self, new_config_file, new_config_hashes=None):
        """Update state with new config file/hashes."""
        self.config_file = new_config_file
        if new_config_hashes is None:
            new_config_hashes = {new_config_file: None}
        if new_config_hashes:
            self.config_hashes = new_config_hashes


class ValvesManager:
    """Manage a collection of Valves."""

    valves = None # type: dict

    def __init__(self, logname, logger, metrics, notifier, bgp,
                 dot1x, config_auto_revert, send_flows_to_dp_by_id):
        """Initialize ValvesManager.

        Args:
            logname (str): log name to use in logging.
            logger (logging.logging): logger instance to use for logging.
            metrics (FaucetMetrics): metrics instance.
            notifier (FaucetEvent): event notifier instance.
            bgp (FaucetBgp): BGP instance.
            config_auto_revert (bool): True if FAUCET should attempt to revert bad configs.
            send_flows_to_dp_by_id: callable, two args - DP ID and list of flows to send to DP.
        """
        self.logname = logname
        self.logger = logger
        self.metrics = metrics
        self.notifier = notifier
        self.bgp = bgp
        self.dot1x = dot1x
        self.config_auto_revert = config_auto_revert
        self.send_flows_to_dp_by_id = send_flows_to_dp_by_id
        self.valves = {}
        self.config_applied = {}
        self.config_watcher = ConfigWatcher()
        self.meta_dp_state = MetaDPState()

    def update_dp_live_time(self, now):
        """
        Update DP running time

        Args:
            now (float): Current time
        """
        for valve in self.valves.values():
            if valve.dp.dyn_running:
                self.meta_dp_state.dp_last_live_time[valve.dp.name] = now

    def inconsistent_stack_roots(self):
        """Return DP names that do not agree with the current root state"""
        inconsistent_dps = []
        for valve in self.valves.values():
            if valve.stack_manager:
                if valve.stack_manager.stack.root_name != self.meta_dp_state.stack_root_name:
                    inconsistent_dps.append(valve.dp.name)
        return inconsistent_dps

    def maintain_stack_root(self, now, update_time):
        """
        Maintain current stack root

        Args:
            now (float): Current time
            update_time (int): Stack root update time interval
        """
        import sys
        self.update_dp_live_time(now)
        last_live_times = self.meta_dp_state.dp_last_live_time

        # Get candidate healthy stack valves
        unhealthy_root_valves = []
        healthy_root_valves = []
        for valve in self.valves.values():
            if valve.stack_manager and valve.dp.stack.is_root_candidate():
                sys.stderr.write('Root candidate: %s\n' % valve.dp.name)
                healthy = valve.stack_manager.update_health(now, last_live_times, update_time)
                if healthy:
                    sys.stderr.write('Healthy: %s\n' % valve.dp.name)
                    healthy_root_valves.append(valve)
                else:
                    sys.stderr.write('Unhealthy: %s\n' % valve.dp.name)
                    unhealthy_root_valves.append(valve)

        if not healthy_root_valves and not unhealthy_root_valves:
            sys.stderr.write('No stack root candidates\n')
            return False

        # Choose a candidate valve to be the root
        prev_root_name = self.meta_dp_state.stack_root_name
        prev_root_valve = [valve for valve in self.valves.values() if valve.dp.name == prev_root_name][0]
        if healthy_root_valves:
            if self.meta_dp_state.stack_root_name not in healthy_root_valves:
                # Need to pick a new healthy root if current root not healthy
                new_root_name = healthy_root_valves[0].dp.name
                new_root_valve = healthy_root_valves[0]
        else:
            # No healthy stack roots, so choose a (random) valve
            new_root_name = unhealthy_root_valves[0].dp.name
            new_root_valve = unhealthy_root_valves[0]

        sys.stderr.write('New root name %s\n' % new_root_name)

        stack_change = False
        if self.meta_dp_state.stack_root_name != new_root_name:
            # Current stack root is not the new stack root, 
            self.logger.info('stack root changed from %s to %s' % (
                self.meta_dp_state.stack_root_name, new_root_name))
            if self.meta_dp_state.stack_root_name:
                stack_change = True
                labels = prev_root_valve.dp.base_prom_labels()
                self.metrics.is_dp_stack_root.labels(**labels).set(0)
            self.meta_dp_state.stack_root_name = new_root_name
            self.metrics.faucet_stack_root_dpid.set(new_root_valve.dp.dp_id)
        else:
            # Current stack root does not change, however ensure that the current stack root
            #   is known for all DPs
            inconsistent_dps = self.inconsistent_stack_roots()
            if inconsistent_dps:
                sys.stderr.write('Inconsistent Dps\n')
                self.logger.info('stack root on %s inconsistent' % inconsistent_dps)
                stack_change = True

        if stack_change:
            sys.stderr.write('Root changed\n')
            # Stack root changed, force restart on all DPs
            self.logger.info('Stack root changed to %s (previous %s)' % (
                new_root_name, prev_root_name))
            dps = dp_preparsed_parser(self.meta_dp_state.top_conf, self.meta_dp_state)
            self._apply_configs(dps, now, None)

        labels = new_root_valve.dp.base_prom_labels()
        self.metrics.is_dp_stack_root.labels(**labels).set(1)
        return stack_change

    def event_socket_heartbeat(self, now):
        """raises event for event sock heartbeat"""
        self._notify({'EVENT_SOCK_HEARTBEAT': None})

    def revert_config(self):
        """Attempt to revert config to last known good version."""
        for config_file_name, config_content in self.meta_dp_state.last_good_config.items():
            self.logger.info('attempting to revert to last good config: %s' % config_file_name)
            try:
                with open(config_file_name, 'w') as config_file:
                    config_file.write(str(config_content))
            except (FileNotFoundError, OSError, PermissionError) as err:
                self.logger.error('could not revert %s: %s' % (config_file_name, err))
                return
        self.logger.info('successfully reverted to last good config')

    def parse_configs(self, new_config_file):
        """Return parsed configs for Valves, or None."""
        self.metrics.faucet_config_hash_func.labels(algorithm=CONFIG_HASH_FUNC)
        try:
            new_conf_hashes, new_config_content, new_dps, top_conf = dp_parser(
                new_config_file, self.logname, self.meta_dp_state)
            new_present_conf_hashes = [
                (conf_file, conf_hash) for conf_file, conf_hash in sorted(new_conf_hashes.items())
                if conf_hash is not None]
            conf_files = [conf_file for conf_file, _ in new_present_conf_hashes]
            conf_hashes = [conf_hash for _, conf_hash in new_present_conf_hashes]
            self.config_watcher.update(new_config_file, new_conf_hashes)
            self.meta_dp_state.top_conf = top_conf
            self.meta_dp_state.last_good_config = new_config_content
            self.meta_dp_state.config_hash_info = dict(
                config_files=','.join(conf_files), hashes=','.join(conf_hashes), error='')
            self.metrics.faucet_config_hash.info(self.meta_dp_state.config_hash_info)
            self.metrics.faucet_config_load_error.set(0)
        except InvalidConfigError as err:
            self.logger.error('New config bad (%s) - rejecting', err)
            # If the config was reverted, let the watcher notice.
            if self.config_auto_revert:
                self.revert_config()
            self.config_watcher.update(new_config_file)
            self.meta_dp_state.config_hash_info = dict(
                config_files=new_config_file, hashes='', error=str(err))
            self.metrics.faucet_config_hash.info(self.meta_dp_state.config_hash_info)
            self.metrics.faucet_config_load_error.set(1)
            new_dps = None
        return new_dps

    def new_valve(self, new_dp):
        valve_cl = valve_factory(new_dp)
        if valve_cl is not None:
            return valve_cl(new_dp, self.logname, self.metrics, self.notifier, self.dot1x)
        self.logger.error(
            '%s hardware %s must be one of %s',
            new_dp.name,
            new_dp.hardware,
            sorted(list(SUPPORTED_HARDWARE.keys())))
        return None

    def _apply_configs(self, new_dps, now, delete_dp):
        self.update_config_applied(reset=True)
        if new_dps is None:
            return False
        deleted_dpids = {v for v in self.valves} - {dp.dp_id for dp in new_dps}
        sent = {}
        for new_dp in new_dps:
            dp_id = new_dp.dp_id
            if dp_id in self.valves:
                self.logger.info('Reconfiguring existing datapath %s', dpid_log(dp_id))
                valve = self.valves[dp_id]
                ofmsgs = valve.reload_config(now, new_dp)
                self.send_flows_to_dp_by_id(valve, ofmsgs)
                sent[dp_id] = valve.dp.dyn_running
            else:
                self.logger.info('Add new datapath %s', dpid_log(new_dp.dp_id))
                valve = self.new_valve(new_dp)
                if valve is None:
                    continue
                self._notify({'CONFIG_CHANGE': {'restart_type': 'new'}}, dp=new_dp)
            valve.update_config_metrics()
            self.valves[dp_id] = valve
        if delete_dp is not None:
            for deleted_dp in deleted_dpids:
                delete_dp(deleted_dp)
                del self.valves[deleted_dp]
        self.bgp.reset(self.valves)
        self.dot1x.reset(self.valves)
        self.update_config_applied(sent)
        return True

    def load_configs(self, now, new_config_file, delete_dp=None):
        """Load/apply new config to all Valves."""
        return self._apply_configs(self.parse_configs(new_config_file), now, delete_dp)

    def _send_ofmsgs_by_valve(self, ofmsgs_by_valve):
        if ofmsgs_by_valve:
            for valve, ofmsgs in ofmsgs_by_valve.items():
                self.send_flows_to_dp_by_id(valve, ofmsgs)

    def _notify(self, event_dict, dp=None):
        """Send an event notification."""
        if dp:
            self.notifier.notify(dp.dp_id, dp.name, event_dict)
        else:
            self.notifier.notify(0, str(0), event_dict)

    def request_reload_configs(self, now, new_config_file, delete_dp=None):
        """Process a request to load config changes."""
        if self.config_watcher.content_changed(new_config_file):
            self.logger.info('configuration %s changed, analyzing differences', new_config_file)
            result = self.load_configs(now, new_config_file, delete_dp=delete_dp)
            self._notify({'CONFIG_CHANGE':
                          {'success': result,
                           'config_hash_info': self.meta_dp_state.config_hash_info}})
        else:
            self.logger.info('configuration is unchanged, not reloading')
            self.metrics.faucet_config_load_error.set(0)
        self.metrics.faucet_config_reload_requests.inc() # pylint: disable=no-member

    def update_metrics(self, now):
        """Update metrics in all Valves."""
        for valve in self.valves.values():
            valve.update_metrics(now, rate_limited=False)
        self.bgp.update_metrics(now)

    def valve_flow_services(self, now, valve_service):
        """Call a method on all Valves and send any resulting flows."""
        ofmsgs_by_valve = defaultdict(list)
        for valve in self.valves.values():
            other_valves = self._other_running_valves(valve)
            valve_service_labels = dict(valve.dp.base_prom_labels(), valve_service=valve_service)
            valve_service_func = getattr(valve, valve_service)
            with self.metrics.faucet_valve_service_secs.labels( # pylint: disable=no-member
                    **valve_service_labels).time():
                for service_valve, ofmsgs in valve_service_func(now, other_valves).items():
                    # Since we are calling all Valves, keep only the ofmsgs
                    # provided by the last Valve called (eventual consistency).
                    if service_valve in ofmsgs_by_valve:
                        ofmsgs_by_valve[service_valve] = []
                    ofmsgs_by_valve[service_valve].extend(ofmsgs)
        self._send_ofmsgs_by_valve(ofmsgs_by_valve)

    def _other_running_valves(self, valve):
        return [other_valve for other_valve in self.valves.values()
                if valve != other_valve and other_valve.dp.dyn_running]

    def port_status_handler(self, valve, msg, now):
        """Handle a port status change message."""
        ofmsgs_by_valve = valve.port_status_handler(
            msg.desc.port_no, msg.reason, msg.desc.state, self._other_running_valves(valve), now)
        self._send_ofmsgs_by_valve(ofmsgs_by_valve)

    def valve_packet_in(self, now, valve, msg):
        """Time a call to Valve packet in handler."""
        self.metrics.of_packet_ins.labels( # pylint: disable=no-member
            **valve.dp.base_prom_labels()).inc()
        if valve.rate_limit_packet_ins(now):
            return
        pkt_meta = valve.parse_pkt_meta(msg)
        if pkt_meta is None:
            self.metrics.of_unexpected_packet_ins.labels( # pylint: disable=no-member
                **valve.dp.base_prom_labels()).inc()
            return
        with self.metrics.faucet_packet_in_secs.labels( # pylint: disable=no-member
                **valve.dp.base_prom_labels()).time():
            ofmsgs_by_valve = valve.rcv_packet(now, self._other_running_valves(valve), pkt_meta)
        if ofmsgs_by_valve:
            self._send_ofmsgs_by_valve(ofmsgs_by_valve)
            valve.update_metrics(now, pkt_meta.port, rate_limited=True)

    def update_config_applied(self, sent=None, reset=False):
        """Update faucet_config_applied from {dpid: sent} dict,
           defining applied == sent == enqueued via Ryu"""
        if reset:
            self.config_applied = defaultdict(bool)
        if sent:
            self.config_applied.update(sent)
        count = float(len(self.valves))
        configured = sum((1 if self.config_applied[dp_id] else 0)
                         for dp_id in self.valves)
        fraction = configured/count if count > 0 else 0
        self.metrics.faucet_config_applied.set(fraction)

    def datapath_connect(self, now, valve, discovered_up_ports):
        """Handle connection from DP."""
        self.meta_dp_state.dp_last_live_time[valve.dp.name] = now
        self.update_config_applied({valve.dp.dp_id: True})
        return valve.datapath_connect(now, discovered_up_ports)
