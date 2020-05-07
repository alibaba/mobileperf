# encoding:utf-8
'''
@author:     look

@copyright:  1999-2020 Alibaba.com. All rights reserved.

@license:    Apache Software License 2.0

@contact:    390125133@qq.com
'''
from __future__ import division
import csv
import heapq
import os
import re
import os, sys
import threading
import time
from collections import OrderedDict

from datetime import datetime
import traceback
BaseDir = os.path.dirname(__file__)
sys.path.append(os.path.join(BaseDir, '../..'))

from mobileperf.android.tools.androiddevice import AndroidDevice
from mobileperf.common.utils import TimeUtils
from mobileperf.common.log import logger
from mobileperf.android.globaldata import RuntimeData

class CpuSnapshot(object):
    '''
    统计整机cpu使用率
    '''
    def __init__(self):
        self.cpu_jiffs = 0
        self.cpu_rate = 0
        self.system_rate = 0
        self.user_rate = 0

class CpuPckSnapshot(object):
    '''
    统计进程cpu使用率
    '''
    def __init__(self, packagename):
        self.pckagename = packagename
        self.pid = -1
        self.uid = 0
        self.p_cpu_jiffs = 0
        self.p_cpu_rate = 0

    def __repr__(self):
        return "CpuPckSnapshot,"+ ", packagename: "  + str(self.pckagename) + "pid: " + str(self.pid) + ", uid: " +str(self.uid) \
               + ", p_cpu_rate: " + str(self.p_cpu_rate) + ", p_cpu_jiffs: " + str(self.p_cpu_jiffs)
    

