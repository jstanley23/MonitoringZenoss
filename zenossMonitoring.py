#!/opt/zenoss/bin/python
import os
import sys
import json
import time
import argparse
import requests


scriptVersion = "1.0.0"
scriptSummary = " script for monitoring event handling in Zenoss. "
documentationURL = "http://wiki.zenoss.org/Monitoring_Zenoss"

# Zenoss Instance information
# This can be removed and the class can be called with args
_ZENOSS_INSTANCE = 'http://10.10.10.10:8080'
_ZENOSS_USERNAME = 'svc_monitoring'
_ZENOSS_PASSWORD = 'supersecure'
_ZENOSS_TIMEOUT = 10

# RabbitMQ (AMQP) information
_RABBIT_HOST = '10.10.10.10'
_RABBIT_PORT = '5672'
_RABBIT_USERNAME = 'zenoss'
_RABBIT_PASSWORD = 'zenoss'
_RABBIT_VHOST = '/zenoss'
_RABBIT_SSL = False

# A dict() with queues to monitor and their threshold
_QUEUES = {
    'zenoss.queues.zep.rawevents': 500,
    'zenoss.queues.zep.zenevents': 200,
    'zenoss.queues.zep.signal': 100,
    }

# Max number of times to try verifying event state
_RETRY = 20
# Sometimes there is a small delay in the event action and the check loops
# cycle too quickly. The sleep is to slow them down a bit.
_SLEEP = 0.1

# Device for event
_ZENOSS_RM = 'localhost'
# Event summary to be used. We make this unique for searches.
_MSG = 'Synthetic Zenoss event check ({})'
# When checking a pre-existing event the severity
# must be Warning or higher or event will age.
_SEVERITY = 'Critical'
# Transform
_TRANSFORM = '''
Under Event Class /App/Zenoss, add the following transform:
if hasattr(evt, 'device') and hasattr(evt, 'component'):
    if (evt.device == 'localhost' and
            evt.component == 'zenossMonitoring' and
            'Synthetic Zenoss event check' in evt.summary):
        evt.message = '%s\\n%s' % (evt.summary, 'Transform worked.')
'''.format(_ZENOSS_RM, _MSG[:-5])

# Event data
_EVENTDATA = dict(
    device=_ZENOSS_RM,
    component='zenossMonitoring',
    evclass='/App/Zenoss',
    evclasskey='',
    )

# Event search parameters
_PARAMS = dict(
    eventState=[0, 1, 2, 3, 4, 5, 6],
    severity=[5, 4, 3, 2, 1, 0],
    device='%s' % _ZENOSS_RM,
    component='zenossMonitoring',
    eventClass='/App/Zenoss',
    )

# Zenoss severities dict() for easier setting of severity
_SEVERITIES = dict(
    Clear=0,
    Debug=1,
    Info=2,
    Warning=3,
    Error=4,
    Critical=5,
    )


