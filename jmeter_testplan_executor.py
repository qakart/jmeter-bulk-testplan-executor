#! /usr/local/bin/python

import os
import shutil
import subprocess
import sys
import traceback
import urllib2
from datetime import datetime
from optparse import OptionParser
from time import sleep

HOST_MACHINE = ""
SERVICE_STOP_COMMAND = ""
SERVICE_START_COMMAND = ""
CLIENT_URL = "http://hawk.cit.andover.ocado.com"

SERVICE_STOPPED_MSG = "service started" #whatever is printed in logs
SERVICE_STARTED_MSG = "service stopped" #whatever is printed in logs

JMETER_DIR = "/Users/pavel.nenov/Downloads/apache-jmeter-3.2/bin"

SCRIPT_PATH = os.path.abspath(os.path.dirname(__file__))


def get_options():
    usage = "Run jmeter performance tests."
    parser = OptionParser(usage=usage)

    # optional
    parser.add_option("-t", "--testplan-dir",
                      help="The directory where the test plans for execution are stored. Default: 'testplans'",
                      default=os.path.join(SCRIPT_PATH, "testplans"))
    # optional
    parser.add_option("-j", "--jmeter-dir",
                      help="The directory where JMeter lives (incl. /bin). Default is './jmeter/bin/'",
                      default=os.path.join(SCRIPT_PATH, "jmeter", "bin"))
    # optional
    parser.add_option("-r", "--reports-dir",
                      help="The directory where jmeter reports will be saved. Default is 'reports'",
                      default=os.path.join(SCRIPT_PATH, "reports"))
    # optional
    parser.add_option("-d", "--dashboards-dir",
                      help="The directory where jmeter dashboards will be saved. Default is 'dashboards'",
                      default=os.path.join(SCRIPT_PATH, "dashboards"))

    (options, args) = parser.parse_args()
    return options


def clean_dir(directory):
    for f in os.listdir(directory):
        file_path = os.path.join(directory, f)
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
            else:
                shutil.rmtree(file_path)
        except Exception as e:
            print str(e)


def prepare_dirs(opts):
    if not os.path.exists(opts.reports_dir):
        os.makedirs(opts.reports_dir)
    if not os.path.exists(opts.dashboards_dir):
        os.makedirs(opts.dashboards_dir)


