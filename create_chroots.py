import argparse
import os
import subprocess
import shutil
import time

import jinja2


def run_command(command):
    print command
    command = command.split()
    subp = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    out, err = subp.communicate()
    if out:
        print out
    if err:
        print err


def ns_ips(ns_ip_prefix, ns_count):
    return ['%s.%d' % (ns_ip_prefix, i + 1) for i in xrange(ns_count)]


def clean_existing_directories():
    if os.path.exists('chroots'):
        shutil.rmtree('chroots')


def build_dirs(chroot_name):
    os.makedirs(os.path.join('chroots', chroot_name))
    os.makedirs(os.path.join('chroots', chroot_name, 'var/named/zones'))
    os.makedirs(os.path.join('chroots', chroot_name, 'var/log'))


def build_chroot(env, args, chroot_dir, ns_ip, master_ips=None):
    build_dirs(chroot_dir)
    ns_type = 'master' if master_ips is None else 'slave'
    named9_conf_template = env.get_template('named9.conf')
    with open('chroots/%s/var/named/named9.conf' % chroot_dir, 'w') as fh:
        fh.write(named9_conf_template.render(
            ns_type=ns_type,
            zones=xrange(args.zones),
            ns_ip=ns_ip,
            master_ips=master_ips
        ))
    if ns_type == 'master':
        zone_template = env.get_template('zone_template')
        for zone_no in xrange(args.zones):
            path = 'chroots/master/var/named/zones/zone%d.com.zone'
            with open(path % zone_no, 'w') as fh:
                fh.write(zone_template.render(
                    zone_no=zone_no,
                    refresh=args.refresh,
                    retry=args.retry,
                    expire=args.expire,
                    negative_ttl=args.negative_ttl,
                    master_ip=args.master_ip,
                    xfr_ips=ns_ips(args.xfr_ip_prefix, args.xfr_count),
                    resolver_ips=ns_ips(args.resolver_ip_prefix,
                                        args.resolver_count),
                ))


def build_all_chroots(env, args):
    build_chroot(env, args, 'master', args.master_ip)
    xfr_ips = ns_ips(args.xfr_ip_prefix, args.xfr_count)
    resolver_ips = ns_ips(args.resolver_ip_prefix, args.resolver_count)
    for index, ns_ip in enumerate(xfr_ips):
        build_chroot(env, args, 'xfr%d' % index, ns_ip, [args.master_ip])
    for index, ns_ip in enumerate(resolver_ips):
        build_chroot(
            env, args, 'resolver%d' % index,
            ns_ip,
            ns_ips(args.xfr_ip_prefix, args.xfr_count)
        )


def kill_running_nameservers():
    run_command('killall named')


def configure_ips(args):
    master_ip = args.master_ip
    xfr_ips = ns_ips(args.xfr_ip_prefix, args.xfr_count)
    resolver_ips = ns_ips(args.resolver_ip_prefix, args.resolver_count)
    for index, ip in enumerate([master_ip] + xfr_ips + resolver_ips):
        run_command('ifconfig lo:%d %s' % (index, ip))


def start_nameservers(ns_path):
    for chroot in os.listdir('chroots'):
        run_command(
            '%s -t chroots/%s -c /var/named/named9.conf' % (ns_path, chroot)
        )

def main():
    parser = argparse.ArgumentParser(description='Generate bind9 chroots')
    parser.add_argument('--zones', type=int, default=1)
    parser.add_argument('--master-ip', default='127.1.1.1')
    parser.add_argument('--xfr-ip-prefix', default='127.2.2')
    parser.add_argument('--resolver-ip-prefix', default='127.3.3')

    parser.add_argument('--xfr-count', type=int, default=2)
    parser.add_argument('--resolver-count', type=int, default=1)

    parser.add_argument('--refresh', type=int, default=60)
    parser.add_argument('--retry', type=int, default=30)
    parser.add_argument('--expire', type=int, default=300)
    parser.add_argument('--negative_ttl', type=int, default=5)

    parser.add_argument('--ns-path')

    args = parser.parse_args()

    loader = jinja2.FileSystemLoader('templates')
    env = jinja2.Environment(loader=loader)

    clean_existing_directories()
    build_all_chroots(env, args)
    if args.ns_path is not None:
        kill_running_nameservers()
        time.sleep(5)  # TODO: check that they actually stopped
        configure_ips(args)
        start_nameservers(args.ns_path)


if __name__ == '__main__':
    main()
