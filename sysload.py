#!/usr/bin/env python2.7

# -*- coding: utf-8 -*-
__author__ = 'shandr'
# TODO: Add more complex iostat analyzing
# TODO: Add Ctrl+C proper reaction

import sys
import subprocess
import re
import os
import socket
import threading
import Queue
import argparse
import operator

if not os.geteuid() == 0:
    sys.exit('Script must be run as root')

#Threshold values
get_stat_time = 10
high_net_queue = 10000
critical_hdd_space = 80 #in %
hdd_critical_utilization = 70
ram_free_critical_percent = 15
swap_free_critical_percent = 30

#CPU thresholds
cpu_critical_idle = 50
cpu_critical_wa = 20
cpu_critical_us = 50
cpu_critical_sy = 50
cpu_critical_process_usage = 90


parser = argparse.ArgumentParser(description='This script analyzes system performance issues')
parser.add_argument("--cpu", action="store_true", help="check cpu load")
parser.add_argument("--mem", action="store_true", help="check memory usage")
parser.add_argument("--io", action="store_true", help="check io usage")
parser.add_argument("--net", action="store_true", help="check network issues")
parser.add_argument("--all", action="store_true", help="check all system components")
parser.add_argument("--fs", action="store_true", help="check free space")
#parser.add_argument("--d", action="store_true", help="debug")

class MyQueue(Queue.Queue):
    def __init__(self):
        Queue.Queue.__init__(self)
class bcolors:
    HEADER = '\033[1;30m'
    OKBLUE = '\033[34m'
    OKGREEN = '\033[32m'
    WARNING = '\033[33m'
    FAIL = '\033[31m'
    ENDC = '\033[0m'

    def disable(self):
        self.HEADER = ''
        self.OKBLUE = ''
        self.OKGREEN = ''
        self.WARNING = ''
        self.FAIL = ''
        self.ENDC = ''

