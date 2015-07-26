import argparse
import logging
import os
import subprocess
import shutil
import time

import jinja2


ENV = jinja2.Environment(loader=jinja2.FileSystemLoader('templates'))


class Nameserver(object):
    def __init__(self, name, ip, is_recursive, use_chroot):
        self.name = name
        self.ip = ip
        self.is_recursive = is_recursive
        self.use_chroot = use_chroot
        self.zones = []

    @property
    def base_dir(self):
        if self.use_chroot:
            return ''
        return os.path.join(os.getcwd(), 'chroots', self.name)

    def render_named9_conf(self):
        named9_conf_template = ENV.get_template('named9.conf')
        return named9_conf_template.render(ns=self)

    def build_dirs(self):
        os.makedirs(os.path.join('chroots', self.name))
        os.makedirs(os.path.join('chroots', self.name, 'var/named/zones'))
        os.makedirs(os.path.join('chroots', self.name, 'var/log'))

    def build_chroot(self):
        logging.info('Building %s', self.name)
        self.build_dirs()
        with open('chroots/%s/var/named/named9.conf' % self.name, 'w') as fh:
            fh.write(self.render_named9_conf())
        for zone in self.zones:
            zone.write_zonefile(self.name)


class MasterZone(object):
    def __init__(self, name, auth_nameservers,
                 refresh, retry, expire, negative_ttl,
                 record_count):
        self.name = name
        self.auth_nameservers = auth_nameservers
        self.refresh = refresh
        self.retry = retry
        self.expire = expire
        self.negative_ttl = negative_ttl
        self.test_records = ['test%d' % i for i in xrange(record_count)]

    @property
    def type(self):
        return 'master'

    @property
    def is_slave(self):
        return False

    def write_zonefile(self, ns_name):
        zone_template = ENV.get_template('zone_template')
        file_path = 'chroots/%s/var/named/zones/%s.zone' % (ns_name, self.name)
        with open(file_path, 'w') as fh:
            fh.write(zone_template.render(zone=self))


class SlaveZone(object):
    def __init__(self, name, master_ips):
        self.name = name
        self.master_ips = master_ips

    @property
    def type(self):
        return 'slave'

    @property
    def is_slave(self):
        return True

    def write_zonefile(self, ns_name):
        pass


class StubZone(SlaveZone):
    @property
    def type(self):
        return 'stub'


def run_command(command, stop_on_failure=True):
    logging.debug('Running command: %s', command)
    command = command.split()
    try:
        output = subprocess.check_output(
            command,
            stderr=subprocess.STDOUT
        )
    except subprocess.CalledProcessError as e:
        logging.error(e.output)
        if stop_on_failure:
            raise
    else:
        if output:
            logging.debug('Command output: %s', output)


def ns_ips(ns_ip_prefix, ns_count):
    return ['%s.%d' % (ns_ip_prefix, i + 1) for i in xrange(ns_count)]


def clean_existing_directories():
    logging.info('Removing existing chroots')
    if os.path.exists('chroots'):
        shutil.rmtree('chroots')


def kill_running_nameservers():
    run_command('killall named', stop_on_failure=False)


def configure_ips(nameservers):
    logging.info('Configuring ips')
    for i, ns in enumerate(nameservers):
        run_command('ifconfig lo:%d %s' % (i, ns.ip))


def start_nameservers(ns_path, use_chroots):
    logging.info('Starting nameservers')
    for chroot in os.listdir('chroots'):
        if use_chroots:
            run_command(
                '%s -t chroots/%s -c /var/named/named9.conf' % (
                    ns_path, chroot))
        else:
            conf_path = os.path.join(os.getcwd(), 'chroots', chroot,
                                     'var/named/named9.conf')
            run_command('%s -c %s' % (ns_path, conf_path))


def nsupdate_loop(nsupdate_path, update_interval,
                  master_ns, zones):
    current_value = 1

    while True:
        nsupdate_template = ENV.get_template('nsupdate')
        logging.info('Updating test TXT record from %d to %d',
                     current_value, current_value + 1)
        for zone in zones:
            nsupdate_statements = nsupdate_template.render(
                master_ip=master_ns.ip,
                old_value=current_value,
                new_value=current_value + 1,
                zone=zone
            ).replace('\n\n', '\n')
            with open('/tmp/nsupdate_statements', 'w') as fh:
                fh.write(nsupdate_statements)
            run_command('%s /tmp/nsupdate_statements' % nsupdate_path)
        current_value += 1
        time.sleep(update_interval)


