#-*- coding: utf-8 -*-

import sys
import os
import time
import yaml
import random

from twisted.internet import reactor
from twisted.python import usage
from twisted.python.util import spewer

from ooni.errors import InvalidOONIBCollectorAddress

from ooni import config
from ooni.director import Director
from ooni.reporter import YAMLReporter, OONIBReporter

from ooni.nettest import NetTestLoader, MissingRequiredOption

from ooni.utils import log

class Options(usage.Options):
    synopsis = """%s [options] [path to test].py
    """ % (os.path.basename(sys.argv[0]),)

    longdesc = ("ooniprobe loads and executes a suite or a set of suites of"
                " network tests. These are loaded from modules, packages and"
                " files listed on the command line")

    optFlags = [["help", "h"],
                ["resume", "r"]]

    optParameters = [["reportfile", "o", None, "report file name"],
                     ["testdeck", "i", None,
                         "Specify as input a test deck: a yaml file containig the tests to run an their arguments"],
                     ["collector", "c", 'httpo://nkvphnp3p6agi5qq.onion',
                         "Address of the collector of test results. default: httpo://nkvphnp3p6agi5qq.onion"],
                     ["logfile", "l", None, "log file name"],
                     ["pcapfile", "O", None, "pcap file name"],
                     ["parallelism", "p", "10", "input parallelism"],
                     ]

    compData = usage.Completions(
        extraActions=[usage.CompleteFiles(
                "*.py", descr="file | module | package | TestCase | testMethod",
                repeat=True)],)

    tracer = None

    def __init__(self):
        self['test'] = None
        usage.Options.__init__(self)

    def opt_asciilulz(self):
        from ooni.utils import logo
        print logo.getlogo()

    def opt_spew(self):
        """
        Print an insanely verbose log of everything that happens.  Useful
        when debugging freezes or locks in complex code.
        """
        sys.settrace(spewer)

    def parseArgs(self, *args):
        if self['testdeck']:
            return
        try:
            self['test_file'] = args[0]
            self['subargs'] = args[1:]
        except:
            raise usage.UsageError("No test filename specified!")

def parseOptions():
    cmd_line_options = Options()
    if len(sys.argv) == 1:
        cmd_line_options.getUsage()
    try:
        cmd_line_options.parseOptions()
    except usage.UsageError, ue:
        raise SystemExit, "%s: %s" % (sys.argv[0], ue)

    return dict(cmd_line_options)

def shutdown(result):
    """
    This will get called once all the operations that need to be done in the
    current oonicli session have been completed.
    """
    log.debug("Halting reactor")
    try: reactor.stop()
    except: pass

def runWithDirector():
    """
    Instance the director, parse command line options and start an ooniprobe
    test!
    """
    global_options = parseOptions()
    log.start(global_options['logfile'])

    # contains (test_cases, options, cmd_line_options)
    test_list = []

    if global_options['testdeck']:
        test_deck = yaml.safe_load(open(global_options['testdeck']))
        for test in test_deck:
            test_list.append(NetTestLoader(test['options'],
                                           test_file=global_options['test_file']))
    else:
        log.debug("No test deck detected")
        test_list.append(NetTestLoader(global_options['subargs'],
                                       test_file=global_options['test_file']))

    # check each test's usageOptions
    for net_test_loader in test_list:
        try:
            net_test_loader.checkOptions()
        except MissingRequiredOption, option_name:
            log.err('Missing required option: "%s"' % option_name)
            print net_test_loader.usageOptions().getUsage()
            sys.exit(2)
        except usage.UsageError, e:
            log.err(e)
            print net_test_loader.usageOptions().getUsage()
            sys.exit(2)

    director = Director()
    d = director.start()

    def director_startup_failed(failure):
        log.err("Failed to start the director")
        log.exception(failure)
        reactor.stop()

    # Wait until director has started up (including bootstrapping Tor) before adding tess
    def post_director_start(_):
        for net_test_loader in test_list:
            test_details = net_test_loader.testDetails

            yaml_reporter = YAMLReporter(test_details)
            reporters = [yaml_reporter]

            if global_options['collector']:
                try:
                    oonib_reporter = OONIBReporter(test_details,
                            global_options['collector'])
                    reporters.append(oonib_reporter)
                except InvalidOONIBCollectorAddress:
                    log.err("Invalid format for oonib collector address.")
                    log.msg("Should be in the format http://<collector_address>:<port>")
                    log.msg("for example: ooniprobe -c httpo://nkvphnp3p6agi5qq.onion")
                    sys.exit(1)

            log.debug("adding callback for startNetTest")
            d.addCallback(director.startNetTest, net_test_loader, reporters)
        d.addCallback(shutdown)

    d.addCallback(post_director_start)
    d.addErrback(director_startup_failed)
    reactor.run()