class ZenossAPI(object):
    def __init__(self, host, user, passwd, timeout):
        self._session = requests.Session()
        self._session.auth = (user, passwd)
        self._host = host
        self._req_count = 0
        self.timeout = float(timeout)

    def _router_request(self, method, data=[]):
        req_data = json.dumps([dict(
            action='EventsRouter',
            method=method,
            data=data,
            type='rpc',
            tid=self._req_count,
            )])

        uri = '{0}/zport/dmd/evconsole_router'.format(self._host)
        headers = {'Content-type': 'application/json; charset=utf-8'}
        try:
            response = self._session.post(
                uri,
                data=req_data,
                headers=headers,
                verify=False,
                timeout=self.timeout,
                )
            response.raise_for_status()
        except Exception as e:
            return dict(success=False, msg=str(e))

        self._req_count += 1
        return json.loads(response.content).get('result')

    def openEvent(self, message, severity='Info'):
        data = _EVENTDATA
        data['summary'] = message
        data['severity'] = _SEVERITIES[severity]
        o = self._router_request('add_event', [data])
        return o.get('success', False)

    def findEvent(self, message, severity='Info'):
        time.sleep(_SLEEP)
        _p = _PARAMS
        _p['summary'] = message
        _p['severity'] = _SEVERITIES[severity]
        data = dict(
            limit=1,
            sort='firstTime',
            dir='DESC',
            params=_p,
            )
        f = self._router_request('query', [data])
        for e in f.get('events'):
            if e.get('summary') == message:
                return (True, e.get('evid', ''), e)
        return (False, '', None)

    def closeEvent(self, evid):
        data = dict(
            evids=[evid],
            )
        c = self._router_request('close', [data])
        return c.get('success', False)

    def reopenEvent(self, evid):
        data = dict(
            evids=[evid],
            )
        r = self._router_request('reopen', [data])
        return r.get('success', False)

    def ackEvent(self, evid):
        data = dict(
            evids=[evid],
            )
        a = self._router_request('acknowledge', [data])
        return a.get('success', False)

    def unackEvent(self, evid):
        data = dict(
            evids=[evid],
            )
        u = self._router_request('unacknowledge', [data])
        return u.get('success', False)

    def checkEventState(self, evid, state):
        time.sleep(_SLEEP)
        data = dict(evid=evid)
        ev = self._router_request('detail', [data])
        if ev.get('event'):
            evState = ev['event'][0]['eventState']
            if state == evState:
                return (True, evState)
            else:
                return (False, evState)
        return (False, 'Not found')


class rabbitmqAPI(object):
    def __init__(self, local=True, host=_RABBIT_HOST, port=_RABBIT_PORT,
                 user=_RABBIT_USERNAME, passwd=_RABBIT_PASSWORD,
                 vhost=_RABBIT_VHOST, ssl=_RABBIT_SSL):
        if local:
            import Globals
            from Products.ZenUtils.GlobalConfig import getGlobalConfiguration
            global_conf = getGlobalConfiguration()
            ssl = global_conf.get('amqpusessl', '0')
            self.host = global_conf.get('amqphost', 'localhost')
            self.port = global_conf.get('amqpport', '5672')
            self.user = global_conf.get('amqpuser', 'zenoss')
            self.passwd = global_conf.get('amqppassword', 'zenoss')
            self.vhost = global_conf.get('amqpvhost', '/zenoss')
            self.ssl = (True if ssl in ('1', 'True', 'true') else False)
        else:
            self.host = host
            self.port = port
            self.user = user
            self.passwd = passwd
            self.vhost = vhost
            self.ssl = ssl

    def connect(self):
        from amqplib.client_0_8.connection import Connection
        try:
            conn = Connection(
                host="%s:%s" % (self.host, self.port),
                userid=self.user,
                password=self.passwd,
                virtual_host=self.vhost,
                ssl=self.ssl
                )
            channel = conn.channel()
        except Exception as e:
            return dict(success=False, msg=str(e))
        return dict(connection=conn, channel=channel, success=True)

    def getQueueCount(self, queues=_QUEUES.keys()):
        r = self.connect()
        if not r['success']:
            return r
        qInfo = {}
        with r['connection']:
            with r['channel']:
                for q in queues:
                    n, c, _ = r['channel'].queue_declare(q, passive=True)
                    qInfo[n] = c
        r['data'] = qInfo
        return r


def parse_options(scriptVersion, description_string):
    parser = argparse.ArgumentParser(
        version=scriptVersion,
        description=description_string
        )

    parser.add_argument(
        "-s",
        "--synthetic",
        action="store_true",
        default=False,
        help="perform synthetic check"
        )
    parser.add_argument(
        "-q",
        "--queue",
        action="store_true",
        default=False,
        help="perform rabbitmq queue check"
        )
    parser.add_argument(
        "-e",
        "--event",
        action="store",
        default=False,
        type=str,
        metavar='EVID',
        help="perform event check on pre-existing event"
        )
    parser.add_argument(
        "-t",
        "--transform",
        action="store_true",
        default=False,
        help="print out transform"
        )
    parser.add_argument(
        "-c",
        "--create",
        action="store_true",
        default=False,
        help="create event for pre-existing event check"
        )
    return parser


