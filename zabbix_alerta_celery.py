#!/usr/bin/env python
"""
  zabbix-alerta-celery: Forward Zabbix events to Alerta via celery
"""

import os
import sys
import argparse
import logging as LOG
from pyzabbix import ZabbixAPI

try:
  import configparser
except ImportError:
  import ConfigParser as configparser

from alertaclient.api import Client
from zabbix_celery import send2celery

__version__ = '0.0.1'

LOG_FILE = '/var/log/zabbix/zabbix_alerta_celery.log'
LOG_FORMAT = "%(asctime)s.%(msecs).03d %(name)s[%(process)d] %(threadName)s %(levelname)s - %(message)s"
LOG_DATE_FMT = "%Y-%m-%d %H:%M:%S"

OPTIONS = {
  'config_file': '~/.alerta.conf',
  'profile':   None,
  'endpoint':  'http://localhost:8080',
  'key':     '',
  'sslverify':  True,
  'debug':    False
}

ZBX_SEVERITY_MAP = {
  'Disaster':    'critical',
  'High':      'major',
  'Average':    'minor',
  'Warning':    'warning',
  'Information':  'informational',
  'Not classified': 'indeterminate'
}

epilog = '''INSTALL

  $ ln -s `which zabbix-alerta` <AlertScriptsPath>

ALERT FORMAT

OPERATIONS

Default subject:
{TRIGGER.STATUS}: {TRIGGER.NAME}

Default message:
resource={HOST.NAME1}
event={ITEM.KEY1}
environment=Production
severity={TRIGGER.SEVERITY}!!
status={TRIGGER.STATUS}
ack={EVENT.ACK.STATUS}
service={TRIGGER.HOSTGROUP.NAME}
group=Zabbix
value={ITEM.VALUE1}
text={TRIGGER.STATUS}: {TRIGGER.NAME}
tags={EVENT.TAGS}
attributes.ip={HOST.IP1}
attributes.thresholdInfo={TRIGGER.TEMPLATE.NAME}: {TRIGGER.EXPRESSION}
attributes.moreInfo=<a href="http://x.x.x.x/tr_events.php?triggerid={TRIGGER.ID}&eventid={EVENT.ID}">Zabbix console</a>
type=zabbixAlert
dateTime={EVENT.DATE}T{EVENT.TIME}Z

RECOVERY

Default subject:
{TRIGGER.STATUS}: {TRIGGER.NAME}

Default message:
resource={HOST.NAME1}
event={ITEM.KEY1}
environment=Production
severity={TRIGGER.SEVERITY}!!
status={TRIGGER.STATUS}
ack={EVENT.ACK.STATUS}
service={TRIGGER.HOSTGROUP.NAME}
group=Zabbix
value={ITEM.VALUE1}
text={TRIGGER.STATUS}: {ITEM.NAME1}
tags={EVENT.RECOVERY.TAGS}
attributes.ip={HOST.IP1}
attributes.thresholdInfo={TRIGGER.TEMPLATE.NAME}: {TRIGGER.EXPRESSION}
attributes.moreInfo=<a href="http://x.x.x.x/tr_events.php?triggerid={TRIGGER.ID}&eventid={EVENT.RECOVERY.ID}">Zabbix console</a>
type=zabbixAlert
dateTime={EVENT.RECOVERY.DATE}T{EVENT.RECOVERY.TIME}Z



'''

# FIXME - use {ITEM.APPLICATION} for alert "group" when ZBXNEXT-2684 is resolved (see https://support.zabbix.com/browse/ZBXNEXT-2684)


def parse_zabbix(subject, message):

  alert = {}
  attributes = {}
  zabbix_severity = False
  for line in message.split('\n'):
    if '=' not in line:
      continue
    try:
      macro, value = line.rstrip().split('=', 1)
    except ValueError as e:
      LOG.warning('%s: %s', e, line)
      continue

    if macro == 'service':
      value = value.split(', ')
    elif macro == 'severity':
      if value.endswith('!!'):
        zabbix_severity = True
        value = value.replace('!!','')
      else:
        value = ZBX_SEVERITY_MAP.get(value, 'indeterminate')
    elif macro == 'tags':
      value = value.split(', ')
    elif macro.startswith('attributes.'):
      attributes[macro.replace('attributes.', '')] = value

    alert[macro] = value
    LOG.debug('%s -> %s', macro, value)

  # if {$ENVIRONMENT} user macro isn't defined anywhere set default
  if alert.get('environment', '') == '{$ENVIRONMENT}':
    alert['environment'] = 'Production'

  zabbix_status = alert.pop('status', None)

  if zabbix_status == 'OK':
    if zabbix_severity:
      alert['severity'] = 'OK'
    else:
      alert['severity'] = 'normal'

  if alert.pop('ack', '') == 'Yes' and zabbix_status != 'OK':
    alert['status'] = 'ack'

  alert['attributes'] = attributes
  alert['origin'] = "zabbix/%s" % os.uname()[1]
  alert['rawData'] = "%s\n\n%s" % (subject, message)

  return alert


