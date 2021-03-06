# Copyright 2018 Red Hat, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from oslo_utils import uuidutils
import testtools

from neutron.agent.linux import ip_lib
from neutron.common import utils as common_utils
from neutron.privileged.agent.linux import ip_lib as priv_ip_lib
from neutron.tests.functional import base as functional_base


def _get_attr(pyroute2_obj, attr_name):
    rule_attrs = pyroute2_obj.get('attrs', [])
    for attr in (attr for attr in rule_attrs if attr[0] == attr_name):
        return attr[1]
    return


class GetDeviceNamesTestCase(functional_base.BaseSudoTestCase):

    def _remove_ns(self, namespace):
        priv_ip_lib.remove_netns(namespace)

    def test_get_device_names(self):
        namespace = 'ns_test-' + uuidutils.generate_uuid()
        priv_ip_lib.create_netns(namespace)
        self.addCleanup(self._remove_ns, namespace)
        interfaces = ['int_01', 'int_02', 'int_03', 'int_04', 'int_05']
        interfaces_to_check = (interfaces + ip_lib.FB_TUNNEL_DEVICE_NAMES +
                               [ip_lib.LOOPBACK_DEVNAME])
        for interface in interfaces:
            priv_ip_lib.create_interface(interface, namespace, 'dummy')

        device_names = priv_ip_lib.get_device_names(namespace)
        self.assertGreater(len(device_names), 0)
        for name in device_names:
            self.assertIn(name, interfaces_to_check)

        for interface in interfaces:
            priv_ip_lib.delete_interface(interface, namespace)

        device_names = priv_ip_lib.get_device_names(namespace)
        self.assertGreater(len(device_names), 0)
        for name in device_names:
            self.assertNotIn(name, interfaces)


class ListIpRulesTestCase(functional_base.BaseSudoTestCase):

    RULE_TABLES = {'default': 253, 'main': 254, 'local': 255}

    def setUp(self):
        super(ListIpRulesTestCase, self).setUp()
        self.namespace = 'ns_test-' + uuidutils.generate_uuid()
        self.ns = priv_ip_lib.create_netns(self.namespace)
        self.addCleanup(self._remove_ns)

    def _remove_ns(self):
        priv_ip_lib.remove_netns(self.namespace)

    def test_list_default_rules_ipv4(self):
        rules_ipv4 = priv_ip_lib.list_ip_rules(self.namespace, 4)
        self.assertEqual(3, len(rules_ipv4))
        rule_tables = list(self.RULE_TABLES.values())
        for rule in rules_ipv4:
            rule_tables.remove(rule['table'])
        self.assertEqual(0, len(rule_tables))

    def test_list_rules_ipv4(self):
        ip_lib.add_ip_rule(self.namespace, '192.168.0.1/24', table=10)
        rules_ipv4 = priv_ip_lib.list_ip_rules(self.namespace, 4)
        for rule in rules_ipv4:
            if rule['table'] == 10:
                self.assertEqual('192.168.0.1', rule['attrs']['FRA_SRC'])
                self.assertEqual(24, rule['src_len'])
                break
        else:
            self.fail('Rule added (192.168.0.1/24, table 10) not found')

    def test_list_default_rules_ipv6(self):
        rules_ipv6 = priv_ip_lib.list_ip_rules(self.namespace, 6)
        self.assertEqual(2, len(rules_ipv6))
        rule_tables = [255, 254]
        for rule in rules_ipv6:
            rule_tables.remove(rule['table'])
        self.assertEqual(0, len(rule_tables))

    def test_list_rules_ipv6(self):
        ip_lib.add_ip_rule(self.namespace, '2001:db8::1/64', table=20)
        rules_ipv6 = priv_ip_lib.list_ip_rules(self.namespace, 6)
        for rule in rules_ipv6:
            if rule['table'] == 20:
                self.assertEqual('2001:db8::1', rule['attrs']['FRA_SRC'])
                self.assertEqual(64, rule['src_len'])
                break
        else:
            self.fail('Rule added (2001:db8::1/64, table 20) not found')


