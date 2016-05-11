#Monitoring Zenoss


This script is provided to help administrators monitor their Zenoss instance.

##Script commands
```./zenossMonitoring.py -h```

```
usage: zenossMonitoring.py [-h] [-v] [-s] [-q] [-e EVID] [-t] [-c]

zenossMonitoring script for monitoring event handling in Zenoss.
http://wiki.zenoss.org/Monitoring_Zenoss

optional arguments:
  -h, --help            show this help message and exit
  -v, --version         show program's version number and exit
  -s, --synthetic       perform synthetic check
  -q, --queue           perform rabbitmq queue check
  -e EVID, --event EVID
                        perform event check on pre-existing event
  -t, --transform       print out transform
  -c, --create          create event for pre-existing event check
```

You will need to either edit the global variables within the script to match your environment. Or import the classes/methods and pass the proper arguments.

### Install Instructions
Requires:

 - Python 2.7
 - argparse module
 - requests module

easy_install argparse

easy_install requests

##Monitoring queues in RabbitMQ

Monitoring for common symptoms of problems with an application can be very helpful. Especially when many issues have one common symptom. 

Looking for backed up queues in RabbitMQ is one of those symptoms.

**Here are a few issues that will cause queues to back up:**
 
 - Slow or bad transform
 - Stopped daemons:
     - zeneventd
     - zeneventserver
     - zenactiond
 - Deadlocked ZenDS/MySql

For this reason, it is important to monitor the queues within RabbitMQ.

**There are three queues that are critical to Zenoss event flow:**

- zenoss.queues.zep.rawevents
- zenoss.queues.zep.zenevents
- zenoss.queues.zep.signal

See [Queue Troubleshooting](http://wiki.zenoss.org/Queue_Troubleshooting) for more information on Zenoss queues.


Monitoring the queues:

```./zenossMonitoring.py -q```

This will also print out performance data

```
Everything OK! | zenoss.queues.zep.rawevents=0 zenoss.queues.zep.signal=0 zenoss.queues.zep.zenevents=0
```

##Event Monitoring
There are two synthetic type checks for monitoring events.

First is a pre-existing event check. This will send API calls to Zenoss to acknowledge and unacknowledge an event. This will verify that the following is up and running in some capacity.

- ZenDS/MySql
- zeneventserver
- zenwebserver

Monitoring a pre-existing event:

```./zenossMonitoring.py -e 005056b9-4bf4-8754-11e6-17b8c881cd54```

You can also use the script to create a template event to use for the pre-existing event check.

```
./zenossMonitoring.py -c
Event ID to use for pre-existing event check:
005056b9-4bf4-8754-11e6-17b8c881cd54
```

The second is a more synthetic check. 

1. This will open a new event
2. Find the event created
3. Check the event was modified by the transform
4. Close the event
5. Verify the event was closed

This will verify that the following is up and running in some capacity:

- ZenDS/MySql
- zenwebserver
- zeneventd
- zeneventserver

You will need to have a transform put in place for this to work properly. the transform can be retrived from the script.

Print transform:

```/zenossMonitoring.py -t```

```
./zenossMonitoring.py -t

Under Event Class /App/Zenoss, add the following transform:
if hasattr(evt, 'device') and hasattr(evt, 'component'):
    if (evt.device == 'localhost' and
            evt.component == 'zenossMonitoring' and
            'Synthetic Zenoss event check' in evt.summary):
        evt.message = '%s
%s' % (evt.summary, 'Transform worked.')
```

