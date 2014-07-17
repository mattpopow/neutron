# Copyright (c) 2014 Cisco Systems Inc.
# All Rights Reserved.
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
#
# @author: Arvind Somya (asomya@cisco.com), Cisco Systems Inc.

import netaddr

from oslo.config import cfg

from neutron.common import constants as n_constants
from neutron.extensions import portbindings
from neutron.openstack.common import log
from neutron.plugins.common import constants
from neutron.plugins.ml2 import driver_api as api

from neutron.plugins.ml2.drivers.cisco.apic import apic_manager
from neutron.plugins.ml2.drivers.cisco.apic import apic_mapper
from neutron.plugins.ml2.drivers.cisco.apic import apic_sync
from neutron.plugins.ml2.drivers.cisco.apic import config


LOG = log.getLogger(__name__)


class APICMechanismDriver(api.MechanismDriver):

    @staticmethod
    def get_apic_manager():
        apic_config = cfg.CONF.ml2_cisco_apic
        network_config = {
            'vlan_ranges': cfg.CONF.ml2_type_vlan.network_vlan_ranges,
            'switch_dict': config.switch_dictionary(),
            'external_network_dict': config.external_network_dictionary(),
        }
        apic_system_id = cfg.CONF.apic_system_id
        return apic_manager.APICManager(apic_config, network_config,
                                        apic_system_id)

    @staticmethod
    def get_apic_name_mapper(apic_manager):
        apic_config = cfg.CONF.ml2_cisco_apic
        return apic_mapper.APICNameMapper(
            apic_manager.db, apic_config.apic_name_mapping)

    @staticmethod
    def get_base_synchronizer(inst):
        apic_config = cfg.CONF.ml2_cisco_apic
        return apic_sync.ApicBaseSynchronizer(inst,
                                              apic_config.apic_sync_interval)

    @staticmethod
    def get_router_synchronizer(inst):
        apic_config = cfg.CONF.ml2_cisco_apic
        return apic_sync.ApicRouterSynchronizer(inst,
                                                apic_config.apic_sync_interval)

    def initialize(self):
        # initialize apic
        self.apic_manager = APICMechanismDriver.get_apic_manager()
        self.name_mapper = APICMechanismDriver.get_apic_name_mapper(
            self.apic_manager)
        self.synchronizer = None
        self.apic_manager.ensure_infra_created_on_apic()
        self.apic_manager.ensure_bgp_pod_policy_created_on_apic()

    def sync_init(f):
        def inner(inst, *args, **kwargs):
            if not inst.synchronizer:
                inst.synchronizer = \
                    APICMechanismDriver.get_base_synchronizer(inst)
                inst.synchronizer.sync_base()
            return f(inst, *args, **kwargs)
        return inner

    def _perform_port_operations(self, context):
        # Get port
        port = context.current
        # Check if a compute port
        if port.get('device_owner', '').startswith('compute'):
            self._perform_path_port_operations(context, port)
        elif port.get('device_owner') == n_constants.DEVICE_OWNER_ROUTER_GW:
            self._perform_gw_port_operations(context, port)
        elif port.get('device_owner') == n_constants.DEVICE_OWNER_DHCP:
            self._perform_path_port_operations(context, port)

    def _perform_path_port_operations(self, context, port):
        # Get network
        network_id = context.network.current['id']
        anetwork_id = self.name_mapper.network(context, network_id)
        # Get tenant details from port context
        tenant_id = context.current['tenant_id']
        tenant_id = self.name_mapper.tenant(context, tenant_id)
        # Get segmentation id
        if not context.bound_segment:
            LOG.debug(("Port %s is not bound to a segment"), port)
            return
        seg = None
        if (context.bound_segment.get(api.NETWORK_TYPE)
                in [constants.TYPE_VLAN]):
            seg = context.bound_segment.get(api.SEGMENTATION_ID)
        # hosts on which this vlan is provisioned
        host = port.get(portbindings.HOST_ID)
        # Create a static path attachment for the host/epg/switchport combo
        with self.apic_manager.apic.transaction() as trs:
            self.apic_manager.ensure_path_created_for_port(
                tenant_id, anetwork_id, host, seg, transaction=trs)

    def _perform_gw_port_operations(self, context, port):
        router_id = port.get('device_id')
        network = context.network.current
        anetwork_id = self.name_mapper.network(context, network['id'])
        router_info = self.apic_manager.ext_net_dict.get(network['name'])

        if router_id and router_info:
            address = router_info['cidr_exposed']
            next_hop = router_info['gateway_ip']
            encap = router_info.get('encap')  # No encap if None
            switch = router_info['switch']
            module, sport = router_info['port'].split('/')
            with self.apic_manager.apic.transaction() as trs:
                # Get/Create contract
                arouter_id = self.name_mapper.router(context, router_id)
                cid = self.apic_manager.get_router_contract(arouter_id)
                # Ensure that the external ctx exists
                self.apic_manager.ensure_context_enforced()
                # Create External Routed Network and configure it
                self.apic_manager.ensure_external_routed_network_created(
                    anetwork_id, transaction=trs)
                self.apic_manager.ensure_logical_node_profile_created(
                    anetwork_id, switch, module, sport, encap,
                    address, transaction=trs)
                self.apic_manager.ensure_static_route_created(
                    anetwork_id, switch, next_hop, transaction=trs)
                self.apic_manager.ensure_external_epg_created(
                    anetwork_id, transaction=trs)
                self.apic_manager.ensure_external_epg_consumed_contract(
                    anetwork_id, cid, transaction=trs)
                self.apic_manager.ensure_external_epg_provided_contract(
                    anetwork_id, cid, transaction=trs)

    def _delete_contract_if_gateway(self, context):
        port = context.current
        if port.get('device_owner') == n_constants.DEVICE_OWNER_ROUTER_GW:
            network_id = self.name_mapper.network(
                context, context.network.current['id'])
            arouter_id = self.name_mapper.router(context,
                                                 port.get('device_id'))
            self.apic_manager.delete_external_epg_contract(arouter_id,
                                                           network_id)

    @sync_init
    def create_port_postcommit(self, context):
        self._perform_port_operations(context)

    @sync_init
    def update_port_postcommit(self, context):
        self._perform_port_operations(context)

    @sync_init
    def delete_port_postcommit(self, context):
        self._delete_contract_if_gateway(context)

    @sync_init
    def create_network_postcommit(self, context):
        if not context.current.get('router:external'):
            tenant_id = context.current['tenant_id']
            network_id = context.current['id']

            # Convert to APIC IDs
            tenant_id = self.name_mapper.tenant(context, tenant_id)
            network_id = self.name_mapper.network(context, network_id)

            # Create BD and EPG for this network
            with self.apic_manager.apic.transaction() as trs:
                self.apic_manager.ensure_bd_created_on_apic(tenant_id,
                                                            network_id,
                                                            transaction=trs)
                self.apic_manager.ensure_epg_created_for_network(
                    tenant_id, network_id, transaction=trs)

    @sync_init
    def update_network_postcommit(self, context):
        super(APICMechanismDriver, self).update_network_postcommit(context)

    @sync_init
    def delete_network_postcommit(self, context):
        if not context.current.get('router:external'):
            tenant_id = context.current['tenant_id']
            network_id = context.current['id']

            # Convert to APIC IDs
            tenant_id = self.name_mapper.tenant(context, tenant_id)
            network_id = self.name_mapper.network(context, network_id)

            # Delete BD and EPG for this network
            with self.apic_manager.apic.transaction() as trs:
                self.apic_manager.delete_epg_for_network(tenant_id, network_id,
                                                         transaction=trs)
                self.apic_manager.delete_bd_on_apic(tenant_id, network_id,
                                                    transaction=trs)
        else:
            network_name = context.current['name']
            if self.apic_manager.ext_net_dict.get(network_name):
                network_id = self.name_mapper.network(context,
                                                      context.current['id'])
                self.apic_manager.delete_external_routed_network(network_id)

    @sync_init
    def create_subnet_postcommit(self, context):
        tenant_id = context.current['tenant_id']
        network_id = context.current['network_id']
        network = context._plugin.get_network(context._plugin_context,
                                              network_id)
        if not network.get('router:external'):
            gateway_ip = context.current['gateway_ip']
            cidr = netaddr.IPNetwork(context.current['cidr'])
            netmask = str(cidr.prefixlen)
            gateway_ip = gateway_ip + '/' + netmask

            # Convert to APIC IDs
            tenant_id = self.name_mapper.tenant(context, tenant_id)
            network_id = self.name_mapper.network(context, network_id)

            # Create subnet on BD
            self.apic_manager.ensure_subnet_created_on_apic(
                tenant_id, network_id, gateway_ip)

    @sync_init
    def update_subnet_postcommit(self, context):
        super(APICMechanismDriver, self).update_subnet_postcommit(context)

    @sync_init
    def delete_subnet_postcommit(self, context):
        tenant_id = context.current['tenant_id']
        network_id = context.current['network_id']
        network = context._plugin.get_network(context._plugin_context,
                                              network_id)
        if not network.get('router:external'):
            gateway_ip = context.current['gateway_ip']
            cidr = netaddr.IPNetwork(context.current['cidr'])
            netmask = str(cidr.prefixlen)
            gateway_ip = gateway_ip + '/' + netmask

            # Convert to APIC IDs
            tenant_id = self.name_mapper.tenant(context, tenant_id)
            network_id = self.name_mapper.network(context, network_id)

            # Create subnet on BD
            self.apic_manager.ensure_subnet_deleted_on_apic(
                tenant_id, network_id, gateway_ip)
