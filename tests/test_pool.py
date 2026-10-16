"""Allocator invariants with real session engines and deterministic portal I/O."""
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from test_integration import campus_network as cn, Clock, Portal


class PoolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clock = Clock()
        self.portals = {}
        self.networks = {}
        self.config = dict(cn.DEFAULT_CONFIG, initial_jitter=0)
        self.pool = self.make_pool()

    def factory(self, config):
        if config['source_address'] not in self.portals:
            portal = Portal()
            portal.probe_result['query'] = 'wlanuserip=' + (config['source_address'] or '10.0.0.1')
            self.portals[config['source_address']] = portal
        return self.portals[config['source_address']]

    def network(self, item):
        ready = self.networks.get(item['address'], True)
        return {'ready': ready, 'link': ready, 'interface': item['address'] or 'eth-test',
                'source_address': item['address'] or '10.0.0.1',
                'signature': (item['address'], ready), 'reason': 'test network'}

    def make_pool(self):
        return cn.PoolController(self.config, self.root / 'state', self.root / 'account.json',
                                 portal_factory=self.factory, network=self.network,
                                 clock=self.clock, wall=self.clock, rng=lambda low, high: low)

    def add_account(self, name):
        self.pool.command({'command': 'pool-add', 'kind': 'accounts',
                           'value': {'username': name, 'password': 'secret-' + name, 'service': '移动'}})
        return self.pool.data['accounts'][-1]['id']

    def add_ip(self, address):
        self.pool.command({'command': 'pool-add', 'kind': 'ips', 'value': {'address': address}})
        return self.pool.data['ips'][-1]['id']

    def tick(self, seconds=6):
        self.clock.advance(seconds)
        self.pool.step(wait=True)
        self.assertFalse(self.pool.worker_errors)

    def connect(self):
        self.pool.command({'command': 'on'})
        self.tick()
        self.tick()
        self.assertEqual(self.pool.snapshot()['state'], 'online')

    def lose(self, address=''):
        self.portals[address].probe_result = {'kind': 'portal', 'query': 'test', 'reason': 'needs login'}
        self.tick()
        self.tick()

    def test_single_account_cools_without_reclaiming_student_session(self):
        account = self.add_account('main')
        self.connect()
        self.lose()
        self.tick()
        self.assertGreater(self.pool._find('accounts', account)['cooldown_until'], self.clock())
        self.assertEqual(self.portals[''].count('login'), 1)
        self.assertEqual(self.portals[''].count('logout'), 0)
        self.assertFalse(self.pool.data['bindings'])
        self.pool.command({'command': 'off'})
        self.pool.command({'command': 'on'})
        self.tick()
        self.assertEqual(self.portals[''].count('login'), 1)
        self.tick(43201)
        self.assertEqual(self.portals[''].count('login'), 2)

    def test_second_account_takes_over_same_primary_ip(self):
        main = self.add_account('main')
        spare = self.add_account('spare')
        self.connect()
        self.lose()
        self.tick()
        self.tick()
        self.assertEqual(self.pool.data['bindings']['primary']['account'], spare)
        self.assertGreater(self.pool._find('accounts', main)['cooldown_until'], self.clock())
        self.assertEqual(self.pool.snapshot()['state'], 'online')
        self.tick(43201)
        self.assertEqual(self.pool.data['bindings']['primary']['account'], spare)
        self.lose()
        self.tick()
        self.assertEqual(self.pool.data['bindings']['primary']['account'], main)

    def test_restart_disable_and_off_on_preserve_cooldown(self):
        main = self.add_account('main')
        self.connect()
        self.lose()
        until = self.pool._find('accounts', main)['cooldown_until']
        self.pool = self.make_pool()
        for enabled in (False, True):
            self.pool.command({'command': 'pool-enable', 'kind': 'accounts', 'id': main, 'enabled': enabled})
        self.tick()
        self.assertEqual(self.pool._find('accounts', main)['cooldown_until'], until)
        self.assertEqual(self.portals[''].count('login'), 1)
        self.assertEqual(self.portals[''].count('logout'), 0)

    def test_secondary_prefers_other_accounts_and_main_is_last_resort(self):
        main = self.add_account('main')
        spare = self.add_account('spare')
        third = self.add_account('third')
        ip = self.add_ip('10.0.0.2')
        self.connect()
        self.assertEqual(self.pool.data['bindings']['primary']['account'], main)
        self.assertEqual(self.pool.data['bindings'][ip]['account'], spare)
        # Make the spare the new primary account, so the old main becomes a secondary candidate.
        self.pool.command({'command': 'pool-primary', 'kind': 'accounts', 'id': main})
        self.pool.command({'command': 'pool-enable', 'kind': 'ips', 'id': 'primary', 'enabled': False})
        self.tick()
        self.tick()
        ip2 = self.add_ip('10.0.0.3')
        self.tick()
        self.assertEqual(self.pool.data['bindings'][ip2]['account'], third)
        ip3 = self.add_ip('10.0.0.4')
        self.tick()
        self.assertEqual(self.pool.data['bindings'][ip3]['account'], main)

    def test_main_reclaims_secondary_even_if_logout_is_ineffective(self):
        main = self.add_account('main')
        spare = self.add_account('spare')
        ip = self.add_ip('10.0.0.2')
        self.connect()
        self.portals['10.0.0.2'].logout_result = {'result': 'fail', 'message': 'busy'}
        self.lose()
        for _ in range(4):
            self.tick()
        self.assertEqual(self.pool.data['bindings']['primary']['account'], spare)
        self.assertNotIn(ip, self.pool.data['bindings'])
        self.assertGreater(self.pool._find('accounts', main)['cooldown_until'], self.clock())
        self.assertEqual(self.portals[''].calls[-1][0], 'probe')
        self.assertEqual(self.portals['10.0.0.2'].count('logout'), 1)

    def test_external_failure_link_loss_and_one_captive_sample_do_not_rotate(self):
        main = self.add_account('main')
        self.add_account('spare')
        self.connect()
        self.portals[''].probe_result = {'kind': 'unknown', 'reason': 'upstream failure'}
        for _ in range(3):
            self.tick()
        self.networks[''] = False
        self.tick()
        self.networks[''] = True
        self.portals[''].probe_result = {'kind': 'portal', 'query': 'test'}
        self.tick()
        self.portals[''].probe_result = {'kind': 'online', 'reason': 'recovered'}
        self.tick()
        self.assertEqual(self.pool.data['bindings']['primary']['account'], main)
        self.assertEqual(self.pool._find('accounts', main)['cooldown_until'], 0)
        self.assertEqual(self.portals[''].count('login'), 1)

    def test_correlated_captive_failures_hold_all_accounts(self):
        self.add_account('main')
        self.add_account('spare')
        self.add_ip('10.0.0.2')
        self.connect()
        for portal in self.portals.values():
            portal.probe_result = {'kind': 'portal', 'query': 'test'}
        for _ in range(4):
            self.tick()
        self.assertTrue(all(a['cooldown_until'] == 0 for a in self.pool.data['accounts']))
        self.assertTrue(all(p.count('login') == 1 for p in self.portals.values()))

    def test_disable_account_stops_and_releases_only_its_slot(self):
        main = self.add_account('main')
        spare = self.add_account('spare')
        ip = self.add_ip('10.0.0.2')
        self.connect()
        self.pool.command({'command': 'pool-enable', 'kind': 'accounts', 'id': spare, 'enabled': False})
        self.assertEqual(self.pool.engines[ip].state['mode'], 'off')
        self.tick()
        self.tick()
        self.assertNotIn(ip, self.pool.data['bindings'])
        self.assertEqual(self.pool.data['bindings']['primary']['account'], main)
        self.assertEqual(self.portals[''].count('logout'), 0)
        self.assertEqual(self.portals['10.0.0.2'].count('logout'), 1)

    def test_off_during_login_retains_reservation_until_new_token_is_released(self):
        self.add_account('main')
        portal = self.portals.setdefault('', Portal())
        portal.login_started, portal.login_continue = threading.Event(), threading.Event()
        self.pool.command({'command': 'on'})
        self.pool.step()
        try:
            self.assertTrue(portal.login_started.wait(2))
            started = time.monotonic()
            self.pool.command({'command': 'off'})
            self.assertLess(time.monotonic() - started, .5)
            self.assertIn('primary', self.pool.data['bindings'])
        finally:
            portal.login_continue.set()
            self.pool.workers['primary'].join(2)
        self.tick()
        self.tick()
        self.assertFalse(self.pool.data['bindings'])
        self.assertEqual(portal.count('login'), 1)
        self.assertEqual(portal.count('logout'), 1)

    def test_unknown_login_result_survives_restart_without_retry_or_reassignment(self):
        self.add_account('main')
        self.add_account('spare')
        self.portals[''] = Portal()
        self.portals[''].login_error = subprocess.TimeoutExpired('curl', 5)
        self.pool.command({'command': 'on'})
        self.tick()
        self.pool = self.make_pool()
        for _ in range(3):
            self.tick()
        self.assertEqual(self.portals[''].count('login'), 1)
        self.assertEqual(len(self.pool.data['bindings']), 1)

    def test_rejected_account_cools_and_spare_is_tried(self):
        main = self.add_account('main')
        spare = self.add_account('spare')
        self.portals[''] = Portal()
        self.portals[''].login_result = {'result': 'fail', 'message': 'restricted'}
        self.pool.command({'command': 'on'})
        self.tick()
        self.assertGreater(self.pool._find('accounts', main)['cooldown_until'], self.clock())
        self.portals[''].login_result = {'result': 'success', 'userIndex': 'new-token'}
        self.tick()
        self.assertEqual(self.pool.data['bindings']['primary']['account'], spare)

    def test_source_addresses_cannot_alias_automatic_main(self):
        self.add_account('main')
        self.add_account('spare')
        ip = self.add_ip('10.0.0.1')
        self.connect()
        self.assertNotIn(ip, self.pool.data['bindings'])

    def test_wrong_captive_ip_does_not_authenticate_or_cool_account(self):
        main = self.add_account('main')
        self.connect()
        self.portals[''].probe_result = {'kind': 'portal', 'query': 'wlanuserip=10.0.0.99'}
        for _ in range(3):
            self.tick()
        self.assertEqual(self.pool._find('accounts', main)['cooldown_until'], 0)
        self.assertEqual(self.portals[''].count('login'), 1)

    def test_pool_status_has_no_password_or_session_token(self):
        self.add_account('main')
        self.connect()
        public = json.dumps(self.pool.snapshot())
        self.assertNotIn('secret-main', public)
        self.assertNotIn('private-session-42', public)

    def test_duplicate_username_other_operator_is_rejected(self):
        self.add_account('main')
        with self.assertRaises(ValueError):
            self.pool.command({'command': 'pool-add', 'kind': 'accounts',
                               'value': {'username': 'main', 'password': 'other', 'service': '电信'}})

    def test_legacy_session_migrates_without_login_and_is_released(self):
        root = Path(self.temp.name) / 'legacy'
        root.mkdir()
        cn.atomic_json(root / 'state.json', {'mode': 'off', 'session': 'old-token', 'generation': 3})
        cn.atomic_json(self.root / 'account.json', {'username': 'old', 'password': 'private', 'service': '校园网'})
        pool = cn.PoolController(self.config, root, self.root / 'account.json',
                                 portal_factory=self.factory, network=self.network, rng=lambda low, high: low)
        self.assertEqual(pool.engines['primary'].state['session'], 'old-token')
        pool.step(wait=True)
        pool.step(wait=True)
        self.assertFalse(pool.data['bindings'])
        self.assertEqual(self.portals[''].count('login'), 0)
        self.assertEqual(self.portals[''].calls[-1], ('logout', 'old-token'))

    def test_corrupt_cooldown_fails_closed(self):
        self.add_account('main')
        self.pool.data['accounts'][0]['cooldown_until'] = 'broken'
        self.pool._save()
        with self.assertRaises(ValueError):
            self.make_pool()

    def test_busy_portal_retries_without_consuming_account_pool(self):
        main = self.add_account('main')
        self.add_account('spare')
        self.portals[''] = Portal()
        self.portals[''].login_result = {'result': 'fail', 'message': 'server busy'}
        self.pool.command({'command': 'on'})
        for _ in range(3):
            self.tick()
        self.assertEqual(self.pool._find('accounts', main)['cooldown_until'], 0)
        self.assertEqual(self.pool.data['bindings']['primary']['account'], main)
        self.assertEqual(self.portals[''].count('login'), 3)

    def test_existing_unowned_connectivity_is_not_claimed_or_reauthenticated(self):
        self.add_account('main')
        self.portals[''] = Portal()
        self.portals[''].probe_result = {'kind': 'online', 'reason': 'existing connection'}
        self.pool.command({'command': 'on'})
        self.tick()
        self.assertEqual(self.pool.snapshot()['state'], 'online-unowned')
        self.assertEqual(self.pool.snapshot()['ips'][0]['ownership'], 'unconfirmed')
        self.assertEqual(self.portals[''].count('login'), 0)

    def test_blocked_ip_does_not_block_other_ip_or_control(self):
        self.add_account('main')
        self.add_account('spare')
        self.add_ip('10.0.0.2')
        main = self.portals.setdefault('', Portal())
        secondary = self.portals.setdefault('10.0.0.2', Portal())
        secondary.probe_result['query'] = 'wlanuserip=10.0.0.2'
        main.login_started, main.login_continue = threading.Event(), threading.Event()
        self.pool.command({'command': 'on'})
        self.pool.step()
        try:
            self.assertTrue(main.login_started.wait(2))
            self.pool.workers[self.pool.data['ips'][1]['id']].join(2)
            self.assertEqual(secondary.count('login'), 1)
            started = time.monotonic()
            self.pool.command({'command': 'status'})
            self.pool.command({'command': 'off'})
            self.assertLess(time.monotonic() - started, .5)
        finally:
            main.login_continue.set()
            self.pool.workers['primary'].join(2)

    def test_confirming_network_io_does_not_hold_control_lock(self):
        self.add_account('main')
        self.connect()
        engine = self.pool.engines['primary']
        started, release = threading.Event(), threading.Event()
        calls = []
        def network():
            calls.append(True)
            if len(calls) == 2:
                started.set()
                release.wait(3)
            return self.network(self.pool.data['ips'][0])
        engine.network = network
        self.clock.advance(6)
        self.pool.step()
        try:
            self.assertTrue(started.wait(2))
            before = time.monotonic()
            self.pool.command({'command': 'off'})
            self.assertLess(time.monotonic() - before, .5)
        finally:
            release.set()
            self.pool.workers['primary'].join(2)

    def test_off_during_captive_probe_does_not_cool_account(self):
        account = self.add_account('main')
        self.connect()
        portal = self.portals['']
        portal.probe_result = {'kind': 'portal', 'query': 'test'}
        portal.probe_started, portal.probe_continue = threading.Event(), threading.Event()
        self.clock.advance(6)
        self.pool.step()
        try:
            self.assertTrue(portal.probe_started.wait(2))
            self.pool.command({'command': 'off'})
        finally:
            portal.probe_continue.set()
            self.pool.workers['primary'].join(2)
        self.assertEqual(self.pool._find('accounts', account)['cooldown_until'], 0)

    def test_displacement_journal_replay_never_sends_old_logout(self):
        self.add_account('main')
        self.connect()
        self.lose()
        # Recreate the engine journal left by a crash just after pool cooldown fsync.
        engine = self.pool.engines['primary']
        engine._save(mode='on', session='stale-token', uncertain=False)
        self.pool = self.make_pool()
        self.tick()
        self.assertFalse(self.pool.data['bindings'])
        self.assertEqual(self.portals[''].count('logout'), 0)