class CpuCollector(object):
    '''
        搜集cpu信息的一个类
        '''

    def __init__(self, device, packages, interval=1.0, timeout=24 * 60 * 60, cpu_queue = None):
        '''

        :param device: 具体的设备实例
        :param packages: 应用的包名 列表
        :param interval: 数据采集的频率
        :param timeout: 采集的超时，超过这个时间，任务会停止采集
        '''
        self.device = device
        self.packages = packages
        self._interval = interval
        self._timeout = timeout
        self._stop_event = threading.Event()
        self.stop_device_event = threading.Event()
        self._init_device_data()
        self._init_pck_data()
        #取得cpu_queue,以便生产数据
        self.cpu_queue = cpu_queue


    def _init_device_data(self):
        self._init_cpu = True
        self.o_cpu = []

    def _init_pck_data(self):
        self.o_a_cpu = self.c_a_cpu = 0
        self.o_p_cpu = self.c_p_cpu = 0
        # self.o_pcpu_dic = {}
        # self.o_pkey_list = []#用来存放o_pcpu_dic中的key
        # self.o_dkey_list = []

    def start(self,start_time):
        '''
        启动一个搜集器来启动一个新的线程搜集cpu信息
        :return:
        '''
        self.collect_device_cpu_thread = threading.Thread(target=self._collect_cpu_thread, args=(start_time,))
        self.collect_device_cpu_thread.start()
        logger.debug("INFO: CpuCollector  started...")

    def stop(self):
        '''
        停止cpu的搜集器
        :return:
        '''
        logger.debug("INFO: CpuCollector  stop...")
        # if (self.collect_package_cpu_thread.isAlive()):
        #     self._stop_event.set()
        #     self.collect_package_cpu_thread.join(timeout=1)
        #     self.collect_package_cpu_thread = None

        if (self.collect_device_cpu_thread.isAlive()):
            self.stop_device_event.set()
            self.collect_device_cpu_thread.join(timeout=1)
            self.collect_device_cpu_thread = None
            if self.cpu_queue:
                self.cpu_queue.task_done()

    # @profile
    def _collect_cpu_thread(self,start_time):
        end_time = time.time() + self._timeout
        cpu_title = ["datetime", "device_cpu_rate%", "user%", "system%"]
        cpu_file = os.path.join(RuntimeData.package_save_path, 'cpuinfo.csv')
        for i in range(0,len(self.packages)):
            cpu_title.append("package","pid","pid_cpu%")
        cpu_title.append("total_pid_cpu%")
        try:
            with open(cpu_file, 'a+') as df:
                csv.writer(df, lineterminator='\n').writerow(cpu_title)
                if self.cpu_queue:
                    cpu_file_dic = {'cpu_file': cpu_file}
                    self.cpu_queue.put(cpu_file_dic)
        except RuntimeError as e:
            logger.error(e)
        while not self.stop_device_event.is_set() and time.time() < end_time:
            try:
                before = time.time()
                logger.debug("into _collect_cpu_thread loop thread is : " + str(
                        threading.current_thread().name))
                cpu_info = self._get_cpu_usage()
                logger.debug(" get cpu info: " + str(cpu_info))


                cpu_pck_info = self._get_pck_cpu_usage()
                cpu_pck_info = self._trim_pakcage_info(cpu_pck_info, cpu_info)
                collection_time = time.time()
                logger.debug(" collection time in cpu is : " + TimeUtils.getCurrentTime())
                if cpu_pck_info.pid == -1:
                    logger.debug("cpu_pck pid is -1")
                    continue
                gather_list = [collection_time, cpu_info.cpu_rate, cpu_info.user_rate, cpu_info.system_rate]
                if self.cpu_queue:
                    self.cpu_queue.put(gather_list)
                for i in range(0,len(self.packages)):
                    gather_list.append()

                # 添加进程 总cpu使用率
                gather_list.append()

                if not self.cpu_queue:#为了让单个脚本运行
                    gather_list[0] = TimeUtils.formatTimeStamp(gather_list[0])
                    try:
                        with open(cpu_file, 'a+') as f:
                            csv.writer(f, lineterminator='\n').writerow(gather_list)
                            logger.debug("write to file:"+cpu_file)
                            logger.debug(gather_list)
                    except RuntimeError as e:
                        logger.error(e)

                time_consume = time.time() - before
                logger.debug(" _collect_cpu_thread time consume for device cpu usage: " + str(format(time_consume, '0.2f')))
                delta_inter = self._interval - time_consume
                if delta_inter > 0:
                    time.sleep(delta_inter)
            except Exception as e:
                logger.error("an exception hanpend in cpu thread , reason unkown!")
                s = traceback.format_exc()
                logger.debug(s)#将堆栈信息打印到log中
                if self.cpu_queue:
                    self.cpu_queue.task_done()
        logger.debug("stop event is set or timeout")

    
    def _trim_pakcage_info(self,cpu_pck_info, cpu_info):
        if cpu_pck_info and cpu_info:
            if cpu_info.cpu_rate < cpu_pck_info.p_cpu_rate:
                cpu_pck_info.p_cpu_rate = cpu_info.cpu_rate
        return cpu_pck_info

    # 第一行是所有核汇总  /proc/stat包含了所有cpu的数据
    def _read_proc(self):
        results = self.device.adb.run_shell_cmd("cat /proc/stat")
        results = results.replace('\r','').splitlines()
        cpu_list = []
        # cpu   user    nice   system     idle     iowait  irq softirq steal guest guest_nice
        # cpu  31646496 1046389 11192565 26694355   148314    0    60984      0      0     0
        # cpu后面会有两个空格 所以user下标从2开始
        if len(results):
            cpu_list = results[0].split(" ")
        return cpu_list

    def _read_pck_proc(self, pid):
        results = self.device.adb.run_shell_cmd("cat /proc/%d/stat"%pid)
        results = results.replace('\r', '').splitlines()
        cpu_list = []
        if len(results):
            #temp list的格式如下:
            '''
            5165 (alibaba.ailabs) S 347 346 0 0 -1 4194624 12601838 23521 226 3 384520 5228
            6 27 133 20 0 84 0 7682849 1177718784 43541 18446744073709551615 1 1 0 0 0 0 461
            2 0 38122 18446744073709551615 0 0 17 6 0 0 0 0 0 0 0 0 0 0 0 0 0
           '''
            #其中1:packagename, 13: user time , 14: system time
            # utime 该任务在用户态运行的时间，单位为jiffies
            # stime 该任务在核心态运行的时间，单位为jiffies
            temp_list = results[0].split(" ")
            cpu_list.append(temp_list[1])
            cpu_list.append(temp_list[13])
            cpu_list.append(temp_list[14])
            logger.debug(cpu_list)
        return cpu_list

    def _get_pck_cpu_usage(self):
        '''
        如果获取多个进程的cpu数据，这个方法要读取多次，太复杂，改用top top一次能拿到所有进程的数据
        :return:
        '''
        for i in range(0,len(self.packages)):
            cpu_pck_snapshot = CpuPckSnapshot(self.packages[i])
            list = self._get_pckinfo_from_ps(self.packages[i])
            logger.debug("pids list len: "+str(len(list)))
            if len(list) == 1:#目前应用cpu的信息是按照pid来统计的，在包名完全确定的情况下返回对应的一条记录
                try:
                    for item in list:
                        logger.debug(item)
                        cpu_pck_snapshot.uid = item['uid']
                        cpu_pck_snapshot.pid = item['pid']
                        cpu_pck_snapshot.pckagename = item['proc_name']
                        result1 = self._read_pck_proc(item['pid'])
                        t_result1 = self._read_proc()
                        self.c_p_cpu = int(result1[1]) + int(result1[2])
                        cpu_pck_snapshot.p_cpu_jiffs = self.c_p_cpu

                        if len(t_result1) > 2:
                            self.c_a_cpu = 0
                            i = 2
                            while i < len(t_result1):
                                self.c_a_cpu += int(t_result1[i])
                                i = i+1
                            logger.debug(" pckage cpu calculator all cpu current is : " + str(self.c_a_cpu) + ", all cpu old is : " + str(self.o_a_cpu))
                            logger.debug(" pckage cpu calculator package current cpu is : " + str(self.c_p_cpu) + " package old cpu is : " +str(self.o_p_cpu))

                        p_delta_cpu = self.c_p_cpu - self.o_p_cpu
                        a_delta_cpu = self.c_a_cpu - self.o_a_cpu
                        logger.debug(" package delta_cpu : " + str(p_delta_cpu) + ", all delta cpu: " + str(a_delta_cpu))

                        if 0 != a_delta_cpu:
                            tmp = round((p_delta_cpu / a_delta_cpu) * 100, 2)#caculate package cpu rate
                            cpu_pck_snapshot.p_cpu_rate = self._trim_value(tmp)
                        self.o_p_cpu = self.c_p_cpu
                        self.o_a_cpu = self.c_a_cpu
                except Exception as e:
                    logger.debug("can't cat proc/pid/stat, error message: ")
                    logger.error(e)
                except BaseException as e:#发生过一次异常退出，上面的excepion没有看出什么异常，发生在2018-04-06 09:50:05,413， 加入这个在monitor下
                    logger.debug('BaseException happended in _get_pck_cpu_usage error: ')
                    logger.error(e)
            elif len(list) > 1:#理论上由于在ps应用中添加的过滤信息，这个判断不会进来，为了增加一个应用多个pids的适配，现将算法放在这，以便后续扩展,
                '''
                更新下该问题在HOOK5shang 出现过，即完全相同的一个包名出现了多个pid：       
                '''
                logger.debug(" cpu pck all is zombie: " + str(self._all_process_is_zombie(list)))
                if self._all_process_is_zombie(list):#如果这个list中的进程都是僵尸进程直接返回零
                    logger.debug("all process is zombile list len: " + str(len(list)))
                    item = list[-1]#多个僵尸进程返回最后一个
                    cpu_pck_snapshot.uid = item['uid']
                    cpu_pck_snapshot.pid = item['pid']
                    cpu_pck_snapshot.pckagename = item['proc_name']
                    cpu_pck_snapshot.p_cpu_rate = 0
                    cpu_pck_snapshot.p_cpu_jiffs = 0
                    return cpu_pck_snapshot
                tem_pck_cpu = 0
                for item in list:
                    logger.debug(item)
                    # if self.o_pcpu_dic[dic_pck_key]:
                    #     self.o_p_cpu = self.o_pcpu_dic[dic_pck_key]
                    # else:
                    #     self.o_p_cpu = 0
                    # if self.o_pcpu_dic[dic_device_key]:
                    #     self.o_a_cpu = self.o_pcpu_dic[dic_device_key]
                    # else:
                    #     self.o_a_cpu = 0
                    is_zobiem = (item['status'] == 'Z')
                    if not is_zobiem:#只统计非僵尸进程的cpu的值
                        cpu_pck_snapshot.uid = item['uid']
                        cpu_pck_snapshot.pid = item['pid']
                        cpu_pck_snapshot.pckagename = item['proc_name']

                        result1 = self._read_pck_proc(item['pid'])
                        logger.debug(" have zombie process not zimbie process, result1 " + str(result1))
                        t_result1 = self._read_proc()
                        tem_pck_cpu += int(result1[1]) + int(result1[2])#如果由多个非僵尸进程，就累加，目前没有碰到过，这种情况
                        self.c_p_cpu = tem_pck_cpu
                        cpu_pck_snapshot.p_cpu_jiffs = self.c_p_cpu

                        if len(t_result1) > 2:
                            self.c_a_cpu = 0
                            i = 2
                            while i < len(t_result1):
                                self.c_a_cpu += int(t_result1[i])
                                i = i+1
                            logger.debug(" pckage cpu calculator all cpu current is : " + str(self.c_a_cpu) + ", all cpu old is : " + str(self.o_a_cpu))
                            logger.debug(" pckage cpu calculator package current cpu is : " + str(self.c_p_cpu) + " package old cpu is : " +str(self.o_p_cpu))

                        p_delta_cpu = self.c_p_cpu - self.o_p_cpu
                        a_delta_cpu = self.c_a_cpu - self.o_a_cpu
                        logger.debug(" package delta_cpu : " + str(p_delta_cpu) + ", all delta cpu: " + str(a_delta_cpu))

                        if 0 != a_delta_cpu:
                            tmp = round((p_delta_cpu / a_delta_cpu) * 100, 2)#caculate package cpu rate
                            cpu_pck_snapshot.p_cpu_rate = self._trim_value(tmp)

                        self.o_p_cpu = self.c_p_cpu
                        self.o_a_cpu = self.c_a_cpu

                            # dic_pck_key = item['proc_name'] + str(item['pid']) + "pcpu"
                            # dic_device_key = item['proc_name'] + str(item['pid']) + "dcpu"

                            # self.o_pcpu_dic[dic_pck_key] = self.c_p_cpu
                            # self.o_pcpu_dic[dic_device_key] = self.c_a_cpu
                            # self.o_pkey_list.append(dic_pck_key)
                            # self.o_dkey_list.append(dic_device_key)

            else:
                logger.debug("cpu _get_pck_cpu_usage no process found for : " + self.packages)
        return cpu_pck_snapshot

    def _all_process_is_zombie(self,list):
        for item in list:
            is_zombie = (item['status'] == 'Z')
            if not is_zombie:
                return False
        return True


    def _get_cpu_usage(self):
        '''
        通过/proc/stat计算整机cpu使用率
        :return:
        '''
        cpu_snapshot = CpuSnapshot()
        if self._init_cpu:
            self._init_cpu = False
            self.o_cpu = self._read_proc()
            logger.debug("init cpu proc o list: " + str(self.o_cpu))
            time.sleep(0.25)#为了保证有cpu的数据产生，睡眠250ms
            logger.debug("init cpu after sleep 250ms")
            self.n_cpu = self._read_proc()
            logger.debug("init cpu proc n list: " +str(self.n_cpu))
            cpu_snapshot.cpu_rate = self._get_total_cpurate(self.n_cpu, self.o_cpu)
            cpu_snapshot.user_rate = self._get_user_cpurate(self.n_cpu, self.o_cpu)
            cpu_snapshot.system_rate = self._get_sys_cpurate(self.n_cpu, self.o_cpu)
            cpu_snapshot.cpu_jiffs = self._get_cpu_jif(self.n_cpu)
            self.o_cpu = self.n_cpu
        else:
            self.n_cpu = self._read_proc()
            logger.debug("cpu proc list: " + str(self.n_cpu))
            cpu_snapshot.cpu_rate = self._get_total_cpurate(self.n_cpu, self.o_cpu)
            cpu_snapshot.user_rate = self._get_user_cpurate(self.n_cpu, self.o_cpu)
            cpu_snapshot.system_rate = self._get_sys_cpurate(self.n_cpu, self.o_cpu)
            cpu_snapshot.cpu_jiffs = self._get_cpu_jif(self.n_cpu)
            self.o_cpu = self.n_cpu
        return cpu_snapshot

    def _get_cpu_jif(self, n_cpu):
        '''
        计算从开机到最近一次采集的cpu的总jiffies
        :param n_cpu:
        :return:
        '''
        cpu_jif = 0
        if n_cpu:
            cpu_jif = int(n_cpu[2]) + int(n_cpu[3]) + int(n_cpu[4]) + int(n_cpu[5]) + \
                      int(n_cpu[6]) + int(n_cpu[7]) + int(n_cpu[8])
        return cpu_jif

    def _get_sys_cpurate(self, n_cpu, o_cpu):
        sys_rate = 0
        if n_cpu and o_cpu:
            n_cpu_used = int(n_cpu[2]) + int(n_cpu[3]) + int(n_cpu[4]) + \
                         int(n_cpu[6]) + int(n_cpu[7]) + int(n_cpu[8])
            n_cpu_idle = int(n_cpu[5])
            n_cpu_sys = int(n_cpu[4])

            o_cpu_used = int(o_cpu[2]) + int(o_cpu[3]) + int(o_cpu[4]) + \
                         int(o_cpu[6]) + int(o_cpu[7]) + int(o_cpu[8])
            o_cpu_idle = int(o_cpu[5])
            o_cpu_sys = int(o_cpu[4])
            delta_cpu_jif = (n_cpu_used + n_cpu_idle) - (o_cpu_used + o_cpu_idle)

            if delta_cpu_jif != 0:
                temp = round(((n_cpu_sys - o_cpu_sys) / delta_cpu_jif) * 100, 2)
                sys_rate = self._trim_value(temp)
            # logger.debug(" cpu device get sys rate: " + str(sys_rate))
        return sys_rate

    def _get_total_cpurate(self, n_cpu, o_cpu):
        cpu_rate = 0
        if n_cpu and o_cpu:
            logger.debug("_ into cpu get_total_cpurate ----- ")
            n_cpu_used = int(n_cpu[2]) + int(n_cpu[3]) + int(n_cpu[4]) + \
                         int(n_cpu[6]) + int(n_cpu[7]) + int(n_cpu[8])
            n_cpu_idle = int(n_cpu[5])

            o_cpu_used = int(o_cpu[2]) + int(o_cpu[3]) + int(o_cpu[4]) + \
                         int(o_cpu[6]) + int(o_cpu[7]) + int(o_cpu[8])
            o_cpu_idle = int(o_cpu[5])
            delta_cpu_jif = (n_cpu_used + n_cpu_idle) - (o_cpu_used + o_cpu_idle)
            logger.debug("---------- delta_cpu_jif: " + str(delta_cpu_jif))

            if delta_cpu_jif != 0:
                temp = round(((n_cpu_used - o_cpu_used) / delta_cpu_jif) * 100.00, 2)
                cpu_rate = self._trim_value(temp)
            logger.debug(" cpu device get cpu_rate: " +str(cpu_rate))
        return cpu_rate

    def _get_user_cpurate(self, n_cpu, o_cpu):
        user_rate = 0
        if n_cpu and o_cpu:
            n_cpu_used = int(n_cpu[2]) + int(n_cpu[3]) + int(n_cpu[4]) + \
                         int(n_cpu[6]) + int(n_cpu[7]) + int(n_cpu[8])
            n_cpu_idle = int(n_cpu[5])
            n_cpu_user = int(n_cpu[2]) + int(n_cpu[3])

            o_cpu_used = int(o_cpu[2]) + int(o_cpu[3]) + int(o_cpu[4]) + \
                         int(o_cpu[6]) + int(o_cpu[7]) + int(o_cpu[8])
            o_cpu_idle = int(o_cpu[5])
            o_cpu_user = int(o_cpu[2]) + int(o_cpu[3])
            delta_cpu_jif = (n_cpu_used + n_cpu_idle) - (o_cpu_used + o_cpu_idle)

            if delta_cpu_jif != 0:
                temp = round(((n_cpu_user - o_cpu_user) / delta_cpu_jif) * 100.00, 2)
                user_rate = self._trim_value(temp)
        logger.debug( "cpu device get user rate:" + str(user_rate))
        return user_rate

    def _trim_value(self, value):
        '''

        :param value:
        :return:0到100之间的float值
        '''
        result = value
        if result <= 0.00:
            result = 0
        elif result > 100.00:
            result = 100.0
        return result

    def _get_pckinfo_from_ps(self, packagename):
        return self.device.adb.get_pckinfo_from_ps(packagename)


class CpuMonitor(object):
    '''
    cpu 监控类，监控cpu信息， 启动和终止cpu信息的获取
    '''

    def __init__(self, device_id, packages, interval=1.0, timeout=24 * 60 * 60, cpu_queue = None):
        self.device = AndroidDevice(device_id)
        if not packages:
            packages = self.device.adb.get_foreground_process().split("#")
        self.cpu_collector = CpuCollector(self.device, packages, interval, timeout, cpu_queue)

    def start(self, start_time):
        '''
        启动一个cpu监控器，监控cpu信息
        :return:
        '''
        self.cpu_collector.start(start_time)
        logger.debug("INFO: CpuMonitor has started...")

    def stop(self):
        self.cpu_collector.stop()
        logger.debug("INFO: CpuMonitor has stopped...")
        # self.gather_data()

    def _get_cpu_collector(self):
        return self.cpu_collector

    def save(self):
        '''
        保存数据在当前目录的/results/Cpu下面
        :return:
        '''
        pass

if __name__ == "__main__":
    monitor = CpuMonitor("", "com.alibaba.ailabs.genie.contacts", 3)  # HT7B81A05143
    monitor.start(TimeUtils.getCurrentTimeUnderline())
    time.sleep(30)
    monitor.stop()


