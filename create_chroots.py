import argparse
import os
import shutil

import jinja2


def clean_existing_directories():
    if os.path.exists('chroots'):
        shutil.rmtree('chroots')


def build_dirs(chroot_name):
    os.makedirs(os.path.join('chroots', chroot_name))
    os.makedirs(os.path.join('chroots', chroot_name, 'var/named/zones'))
    os.makedirs(os.path.join('chroots', chroot_name, 'var/log'))


def build_master_chroot(env, args):
    build_dirs('master')
    named9_conf_template = env.get_template('named9.conf')
    with open('chroots/master/var/named/named9.conf', 'w') as fh:
        fh.write(named9_conf_template.render(
            zone_type='master',
            zones=xrange(args.zones),
            listen_on=args.master_ip,
        ))
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
                xfrs=xrange(args.xfr_count),
                xfr_ip_prefix=args.xfr_ip_prefix,
                resolvers=xrange(args.resolver_count),
                resolver_ip_prefix=args.resolver_ip_prefix)
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

    args = parser.parse_args()

    loader = jinja2.FileSystemLoader('templates')
    env = jinja2.Environment(loader=loader)

    clean_existing_directories()
    build_master_chroot(env, args)


if __name__ == '__main__':
    main()