class SourceRoutingTests(unittest.TestCase):
    def test_wrong_device_source_route_is_not_ready(self):
        with patch.object(cn.subprocess, 'run', side_effect=[
            subprocess.CompletedProcess([], 0, json.dumps([{'ifname': 'wlan0', 'flags': ['UP'], 'addr_info': [{'local': '10.0.0.2'}]}]).encode()),
            subprocess.CompletedProcess([], 0, b'[{"dev":"eth0"}]')]):
            self.assertFalse(cn.inspect_slot(cn.valid_ip({'address': '10.0.0.2'}), cn.DEFAULT_CONFIG)['ready'])

    def test_namespace_and_source_binding_are_passed_as_arguments(self):
        portal = cn.Portal(dict(cn.DEFAULT_CONFIG, namespace='campus-2'))
        portal.interface = '10.0.0.2'
        with patch.object(portal, 'runner', return_value=subprocess.CompletedProcess([], 0, b'ok\n200')) as run:
            portal.request('https://example.org')
        args = run.call_args.args[0]
        self.assertEqual(args[:5], ['ip', 'netns', 'exec', 'campus-2', 'curl'])
        self.assertEqual(args[args.index('--interface') + 1], '10.0.0.2')

    def test_captive_hint_does_not_override_verified_https(self):
        portal = cn.Portal({})
        portal.verify_portal = True
        with patch.object(portal, 'request', side_effect=[(200, "index.jsp?a=b"), (200, '百度')]):
            self.assertEqual(portal.probe()['kind'], 'online')


if __name__ == '__main__':
    unittest.main()