class RuleTestCase(functional_base.BaseSudoTestCase):

    def setUp(self):
        super(RuleTestCase, self).setUp()
        self.namespace = 'ns_test-' + uuidutils.generate_uuid()
        self.ns = priv_ip_lib.create_netns(self.namespace)
        self.addCleanup(self._remove_ns)

    def _remove_ns(self):
        priv_ip_lib.remove_netns(self.namespace)

    def _check_rules(self, rules, parameters, values, exception_string=None,
                     raise_exception=True):
        for rule in rules:
            if all(rule.get(parameter) == value
                   for parameter, value in zip(parameters, values)):
                return True
        else:
            if raise_exception:
                self.fail('Rule with %s was expected' % exception_string)
            else:
                return False

    def test_add_rule_ip(self):
        ip_addresses = ['192.168.200.250', '2001::250']
        for ip_address in ip_addresses:
            ip_version = common_utils.get_ip_version(ip_address)
            ip_lenght = common_utils.get_network_length(ip_version)
            ip_family = common_utils.get_socket_address_family(ip_version)
            priv_ip_lib.add_ip_rule(self.namespace, src=ip_address,
                                    src_len=ip_lenght, family=ip_family)
            rules = ip_lib.list_ip_rules(self.namespace, ip_version)
            self._check_rules(rules, ['from'], [ip_address],
                              '"from" IP address %s' % ip_address)

            priv_ip_lib.delete_ip_rule(self.namespace, family=ip_family,
                                       src=ip_address, src_len=ip_lenght)
            rules = ip_lib.list_ip_rules(self.namespace, ip_version)
            self.assertFalse(
                self._check_rules(rules, ['from'], [ip_address],
                                  raise_exception=False))

    def test_add_rule_iif(self):
        iif = 'iif_device_1'
        priv_ip_lib.create_interface(iif, self.namespace, 'dummy')
        priv_ip_lib.add_ip_rule(self.namespace, iifname=iif)
        rules = ip_lib.list_ip_rules(self.namespace, 4)
        self._check_rules(rules, ['iif'], [iif], 'iif name %s' % iif)

        priv_ip_lib.delete_ip_rule(self.namespace, iifname=iif)
        rules = ip_lib.list_ip_rules(self.namespace, 4)
        self.assertFalse(
            self._check_rules(rules, ['iif'], [iif], raise_exception=False))

    def test_add_rule_table(self):
        table = 212
        ip_addresses = ['192.168.200.251', '2001::251']
        for ip_address in ip_addresses:
            ip_version = common_utils.get_ip_version(ip_address)
            ip_lenght = common_utils.get_network_length(ip_version)
            ip_family = common_utils.get_socket_address_family(ip_version)
            priv_ip_lib.add_ip_rule(self.namespace, table=table,
                                    src=ip_address, src_len=ip_lenght,
                                    family=ip_family)
            rules = ip_lib.list_ip_rules(self.namespace, ip_version)
            self._check_rules(
                rules, ['table', 'from'], [str(table), ip_address],
                'table %s and "from" IP address %s' % (table, ip_address))

            priv_ip_lib.delete_ip_rule(self.namespace, table=table,
                                       src=ip_address, src_len=ip_lenght,
                                       family=ip_family)
            rules = ip_lib.list_ip_rules(self.namespace, ip_version)
            self.assertFalse(
                self._check_rules(rules, ['table', 'from'],
                                  [str(table), ip_address],
                                  raise_exception=False))

    def test_add_rule_priority(self):
        priority = 12345
        ip_addresses = ['192.168.200.252', '2001::252']
        for ip_address in ip_addresses:
            ip_version = common_utils.get_ip_version(ip_address)
            ip_lenght = common_utils.get_network_length(ip_version)
            ip_family = common_utils.get_socket_address_family(ip_version)
            priv_ip_lib.add_ip_rule(self.namespace, priority=priority,
                                    src=ip_address, src_len=ip_lenght,
                                    family=ip_family)
            rules = ip_lib.list_ip_rules(self.namespace, ip_version)
            self._check_rules(
                rules, ['priority', 'from'], [str(priority), ip_address],
                'priority %s and "from" IP address %s' %
                (priority, ip_address))

            priv_ip_lib.delete_ip_rule(self.namespace, priority=priority,
                                       src=ip_address, src_len=ip_lenght,
                                       family=ip_family)
            rules = ip_lib.list_ip_rules(self.namespace, ip_version)
            self.assertFalse(
                self._check_rules(rules, ['priority', 'from'],
                                  [str(priority), ip_address],
                                  raise_exception=False))

    def test_add_rule_priority_table_iif(self):
        table = 213
        priority = 12346
        iif = 'iif_device_2'
        priv_ip_lib.create_interface(iif, self.namespace, 'dummy')
        priv_ip_lib.add_ip_rule(self.namespace, priority=priority, iifname=iif,
                                table=table)

        rules = ip_lib.list_ip_rules(self.namespace, 4)
        self._check_rules(
            rules, ['priority', 'iif', 'table'],
            [str(priority), iif, str(table)],
            'priority %s, table %s and iif name %s' % (priority, table, iif))

        priv_ip_lib.delete_ip_rule(self.namespace, priority=priority,
                                   iifname=iif, table=table)
        rules = ip_lib.list_ip_rules(self.namespace, 4)
        self.assertFalse(
            self._check_rules(rules, ['priority', 'iif', 'table'],
                              [str(priority), iif, str(table)],
                              raise_exception=False))

    @testtools.skip('https://github.com/svinota/pyroute2/issues/566')
    def test_add_rule_exists(self):
        iif = 'iif_device_1'
        priv_ip_lib.create_interface(iif, self.namespace, 'dummy')
        priv_ip_lib.add_ip_rule(self.namespace, iifname=iif)
        rules = ip_lib.list_ip_rules(self.namespace, 4)
        self._check_rules(rules, ['iif'], [iif], 'iif name %s' % iif)
        self.assertEqual(4, len(rules))

        # pyroute2.netlink.exceptions.NetlinkError(17, 'File exists')
        # exception is catch.
        priv_ip_lib.add_ip_rule(self.namespace, iifname=iif)
        rules = ip_lib.list_ip_rules(self.namespace, 4)
        self._check_rules(rules, ['iif'], [iif], 'iif name %s' % iif)
        self.assertEqual(4, len(rules))