def syntheticCheck():
    rnd = idGenerator()
    msg = _MSG.format(rnd)
    z = ZenossAPI(
        host=_ZENOSS_INSTANCE,
        user=_ZENOSS_USERNAME,
        passwd=_ZENOSS_PASSWORD,
        timeout=_ZENOSS_TIMEOUT
        )
    o = z.openEvent(msg)
    if not o:
        return nagiosOutput('Could not open event', 2)

    i = 0
    f = False
    while not f and i < _RETRY:
        i += 1
        f, evid, e = z.findEvent(msg)

    if not f:
        return nagiosOutput('Could not find event', 2)

    if 'Transform worked.' not in e.get('message'):
        return nagiosOutput('Event was not modified by transform.', 1)

    c = z.closeEvent(evid)
    if not c:
        return nagiosOutput('Could not close event', 2)

    i = 0
    v = False
    while not v and i < _RETRY:
        i += 1
        v, s = z.checkEventState(evid, 'Closed')

    if not v:
        return nagiosOutput('Could not close event', 2)

    return nagiosOutput('Everything OK!', 0)


def eventCheck(evid):
    z = ZenossAPI(
        host=_ZENOSS_INSTANCE,
        user=_ZENOSS_USERNAME,
        passwd=_ZENOSS_PASSWORD,
        timeout=_ZENOSS_TIMEOUT
        )
    c = z.ackEvent(evid)
    if not c:
        return nagiosOutput('Could not acknowledge event', 2)

    i = 0
    v = False
    while not v and i < _RETRY:
        i += 1
        v, s = z.checkEventState(evid, 'Acknowledged')

    if not v:
        return nagiosOutput('Could not acknowledge event', 2)

    c = z.unackEvent(evid)
    if not c:
        return nagiosOutput('Could unacknowledge event', 2)

    i = 0
    v = False
    while not v and i < _RETRY:
        i += 1
        v, s = z.checkEventState(evid, 'New')

    return nagiosOutput('Everything OK!', 0)


def createEvent():
    rnd = idGenerator()
    msg = _MSG.format(rnd)
    z = ZenossAPI(
        host=_ZENOSS_INSTANCE,
        user=_ZENOSS_USERNAME,
        passwd=_ZENOSS_PASSWORD,
        timeout=_ZENOSS_TIMEOUT
        )
    o = z.openEvent(msg, _SEVERITY)
    if not o:
        return 'Could not open event'

    i = 0
    f = False
    while not f and i < _RETRY:
        i += 1
        f, evid, e = z.findEvent(msg, _SEVERITY)

    if not f:
        return 'Could not find event'

    return evid


def idGenerator():
    import random
    import string
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(6))


def nagiosOutput(message, code, data={}):
    if data:
        o = ' '.join('{}={}'.format(k, v) for k, v in sorted(data.items()))
        message = '%s | %s' % (message, o)
    if code == 0:
        print message
        sys.exit(code)
    else:
        print message
        sys.exit(message)


def checkQueues(queues=_QUEUES):
    r = rabbitmqAPI(local=False)
    q = r.getQueueCount(queues=queues.keys())
    alert = 0
    msg = ''
    if not q['success']:
        return  nagiosOutput(q.get('msg'), 2)

    for k, v in q['data'].iteritems():
        if v > queues.get(k):
            alert = 2
            msg = '%s queue has %s messages queued. %s' % (k, v, msg)
    if alert == 0:
        msg = 'Everything OK!'
    return nagiosOutput(msg, alert, q['data'])


def main():
    scriptName = os.path.basename(__file__).split('.')[0]
    desc = '{}\n{}\n{}'.format(scriptName, scriptSummary, documentationURL)
    parser = parse_options(scriptVersion, desc)
    cli_options = vars(parser.parse_args())

    if cli_options['transform']:
        print _TRANSFORM
        sys.exit(0)

    if cli_options['synthetic']:
        print syntheticCheck()

    if cli_options['event']:
        print eventCheck(cli_options['event'])

    if cli_options['create']:
        print 'Event ID to use for pre-existing event check:'
        print createEvent()

    if cli_options['queue']:
        print checkQueues()


if __name__ == "__main__":
    main()