class bcolors:
    OKBLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[33m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


# normal log
def print_green(str):
    print bcolors.GREEN + str + bcolors.ENDC


# error
def print_red(str):
    print bcolors.RED + str + bcolors.ENDC


# command execution
def print_magenta(str):
    print bcolors.MAGENTA + str + bcolors.ENDC


def print_yellow(str):
    print bcolors.YELLOW + str + bcolors.ENDC


# shell command
def print_cyan(str):
    print bcolors.CYAN + str + bcolors.ENDC


class ExecutionException(Exception):
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


class JMeterTestExecutor(object):

    #this assumes that the JMeter test plan has jvm paramets for (threads, loops - times the same request is sent over and over again)
    #structure in jmeter:
        #for ${num_threads} threads:
            #for ${var} times:
                #POST msg
    SSH_TIMEOUT = 180
    JMETER_TIMEOUT = 5400  # 1.5 hours

    EXECUTION_STEPS = (
        (20, 10),  # approx 10k requests
        (30, 20),  # approx 30k requests
        (50, 30),  # approx 60k requests
        (100, 30),  # approx 150k requests
        (200, 100),  # approx 1mil requests
        (500, 100), #approx  2.5 mil requests
    )

    def __init__(self, testplans_dir, jmeter_dir, reports_dir, dashboards_dir):
        self._jmeter_dir = jmeter_dir
        self._reports_dir = reports_dir
        self._dashboards_dir = dashboards_dir
        self._testplans_list = self._get_test_plans(testplans_dir)

    def _get_test_plans(self, testplan_dir):
        testplan_name_path_map = {}
        for file in os.listdir(testplan_dir):
            if not file.endswith(".jmx"):
                continue
            print_green("Found test plan: " + file)
            file_name = file.replace(".jmx", "")
            testplan_name_path_map[file_name] = os.path.join(SCRIPT_PATH, testplan_dir,
                                                             file)
        print '*' * 50
        return testplan_name_path_map

    def _get_timestamp(self):
        now = datetime.now()
        date_str = now.strftime("%Y_%m_%dT%H_%M_%S")
        return date_str

    def _execute_shh_command_remotely(self, cmd, verify_message):
        params = ["ssh", "%s" % HOST_MACHINE, cmd]
        max_tries = 10
        try_count = 0
        while try_count < max_tries:
            print_cyan("Execute ssh command: " + ' '.join(params))
            proc = subprocess.Popen(params,
                                    shell=False,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
            self._wait_for_process(proc, self.SSH_TIMEOUT)
            result = proc.stdout.readlines()
            if result == []:
                error = proc.stderr.readlines()
                print_red("ERROR: %s" % error)
                sleep(10)
            else:
                print_cyan("Server result: " + ' '.join(result))
                break

    def is_client_up(self):
        #check that web service is up after restart
        try:
            conn = urllib2.urlopen(CLIENT_URL)
            return conn.getcode() == 200
        except urllib2.HTTPError, urllib2.URLError:
            return False
        except Exception:
            return False

    def _wait_for_server_to_start(self):
        print_green("Waiting for scada to start...")
        try_count = 90
        attempts = 1
        is_service_up = False
        while attempts <= try_count:
            if self.is_scada_service_up() is True:
                print_green("Server is back!")
                is_service_up = True
                break
            print_green("\t...waiting 10 seconds....")
            sleep(10)
            attempts += 1
        if is_service_up is False:
            print_red("Server has not stated after timeout :(")


    def start_service(self):
        print_green("Starting service...")
        self._execute_shh_command_remotely(SERVICE_STOP_COMMAND, SERVICE_STARTED_MSG)
        self._wait_for_server_to_start()

    def stop_service(self):
        print_green("Stopping service...")
        self._execute_shh_command_remotely(SERVICE_START_COMMAND, SERVICE_STOPPED_MSG)

    def restart_service(self):
        #So each perf test can start clean
        print_green("Restarting service")
        self.stop_service()
        self.start_service()
    
    def _wait_for_process(self, proc, timeout):
        """return True if process finished alone
        return False if process was killed"""
        wait_time = 0
        while wait_time < timeout:
            print "proces poll", proc.poll()
            if proc.poll() is not None:
                return proc.returncode == 0
            wait_time += 1
            sleep(1)
        else:
            pids = subprocess.check_output("ps axu | grep  jmeter | grep -v grep  | awk '{print $2}'", shell=True)
            print_yellow("Killing jmeter due to timeout")
            for p in pids.split():
                print_yellow("Killing jmeter due to timeout")
                os.kill(int(p.strip()), signal.SIGKILL)
            return False


    def _run_jmeter(self, test_plan, report_path, thread_count, loop_count, dashboard_output_dir):
        try:
            params = ["./jmeter.sh",
                      "-n",
                      "-t",
                      test_plan,
                      "-JthreadCount=%d" % thread_count,
                      "-JloopMsgCount=%d" % loop_count,
                      "-l",
                      report_path,
                      "-e",
                      "-o",
                      dashboard_output_dir,
                      ]

            try:
                try_count = 2
                attempts = 1
                while attempts <= try_count:
                    print_magenta("Execute command: " + ' '.join(params))
                    proc = subprocess.Popen(params, cwd=self._jmeter_dir)
                    was_process_successful = self._wait_for_process(proc, self.JMETER_TIMEOUT)
                    if was_process_successful is True:
                        break
                    else:
                        self.restart_scada()
                    attempts += 1
            except Exception:
                raise  # ExecutionException(e)
        except:
            raise ExecutionException

    def _calculate_requests(self, threads, loops):
        return threads * loops * self.BOTS_NUMBER

    def execute(self):
        try:
            for threads, loops in self.EXECUTION_STEPS:
                requests_num = self._calculate_requests(threads, loops)
                for test_plan_name, test_plan_path in self._testplans_list.iteritems():
                    print_yellow("Starting sequence of executions for test plan:" + test_plan_name)
                    # self._generated_reports[test_plan_name] = []

                    print_yellow("\tExectute test plan %s with %d requests" % (test_plan_name, requests_num))
                    report_timestamp = self._get_timestamp()
                    report_path = os.path.join(SCRIPT_PATH, self._reports_dir,
                                               "report_%s_%s_%d.csv" % (report_timestamp, test_plan_name, requests_num))

                    try:
                        dashboard_output_dir = os.path.join(os.path.abspath(os.path.basename(__file__)),
                                                                   self._dashboards_dir, "%s_%s_%d" % (
                                                                       test_plan_name, report_timestamp, requests_num))
                        self._run_jmeter(test_plan_path, report_path, threads, loops, dashboard_output_dir)
                    except ExecutionException as e:
                        print_red(traceback.format_exc(e))
                        raise
                    except Exception as e:
                        print_red("Unknown error")
                        raise

                    self.restart_service()
                    #TODO implement a real check
                    print_green("Wait a bit, the server might need it")
                    for i in xrange(600):
                        if i % 10 == 0:
                            print "zZzZzZz"

                        sleep(1)
                    print
        except ExecutionException as e:
            raise
        except Exception as e:
            raise


if __name__ == '__main__':
    options = get_options()
    prepare_dirs(options)

    jmeter_executor = JMeterTestExecutor(options.testplan_dir, options.jmeter_dir, options.reports_dir,
                                         options.dashboards_dir)
    try:
        print_green("Restart service, start testing a-fresh")
        jmeter_executor.restart_service()
        jmeter_executor.execute()
    except KeyboardInterrupt:
        print_green("Check if service is running...")
        if jmeter_executor.is_client_up() is False:
            jmeter_executor.start_service()
        else:
            print_green("Yep, server's up")
    except ExecutionException as e:
        print_red(traceback.format_exc(e))
    except Exception as e:
        print_red(traceback.format_exc(e))
        jmeter_executor.restart_service()
    print_green("End of test run!")