def main():
  config_file = os.environ.get('ALERTA_CONF_FILE') or OPTIONS['config_file']

  config = configparser.RawConfigParser(defaults=OPTIONS)
  try:
    config.read(os.path.expanduser(config_file))
  except Exception:
    sys.exit("Problem reading configuration file %s - is this an ini file?" % config_file)

  parser = argparse.ArgumentParser(
    prog='zabbix-alerta-celery',
    usage='zabbix-alerta-celery SENDTO SUMMARY BODY',
    description='Zabbix-to-Alerta via celery integration script',
    epilog=epilog,
    formatter_class=argparse.RawTextHelpFormatter
  )
  parser.add_argument(
    'sendto',
    help='config profile or alerta API endpoint and key'
  )
  parser.add_argument(
    'summary',
    help='alert summary'
  )
  parser.add_argument(
    'zbxuser',
    help='zabbix user'
  )
  parser.add_argument(
    'zbxpassword',
    help='zabbix password'
  )
  parser.add_argument(
    'zbxurl',
    help='zabbix url'
  )  
  parser.add_argument(
    'body',
    help='alert body (see format below)'
  )
  args, left = parser.parse_known_args()

  # sendto=apiUrl[;key]
  if args.sendto.startswith('http://') or args.sendto.startswith('https://'):
    want_profile = None
    try:
      OPTIONS['endpoint'], OPTIONS['key'] = args.sendto.split(';', 1)
    except ValueError:
      OPTIONS['endpoint'] = args.sendto
  # sendto=profile
  else:
    want_profile = args.sendto or os.environ.get('ALERTA_DEFAULT_PROFILE') or config.defaults().get('profile')

    if want_profile and config.has_section('profile %s' % want_profile):
      for opt in OPTIONS:
        try:
          OPTIONS[opt] = config.getboolean('profile %s' % want_profile, opt)
        except (ValueError, AttributeError):
          OPTIONS[opt] = config.get('profile %s' % want_profile, opt)
    else:
      for opt in OPTIONS:
        try:
          OPTIONS[opt] = config.getboolean('DEFAULT', opt)
        except (ValueError, AttributeError):
          OPTIONS[opt] = config.get('DEFAULT', opt)

  parser.set_defaults(**OPTIONS)
  args = parser.parse_args()

  if args.debug or not os.path.isdir('/var/log/zabbix'):
    LOG.basicConfig(stream=sys.stderr, format=LOG_FORMAT, datefmt=LOG_DATE_FMT, level=LOG.DEBUG)
  else:
    LOG.basicConfig(filename=LOG_FILE, format=LOG_FORMAT, datefmt=LOG_DATE_FMT, level=LOG.INFO)

  LOG.info("[alerta] endpoint=%s key=%s sendto=%s, summary=%s, body=%s", args.endpoint, args.key, args.sendto, args.summary, args.body)
  try:
    # log = LOG.getLogger('pyzabbix')
    # log.setLevel(LOG.DEBUG)
    alert = parse_zabbix(args.summary, args.body)
    zapi = ZabbixAPI(args.zbxurl)
    zapi.session.verify = False
    zapi.timeout = 300
    zapi.login(args.zbxuser, args.zbxpassword)
    trigger = zapi.trigger.get(triggerids=alert['triggerId'], selectFunctions="extend", expandExpression=True)
    hostId = None
    items = {}
    for item in zapi.item.get(itemids=[item['itemid'] for item in trigger[0]['functions']]):
      hostId = item['hostid']
      items[item['key_']]=item['itemid']
    alert['event'] = "_".join(sorted(items.keys()))
    if alert['severity'] == 'OK':
      num2Severity = {
        '0':'Not classified',
        '1':'Information',
        '2':'Warning',
        '3':'Average',
        '4':'High',
        '5':'Disaster'
      }
      trigger = zapi.trigger.get(monitored=True, hostids=hostId, itemids=[items[key] for key in items.keys()],expandExpression=True, filter={'value':1}, sortfield="priority", sortorder="DESC", limit=1)
      if len(trigger) > 0:
        foundAll = True
        for item in items:
          if item not in trigger[0]['expression']:
            foundAll = False
            break
        if foundAll:
          alert['severity'] = num2Severity[trigger[0]['priority']]
    # LOG.info("Sending to celery")
    send2celery.apply_async(args = [args.endpoint, args.key, args.sslverify, alert], queue='zabbix_celery')
  except (SystemExit, KeyboardInterrupt):
    LOG.warning("Exiting zabbix-alerta.")
    sys.exit(0)
  except Exception as e:
    LOG.error(e, exc_info=1)
    sys.exit(1)

if __name__ == '__main__':
  main()