def check_software():
    if os.path.exists('/etc/debian_version'):
        if_iotop=subprocess.call(["dpkg", "-l", "iotop"],shell=False,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if_sysstat=subprocess.call(["dpkg", "-l", "sysstat"],shell=False,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if if_iotop == 1:
            print "iotop util is required. Please install it before using sysload.py(sudo apt-get get install iotop)"
        if if_sysstat == 1:
            print "sysstat util is required. Please install it before using sysload.py(sudo apt-get install sysstat)"
        if if_iotop == 1 or if_sysstat == 1:
            sys.exit(0)
    if os.path.exists('/etc/redhat-release'):
        if_iotop=subprocess.call(["rpm", "-qi", "iotop"],shell=False,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if_sysstat=subprocess.call(["rpm", "-qi", "sysstat"],shell=False,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if if_iotop == 1:
            print "iotop util is required. Please install it before using sysload.py(sudo yum install iotop)"
        if if_sysstat == 1:
            print "sysstat util is required. Please install it before using sysload.py(sudo yum install sysstat)"
        if if_iotop == 1 or if_sysstat == 1:
            sys.exit(0)


def get_vm_stats():
    vmstat_counters_dict={}
#letters = ['r','b','swpd','free','buff','cache','si','so','bi','bo','in','cs','us','sy','id', 'wa']
    vm_output = subprocess.Popen("vmstat 1 %d" % get_stat_time, shell=True, stdout = subprocess.PIPE).stdout.read()
    vm_output_new = vm_output.split("\n")
    letters=vm_output_new[1].split()
    count=0
    for i in vm_output_new[3:]:
        counters_temp = re.findall(r'\d+',i) #we have list of values
        if len(counters_temp) > 0:
            while count < len(letters):
                if letters[count] in vmstat_counters_dict:
                    vmstat_counters_dict[letters[count]].append(counters_temp[count])
                else:
                    vmstat_counters_dict[letters[count]]=[counters_temp[count]]
                count +=1
        count = 0
    get_vm_stats_q.put(vmstat_counters_dict)
    return vmstat_counters_dict

def get_iostat():
    counters_dict={}
    iostat_output = subprocess.Popen("iostat -Ndxz 1 %d" % get_stat_time, shell=True, stdout = subprocess.PIPE).stdout.read()
    iostat_output_new = iostat_output.split("\n")
    letters=iostat_output_new[2].split()[1:]
    for line in iostat_output_new:
        count=0
        match = re.search(r'^\w+[-_]*\w*\s{3,}.*\d+',line)
        if match:
            counters_list=line.split()
            if not counters_dict.get(counters_list[0]):
                counters_dict[counters_list[0]]=[]
            while count < len(letters):
                if len(counters_dict[counters_list[0]])<13:
                    counters_dict[counters_list[0]].append([letters[count]])
                count+=1
            count=0
            while count < len(letters):
                counters_dict[counters_list[0]][count].append(counters_list[count+1])
                count+=1
    get_iostat_q.put(counters_dict)
    return counters_dict

def get_iotop():
    iotop_dict={}
    iotop_output=subprocess.Popen('iotop -b -o -P -k -d %d -qqq -n 2' % get_stat_time, shell=True,stdout=subprocess.PIPE).stdout.read()
    iotop_output_split=iotop_output.split('\n')
    for line in iotop_output_split:
        list = line.split()
        if len(list)<=12 and len(list)>0:
            iotop_dict[list[0]]=[list[2],list[3],list[5],list[7],list[9],list[11]]
        elif len(list)>12:
            iotop_dict[list[0]]=[list[2],list[3],list[5],list[7],list[9],list[11]+list[12]]
    get_iotop_q.put(iotop_dict)
    return iotop_dict

def get_net_stat():
    counters_dict={}
    netstat_output = subprocess.Popen("for i in $(seq %d); do netstat -i;sleep 1; done" % get_stat_time, shell=True,stdout=subprocess.PIPE).stdout.read()
    netstat_output_new = netstat_output.split("\n")
    letters=netstat_output_new[1].split()[1:]
    for line in netstat_output_new:
        count=0
        match = re.search(r'^\w+[-_]*\w*\s{3,}.*\d+',line)
        if match:
            counters_list=line.split()
            if not counters_dict.get(counters_list[0]):
                counters_dict[counters_list[0]]=[]
            while count < len(letters):
                if len(counters_dict[counters_list[0]])<11:
                    counters_dict[counters_list[0]].append([letters[count]])
                count+=1
            count=0
            while count < len(letters):
                counters_dict[counters_list[0]][count].append(counters_list[count+1])
                count+=1
    get_net_stat_q.put(counters_dict)
    return counters_dict

def dns_check():
    try:
        return socket.gethostbyname('google.com')
    except socket.gaierror:
        return False

def ping_lizard():
    ping_lizard = subprocess.Popen("ping -c %d 193.28.87.4" % get_stat_time, shell=True, stdout=subprocess.PIPE).stdout.read()
    ping_liz_result = re.search(r'(\d{1,3})%\s+packet',ping_lizard)
    ping_lizard_q.put([ping_liz_result.group(1)])
    return

def ping_google():
    ping_google = subprocess.Popen("ping -c %d 8.8.8.8" % get_stat_time, shell=True, stdout=subprocess.PIPE).stdout.read()
    ping_google_result = re.search(r'(\d{1,3})%\s+packet',ping_google)
    ping_google_q.put([ping_google_result.group(1)])

def get_net_queue():
    counters_dict={}
    counters_list_total=[]
    netstat_output = subprocess.Popen("for i in $(seq %d); do netstat -nutap |grep -v '0      0';sleep 1; done" % get_stat_time, shell=True,stdout=subprocess.PIPE).stdout.read()
    netstat_output_new=netstat_output.split("\n")
    for line in netstat_output_new:
        match = re.search(r'^[udp|tcp]',line)
        if match:
            counters_list=line.split()
            if len(counters_list)==7:
                counters_list = [counters_list[0],counters_list[1],counters_list[2],counters_list[3],counters_list[4],counters_list[6]]
            else:
                counters_list = [counters_list[0],counters_list[1],counters_list[2],counters_list[3],counters_list[4],counters_list[5]]

            if int(counters_list[1]) > high_net_queue or int(counters_list[2]) > high_net_queue:
                counters_list_total.append(counters_list)
                my_key = counters_list[3]+'('+counters_list[4]+')'
                if my_key not in counters_dict:
                    counters_dict[my_key]=[(counters_list[0],counters_list[1],counters_list[2])]
                else:
                    counters_dict[my_key].append([(counters_list[0],counters_list[1],counters_list[2])])
    if len(counters_dict)==0:
        counters_dict,counters_list_total = None,None
#    get_net_queue_q.put(counters_dict)
    get_net_queue_q.put(counters_list_total)
    return counters_dict

def cpu_count():
    cpu_count=0
    cpu_info_f=''
    try:
        cpu_info_f = open('/proc/cpuinfo', 'r')
    except IOError, err:
        print "%s %s" % (cpu_info_f, err)
    for line in cpu_info_f:
        match_cpu = re.search(r'^processor',line)
        if match_cpu: cpu_count = cpu_count+1
    cpu_count_q.put(cpu_count)
    return cpu_count

def get_la():
    la = os.getloadavg()
    get_la_q.put(la)
    return la

def check_free_space():
    dev=''
    free_space_dict={}
    space_usage = subprocess.Popen('df -h',shell=True, stdout=subprocess.PIPE).stdout.read()
    space_usage_split=space_usage.split('\n')
    for line in space_usage_split:
        match = re.search(r'^[Filesystem|none]',line)
        if not match:
            if len(line.split()) == 1:
                dev = line
            if len(line.split()) == 5:
                percent = re.search(r'(\d+)%',line)
                line_new = line.split()
                line_new.insert(0,dev)
                line_new[4]=percent.group(1)
                if int(line_new[4])> critical_hdd_space:
                    free_space_dict[dev]=[line_new[1],line_new[2],line_new[3],line_new[4],line_new[5]]
                    pass
            if len(line.split()) == 6:
                percent = re.search(r'(\d+)%',line)
                line = line.split()
                line[4]=percent.group(1)
                if int(line[4])> critical_hdd_space:
                    free_space_dict[line[0]]=[line[1],line[2],line[3],line[4],line[5]]
    return free_space_dict

def percent_count(first,second):
    if float(first) > 0:
        percent = (float(second)/float(first))*100
    else:
        percent = 100
    return percent

def get_mem_info():
    file = open('/proc/meminfo','r')
    mem_info_dict={}
    for line in file:
        match=re.search(r'(\w+):\s+(\d+)',line)
        if match:
            p_name=match.group(1)
            p_value=match.group(2)
            mem_info_dict[p_name]=p_value
    return mem_info_dict

def get_proc_usage_by_pr():
    count_lines=0
    counters_dict={}
    top_output = subprocess.Popen('top -b -i -d%d -n2' % get_stat_time,shell=True,stdout=subprocess.PIPE).stdout.read()
    top_output_list = top_output.split('\n')
    for line in top_output_list:
        match=re.search(r'^\s*\d+\s+\w+',line)
        match_new_cycle=re.search(r'load average',line)
        if match_new_cycle: counters_dict={}
        if match:
            if count_lines < 6:
                counters_list=line.split()
                match = re.search(r'(\d+)\.?',counters_list[8])
                if match:
                    counters_list[8]=match.group(1)
                if counters_list[0] not in counters_dict and int(counters_list[8]) > 0:
                    counters_dict[counters_list[0]]=[[counters_list[11],counters_list[1],counters_list[7],counters_list[8]]]
                elif int(counters_list[8])>0:
                    counters_dict[counters_list[0]].append([counters_list[11],counters_list[1],counters_list[7],counters_list[8]])
                count_lines += 1
        if match_new_cycle: count_lines=0
    get_proc_usage_by_pr_q.put(counters_dict)
    return counters_dict


def mem_usage_by_process():
    ps_output_list=[]
    ps_output=subprocess.Popen('ps c -e -o pid,rss,cmd |sort -nr -k2 |head -10',shell=True, stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout.read()
    ps_output_new = ps_output.split('\n')
    for line in ps_output_new:
        if line != '':
            counters_list=line.split()
            ps_output_list.append(counters_list)
    mem_usage_by_process_q.put(ps_output_list)
    return ps_output_list

def swap_usage_by_process():
    dir = '/proc/'
    files = os.listdir(dir)
    swap_dict = {}
    processes = []
    [processes.append(i) for i in files if re.search(r'\d+',i)]
    for proc in processes:
        swap_size = 0
        try:
            smaps = open(dir+proc+'/'+'smaps','r')
        except:
            pass
        for line in smaps:
            match = re.search(r'^Swap:\s+(\d+)',line)
            if match:
                if int(match.group(1)) != 0:
                    swap_size = swap_size+int(match.group(1))
        if swap_size/1024 > 0:
            swap_dict[proc] = swap_size
    if len(swap_dict)>0:
        sorted_dict_tuple=sorted(swap_dict.iteritems(),key=operator.itemgetter(1),reverse=True)
        swap_usage_by_process_q.put(sorted_dict_tuple)
        return sorted_dict_tuple
    else:
        return None

def print_swap_usage(sorted_tuple):
    count=0
    for key, value in sorted_tuple:
        if count == 11:
            return
        proc_name = subprocess.Popen("ps --no-heading -p %s |awk '{print $4}'" % key,shell=True,stdout=subprocess.PIPE).stdout.read()
        print "PID: %5s  SWAP: %4d MB PROCESS_NAME: %-1s" % (key,value/1024,proc_name),
        count=count+1

def mem_analizer(vmstat_counters_dict):
    print '\n',
    print bcolors.OKBLUE + 'MEMORY STATISTICS' + bcolors.ENDC
    print '\n',
    flag_si,flag_so,flag_swpd,flag_swpd_free = False,False,False,False
    mem_total = mem_info['MemTotal']
    mem_free = mem_info['MemFree']
    mem_cached = mem_info['Cached']
    swap_total = mem_info['SwapTotal']
    swap_free = mem_info['SwapFree']
    mem_free_percent = int(percent_count(mem_total,int(mem_free)+int(mem_cached)))
    swap_free_percent=int(percent_count(swap_total,swap_free))

    for si in vmstat_counters_dict['si']:
        if int(si) > 0:
            flag_si = True
    for so in vmstat_counters_dict['so']:
        if int(so) > 0:
            flag_so = True
    for swpd in vmstat_counters_dict['swpd']:
        if int(swpd) > 0:
            flag_swpd = True

    if mem_free_percent < ram_free_critical_percent: # change this in production
        print bcolors.FAIL + "Free memory %% is low: %d " % mem_free_percent + bcolors.ENDC
        print '\n'
        print bcolors.FAIL + "The most memory consuming programs are: " + bcolors.ENDC
        for proc in mem_usage_by_process_res:
            print "PID: %-5s NAME: %-15s RES: %4d MB" % (proc[0],proc[2],int(proc[1])/1024)
    else:
        print bcolors.OKGREEN + "Mem free %% is OK: %s" % mem_free_percent + bcolors.ENDC

#    print "swap free %% is", swap_free_percent
    if swap_free_percent < swap_free_critical_percent:
        print bcolors.FAIL + "Free SWAP %% is low: %d " % swap_free_percent + bcolors.ENDC
        flag_swpd_free=True
    if flag_so:
        print bcolors.FAIL + "The memory is actively swapping to disk" + bcolors.ENDC
        print "so values: %(so)s " % vmstat_counters_dict
    if flag_si:
        print bcolors.FAIL + "The memory is actively swapping from disk" + bcolors.ENDC
        print "si values: %(si)s " % vmstat_counters_dict
    if flag_swpd_free or flag_si or flag_so:
        print_swap_usage(swap_usage_by_process())
    else:
        if flag_swpd:
            print bcolors.WARNING + "There is some memory in SWAP but it is not critical and not actively used by system now :" + bcolors.ENDC
            print bcolors.WARNING + "Free SWAP memory %% %s: " % swap_free_percent + bcolors.ENDC
        else:
            print bcolors.OKGREEN + "SWAP is not in use" + bcolors.ENDC

    return

def mem_usage_by_process_analizer():
    new_list = mem_usage_by_process()
    for i in new_list:
        print "PNAME: %-12s PID: %-5s Memory Concumpsion: %d MB" % (i[2],i[0],int(i[1])/1024)


def cpu_analizer(vmstat_res,proc_usage_by_pr,la,cpu_count):
    print '\n',
    print bcolors.OKBLUE + 'CPU STATISTICS' + bcolors.ENDC
    print '\n',
    flag_id,flag_wa,flag_us,flag_sy,flag_la,flag_90=False, False,False,False,False,False
    for idle in vmstat_res['id']:
        if int(idle) < cpu_critical_idle:
            flag_id = True

    for wa in vmstat_res['wa']:
        if int(wa)> cpu_critical_wa:
            flag_wa = True

    for us in vmstat_res['us']:
        if int(us) > cpu_critical_us:
            flag_us = True

    for sy in vmstat_res['sy']:
        if int(sy) > cpu_critical_sy:
            flag_sy = True

    if int(la[1]) > int(cpu_count):
        flag_la = True

    for value in proc_usage_by_pr.values():
        for i in value:
            if int(i[3]) > cpu_critical_process_usage:
                flag_90 = True
                pass

    if flag_id:
#        flag_90_f = False
        print bcolors.FAIL + 'CPU idle is too low:' + bcolors.ENDC
        print 'id values: %(id)s' % vmstat_res
        print 'wa values: %(wa)s' % vmstat_res
        print 'us values: %(us)s' % vmstat_res
        print 'sy values: %(sy)s' % vmstat_res
        print '\n',
        print 'Load Average is', la
#        print '\n'
        if flag_wa:
            print bcolors.FAIL + "wa is too high. Please check hdd load" + bcolors.ENDC
        if flag_us:
            print bcolors.FAIL +  "us load is too high. Please check most consuming programms" + bcolors.ENDC
        if flag_sy:
            print bcolors.FAIL + "sy load is too high. It can be high I/O usage or a lot of system calls. sy - means the time the CPU has spent running the kernel and its processes" + bcolors.ENDC
        if flag_la:
            print bcolors.FAIL + "Load average is more than amount of CPU. Please check monitor graphs and compare load with other days" + bcolors.ENDC
        print '\n',
        print bcolors.OKBLUE + "CPU load by the most consuming programs: " + bcolors.ENDC
        for key, value in proc_usage_by_pr.items():
            for i in proc_usage_by_pr[key]:
                print "PID: %s, programm: %s, CPU consumption: %s " % (key, i[0],i[3])
#            print '\n',
    else:
        print bcolors.OKGREEN + "CPU idle is OK" + bcolors.ENDC

    if flag_90:
        print bcolors.FAIL + "Some processes consume > 90% CPU:" + bcolors.ENDC
        for key, value in proc_usage_by_pr.items():
            for i in proc_usage_by_pr[key]:
                if int(i[3]) > cpu_critical_process_usage:
                    print "PID: %s, programm: %s, CPU consumption: %s " % (key, i[0],i[3])
        print '\n',
    else:
        print bcolors.OKGREEN + "There are NO processes that consumes > 90% CPU" + bcolors.ENDC


def io_analyzer(iostat_res,iotop_res):
    print '\n',
    print bcolors.OKBLUE + 'IO STATISTICS:' + bcolors.ENDC
#    print '\n',
    util_flag=False
    util_flag_global=False
    for key, value in iostat_res.items():
        for i in value:
            if i[0]=='%util':
                for c in i[1:]:
#                    print "c is ", c
                    num=re.search(r'(\d+)\.',c)
                    if num:
                        if int(num.group(1)) >= hdd_critical_utilization:
                            util_flag=True
                            util_flag_global=True
                        else:
                            util_flag=False
                    if util_flag:
                        print bcolors.FAIL + "IO %%util is high: %s on %s" % (c,key) + bcolors.ENDC
    print '\n',
    if util_flag_global:
        print bcolors.OKBLUE + "Find the most consuming I/0 programs below: " + bcolors.ENDC
        print '\n',
        for key, value in iotop_res.items():
            print "PID: %-5s USER: %-10s READ: %-8s K/s WRITE: %-8s K/s IO %%: %-2s COMMAND: %-15s" % (key,value[0],value[1],value[2],value[4],value[5])
    if not util_flag_global:
        print bcolors.OKGREEN + "I/0 utilization is OK" + bcolors.ENDC
#    print iotop_res

def net_analyzer(net_stat_info,net_queue_info,ping_info_lizard,ping_info_google,dns_info):
    print '\n',
    print bcolors.OKBLUE + "NET STATISTICS" + bcolors.ENDC
    print '\n',
    imp_values=['RX-ERR','RX-DRP','TX-ERR','TX-DRP']
    flag_ping_porta,flag_ping_google,flag_dns=False,False,False
    flag={}
#    print net_stat_info
    for key,value in net_stat_info.items():
        for c in value:
            values=[]
            values.append(key)
            if c[0] in imp_values:
                count=0
                for i in c[1:]:
                    if int(i) > 0:
                        if i not in values:
                            values.append(i)
                            count = count+1
                if count > 1:
                    flag[c[0]]=values
    if flag:
#        print flag
        for key, value in flag.items():
            print bcolors.FAIL + 'There are problems on interface %s: %s %s' % (value[0],key,value[1:]) + bcolors.ENDC
    else:
        print bcolors.OKGREEN + "Net interfaces have no packet drops" + bcolors.ENDC

    if net_queue_info:
        print bcolors.WARNING + 'High Queues on NET interfaces: ' + bcolors.ENDC
        print "Proto Recv-Q Send-Q Local Address             Foreign Address    PID/Program name"
        for i in net_queue_info:
            print i
    else:
        print bcolors.OKGREEN + "Interfaces net queues are OK" + bcolors.ENDC

#        print net_queue_info
#        for k, v in net_queue_info.items():
#            print 'IP/program: %s Queue(proto,Send-Q,Recv-Q): %s' % (k, v)
    if int(ping_info_lizard[0]) != 0:
        flag_ping_porta=True

    if int(ping_info_google[0]) != 0:
        flag_ping_google=True

    if not dns_info:
        flag_dns=True

    if flag_ping_google:
        print bcolors.FAIL + "There are some issues with network: ping google.com failed!" + bcolors.ENDC

    if flag_ping_porta:
        print bcolors.FAIL + "There are some issues with network: ping 193.28.87.4(lizard) failed!" + bcolors.ENDC
        print bcolors.FAIL + "Packet loss:", ping_info_lizard[0] + bcolors.ENDC

    if not flag_ping_google and not flag_ping_porta:
        print bcolors.OKGREEN + 'Ping is OK' + bcolors.ENDC

    if flag_dns:
        print bcolors.FAIL + "There are some issues with DNS: can't resolve google.com " + bcolors.ENDC
        print bcolors.FAIL + "Packet loss:", ping_info_google[0] + bcolors.ENDC
    else:
        print bcolors.OKGREEN + 'DNS is OK' + bcolors.ENDC

def free_space_analyzer(fs_info):
    print '\n',
    print bcolors.OKBLUE + "HARD DRIVE FREE SPACE: " + bcolors.ENDC
    print '\n',
    if fs_info:
        print bcolors.FAIL + "Free space on some partitions is critical!" + bcolors.ENDC
        print "Filesystem               Size  Used Avail Use% Mounted on"
        for key, value in fs_info.items():
            print '%s %s   %s  %s   %s   %s' % (key,value[0],value[1],value[2],value[3],value[4])
    else:
        print bcolors.OKGREEN + "HD FREE SPACE IS OK " + bcolors.ENDC

#Parsing arguments and gathering the info:

args = parser.parse_args()

#SET in queue
get_vm_stats_q= MyQueue()
get_iostat_q=MyQueue()
get_iotop_q=MyQueue()
get_net_stat_q=MyQueue()
#dns_check_q=MyQueue()
ping_lizard_q = MyQueue()
ping_google_q = MyQueue()
get_net_queue_q=MyQueue()
cpu_count_q=MyQueue()
get_la_q=MyQueue()
get_proc_usage_by_pr_q=MyQueue()
mem_usage_by_process_q=MyQueue()
swap_usage_by_process_q=MyQueue()
check_free_space_q=MyQueue()

#create threading objects
get_vm_stats_thread = threading.Thread(target=get_vm_stats)
get_iostat_thread = threading.Thread(target=get_iostat)
get_iotop_thread = threading.Thread(target=get_iotop)
get_net_stat_thread=threading.Thread(target=get_net_stat)
#dns_check_thread=threading.Thread(target=dns_check)
ping_lizard_thread=threading.Thread(target=ping_lizard)
ping_google_thread=threading.Thread(target=ping_google)
get_net_queue_thread=threading.Thread(target=get_net_queue)
cpu_count_thread=threading.Thread(target=cpu_count)
get_la_thread=threading.Thread(target=get_la)
get_proc_usage_by_pr_thread=threading.Thread(target=get_proc_usage_by_pr)
mem_usage_by_process_thread=threading.Thread(target=mem_usage_by_process)
swap_usage_by_process_thread=threading.Thread(target=swap_usage_by_process)
check_free_space_thread=threading.Thread(target=check_free_space)

check_software()

if len(sys.argv) < 2:
    print "run sysload.py --h for help"
    sys.exit(0)

print "Please wait ~ %s seconds while gathering statistics" % get_stat_time

if args.all:
    args.cpu = True
    args.mem = True
    args.io = True
    args.net = True
    args.fs = True

if args.cpu or args.mem:
    get_vm_stats_thread.start()

if args.cpu:
    get_proc_usage_by_pr_thread.start()
    get_la_thread.start()
    cpu_count_thread.start()

if args.mem:
    mem_info=get_mem_info()
    mem_usage_by_process_thread.start()

if args.io:
    get_iostat_thread.start()
    get_iotop_thread.start()

if args.net:
    get_net_stat_thread.start()
    get_net_queue_thread.start()
    ping_lizard_thread.start()
    ping_google_thread.start()
#    dns_check_thread.start()

# Get results:
if args.cpu or args.mem:
    vmstat_res=get_vm_stats_q.get()

if args.cpu:
    proc_usage_by_pr=get_proc_usage_by_pr_q.get()
    la=get_la_q.get()
    cpu_count=cpu_count_q.get()
    cpu_analizer(vmstat_res,proc_usage_by_pr,la,cpu_count)

if args.mem:
    mem_usage_by_process_res=mem_usage_by_process_q.get()
    mem_analizer(vmstat_res)

if args.io:
    iostat_res=get_iostat_q.get()
    iotop_res=get_iotop_q.get()
    io_analyzer(iostat_res,iotop_res)

if args.net:
    net_stat_info = get_net_stat_q.get()
    net_queue_info = get_net_queue_q.get()
    ping_info_lizard = ping_lizard_q.get()
    ping_info_google = ping_google_q.get()
    dns_info = dns_check()
    net_analyzer(net_stat_info,net_queue_info,ping_info_lizard,ping_info_google,dns_info)

if args.fs:
    free_space_info = check_free_space()
    free_space_analyzer(free_space_info)