def main():
    parser = argparse.ArgumentParser(description='Generate bind9 chroots')
    parser.add_argument('--zone-count', type=int, default=2)
    parser.add_argument('--master-ip', default='127.1.1.1')
    parser.add_argument('--xfr-ip-prefix', default='127.2.2')
    parser.add_argument('--resolver-ip-prefix', default='127.3.3')

    parser.add_argument('--xfr-count', type=int, default=2)
    parser.add_argument('--resolver-count', type=int, default=1)

    parser.add_argument('--subdomain-resolver-count', type=int, default=0)
    parser.add_argument('--subdomain-resolver-ip-prefix', default='127.4.4')

    parser.add_argument('--refresh', type=int, default=60)
    parser.add_argument('--retry', type=int, default=30)
    parser.add_argument('--expire', type=int, default=300)
    parser.add_argument('--negative_ttl', type=int, default=5)
    parser.add_argument('--record-count', type=int, default=1000)

    parser.add_argument('--ns-path')

    parser.add_argument('--nsupdate-path')
    parser.add_argument('--nsupdate-interval', type=int, default=1)

    parser.add_argument('--no-chroots', action='store_true', default=False)
    parser.add_argument('--debug', action='store_true', default=False)

    args = parser.parse_args()

    if args.zone_count < 1:
        raise ValueError('At least one zone needs to be configured')
    if args.record_count < 1:
        raise ValueError('At least one test record needs to be configured')

    logging.basicConfig(
        format='%(asctime)s %(levelname)s: %(message)s',
        level=logging.DEBUG if args.debug else logging.INFO
    )

    use_chroot = not args.no_chroots

    master_ns = Nameserver(
        name='master',
        ip=args.master_ip,
        is_recursive=False,
        use_chroot=use_chroot)
    xfrs = [
        Nameserver(
            name='xfr%d' % i,
            ip='%s.%d' % (args.xfr_ip_prefix, i + 1),
            is_recursive=False,
            use_chroot=use_chroot)
        for i in xrange(args.xfr_count)]
    resolvers = [
        Nameserver(
            name='resolver%d' % i,
            ip='%s.%d' % (args.resolver_ip_prefix, i + 1),
            is_recursive=False,
            use_chroot=use_chroot)
        for i in xrange(args.resolver_count)]
    auth_nameservers = [master_ns] + xfrs + resolvers

    master_zones = [
        MasterZone('zone%d.com' % i,
                   auth_nameservers=auth_nameservers,
                   refresh=args.refresh,
                   retry=args.retry,
                   expire=args.expire,
                   negative_ttl=args.negative_ttl,
                   record_count=args.record_count)
        for i in xrange(args.zone_count)]
    master_ns.zones = master_zones

    xfr_zones = [
        SlaveZone('zone%d.com' % i, master_ips=[master_ns.ip])
        for i in xrange(args.zone_count)]
    for xfr in xfrs:
        xfr.zones = xfr_zones

    resolver_zones = [
        SlaveZone('zone%d.com' % i, master_ips=[xfr.ip for xfr in xfrs])
        for i in xrange(args.zone_count)]
    for resolver in resolvers:
        resolver.zones = resolver_zones

    if args.subdomain_resolver_count > 0:
        subdomain_resolvers = [
            Nameserver(
                name='sub%d' % i,
                ip='%s.%d' % (args.subdomain_resolver_ip_prefix, i + 1),
                is_recursive=False,
                use_chroot=use_chroot)
            for i in xrange(args.subdomain_resolver_count)]

        master_subdomain_zones = [
            MasterZone('sub.zone%d.com' % i,
                       auth_nameservers=subdomain_resolvers,
                       refresh=args.refresh,
                       retry=args.retry,
                       expire=args.expire,
                       negative_ttl=args.negative_ttl,
                       record_count=args.record_count)
            for i in xrange(args.zone_count)]
        for resolver in subdomain_resolvers:
            resolver.zones = master_subdomain_zones

        subdomain_stubs = [
            StubZone('sub.zone%d.com' % i,
                     master_ips=[ns.ip for ns in subdomain_resolvers])
            for i in xrange(args.zone_count)]

        for resolver in resolvers:
            resolver.zones.extend(subdomain_stubs)
    else:
        subdomain_resolvers = []

    clean_existing_directories()

    for ns in [master_ns] + xfrs + resolvers + subdomain_resolvers:
        ns.build_chroot()

    if args.ns_path is not None:
        kill_running_nameservers()
        time.sleep(5)  # TODO: check that they actually stopped
        configure_ips([master_ns] + xfrs + resolvers + subdomain_resolvers)
        start_nameservers(args.ns_path, not args.no_chroots)

    if args.nsupdate_path is not None:
        nsupdate_loop(args.nsupdate_path, args.nsupdate_interval,
                      master_ns, master_zones)


if __name__ == '__main__':
    main()