class GetIpAddressesTestCase(functional_base.BaseSudoTestCase):

    def _remove_ns(self, namespace):
        priv_ip_lib.remove_netns(namespace)

    def test_get_ip_addresses(self):
        namespace = 'ns_test-' + uuidutils.generate_uuid()
        priv_ip_lib.create_netns(namespace)
        self.addCleanup(self._remove_ns, namespace)
        interfaces = {
            '20': {'cidr': '192.168.10.20/24', 'scope': 'link',
                   'add_broadcast': True},
            '30': {'cidr': '2001::1/64', 'scope': 'global',
                   'add_broadcast': False}}

        for int_name, int_parameters in interfaces.items():
            priv_ip_lib.create_interface(int_name, namespace, 'dummy',
                                         index=int(int_name))
            ip_lib.add_ip_address(
                int_parameters['cidr'], int_name, namespace,
                int_parameters['scope'], int_parameters['add_broadcast'])

        ip_addresses = priv_ip_lib.get_ip_addresses(namespace)
        for ip_address in ip_addresses:
            int_name = str(ip_address['index'])
            ip = _get_attr(ip_address, 'IFA_ADDRESS')
            mask = ip_address['prefixlen']
            cidr = common_utils.ip_to_cidr(ip, mask)
            self.assertEqual(interfaces[int_name]['cidr'], cidr)
            self.assertEqual(interfaces[int_name]['scope'],
                             ip_lib.IP_ADDRESS_SCOPE[ip_address['scope']])
